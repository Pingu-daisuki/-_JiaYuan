"""持久化后台任务登记、取消和重试基础设施。"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import AsyncIterable, AsyncIterator, Callable, Iterable, Iterator
from contextlib import closing
from datetime import datetime

from core.db import get_db_connection


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_STATUSES = {"queued", "running", "cancelling"}
_CALLBACK_LOCK = threading.RLock()
_CANCEL_CALLBACKS: dict[str, Callable[[], None]] = {}
_CANCEL_EVENTS: dict[str, threading.Event] = {}
_RETRY_HANDLERS: dict[str, Callable[[dict], str]] = {}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def ensure_task_table() -> None:
    with closing(get_db_connection()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS background_tasks (
                id TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                message TEXT DEFAULT '',
                log_text TEXT DEFAULT '',
                payload_json TEXT DEFAULT '{}',
                retryable INTEGER NOT NULL DEFAULT 0,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_background_tasks_updated "
            "ON background_tasks(updated_at DESC)"
        )
        conn.commit()


def recover_interrupted_tasks() -> int:
    ensure_task_table()
    with closing(get_db_connection()) as conn:
        cursor = conn.execute(
            """
            UPDATE background_tasks
            SET status = 'interrupted',
                message = '应用退出时任务尚未完成，可点击重试恢复',
                finished_at = ?, updated_at = ?
            WHERE status IN ('queued', 'running', 'cancelling')
            """,
            (_now(), _now()),
        )
        conn.commit()
        return cursor.rowcount


def create_task(
    task_type: str,
    title: str,
    *,
    payload: dict | None = None,
    retryable: bool = False,
) -> str:
    ensure_task_table()
    task_id = uuid.uuid4().hex
    now = _now()
    with closing(get_db_connection()) as conn:
        conn.execute(
            """
            INSERT INTO background_tasks (
                id, task_type, title, status, progress, message, log_text,
                payload_json, retryable, cancel_requested, created_at, updated_at
            ) VALUES (?, ?, ?, 'queued', 0, '等待开始', '', ?, ?, 0, ?, ?)
            """,
            (task_id, task_type, title, json.dumps(payload or {}, ensure_ascii=False), int(retryable), now, now),
        )
        conn.commit()
    with _CALLBACK_LOCK:
        _CANCEL_EVENTS[task_id] = threading.Event()
    return task_id


def update_task(
    task_id: str,
    *,
    status: str | None = None,
    progress: int | None = None,
    message: str | None = None,
    append_log: str | None = None,
) -> None:
    assignments = ["updated_at = ?"]
    values: list[object] = [_now()]
    if status is not None:
        assignments.append("status = ?")
        values.append(status)
        if status == "running":
            assignments.append("started_at = COALESCE(started_at, ?)")
            values.append(_now())
        if status in TERMINAL_STATUSES or status == "interrupted":
            assignments.append("finished_at = ?")
            values.append(_now())
    if progress is not None:
        assignments.append("progress = ?")
        values.append(max(0, min(100, int(progress))))
    if message is not None:
        assignments.append("message = ?")
        values.append(str(message)[:1000])
    if append_log:
        assignments.append("log_text = substr(COALESCE(log_text, '') || ?, -12000)")
        values.append(str(append_log))
    values.append(task_id)
    with closing(get_db_connection()) as conn:
        conn.execute(f"UPDATE background_tasks SET {', '.join(assignments)} WHERE id = ?", values)
        conn.commit()


def _row_to_task(row) -> dict | None:
    if not row:
        return None
    item = dict(row)
    try:
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
    except json.JSONDecodeError:
        item["payload"] = {}
        item.pop("payload_json", None)
    item["retryable"] = bool(item["retryable"])
    item["cancel_requested"] = bool(item["cancel_requested"])
    return item


def get_task(task_id: str) -> dict | None:
    ensure_task_table()
    with closing(get_db_connection()) as conn:
        return _row_to_task(conn.execute("SELECT * FROM background_tasks WHERE id = ?", (task_id,)).fetchone())


def list_tasks(limit: int = 100) -> list[dict]:
    ensure_task_table()
    with closing(get_db_connection()) as conn:
        rows = conn.execute(
            "SELECT * FROM background_tasks ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(500, int(limit))),),
        ).fetchall()
    return [_row_to_task(row) for row in rows]


def is_cancel_requested(task_id: str) -> bool:
    with _CALLBACK_LOCK:
        event = _CANCEL_EVENTS.get(task_id)
    if event is not None:
        return event.is_set()
    with closing(get_db_connection()) as conn:
        row = conn.execute(
            "SELECT cancel_requested FROM background_tasks WHERE id = ?", (task_id,)
        ).fetchone()
    return bool(row and row[0])


def register_cancel_callback(task_id: str, callback: Callable[[], None]) -> None:
    with _CALLBACK_LOCK:
        _CANCEL_CALLBACKS[task_id] = callback


def unregister_cancel_callback(task_id: str) -> None:
    with _CALLBACK_LOCK:
        _CANCEL_CALLBACKS.pop(task_id, None)
        _CANCEL_EVENTS.pop(task_id, None)


def request_cancel(task_id: str) -> dict | None:
    task = get_task(task_id)
    if not task or task["status"] not in ACTIVE_STATUSES:
        return task
    with closing(get_db_connection()) as conn:
        conn.execute(
            "UPDATE background_tasks SET cancel_requested = 1, status = 'cancelling', "
            "message = '正在安全停止', updated_at = ? WHERE id = ?",
            (_now(), task_id),
        )
        conn.commit()
    with _CALLBACK_LOCK:
        callback = _CANCEL_CALLBACKS.get(task_id)
        event = _CANCEL_EVENTS.get(task_id)
        if event:
            event.set()
    if callback:
        try:
            callback()
        except Exception as exc:
            update_task(task_id, message=f"停止回调执行失败，等待任务自行退出：{exc}")
    return get_task(task_id)


def register_retry_handler(task_type: str, handler: Callable[[dict], str]) -> None:
    with _CALLBACK_LOCK:
        _RETRY_HANDLERS[task_type] = handler


def retry_task(task_id: str) -> str:
    task = get_task(task_id)
    if not task:
        raise LookupError("任务不存在")
    if task["status"] in ACTIVE_STATUSES:
        raise RuntimeError("任务仍在运行，不能重试")
    if not task["retryable"]:
        raise RuntimeError("该任务不支持自动重试")
    with _CALLBACK_LOCK:
        handler = _RETRY_HANDLERS.get(task["task_type"])
    if not handler:
        raise RuntimeError("该任务类型尚未注册重试处理器")
    return handler(task["payload"])


def _progress_from_line(line: str, current: int) -> int:
    markers = (
        (("uploaded", "开始处理", "开始初始化"), 5),
        (("parsing", "正在启用", "正在安装"), 20),
        (("OCR", "提取文字", "下载"), 40),
        (("切片", "验证"), 60),
        (("indexing", "向量化"), 75),
        (("批量写入", "探针"), 90),
        (("ready", "初始化完成", "成功转化"), 100),
    )
    for words, progress in markers:
        if any(word in line for word in words):
            return max(current, progress)
    return current


def track_stream(
    task_id: str,
    stream: Iterable[str],
    *,
    failure_tokens: tuple[str, ...] = ("[致命异常]", "___ENGINE_INIT_FAILED___"),
) -> Iterator[str]:
    progress = 0
    failed_message = ""
    pending_log = ""
    last_update = 0.0
    update_task(task_id, status="running", message="任务正在运行")
    try:
        iterator = iter(stream)
        while True:
            if is_cancel_requested(task_id):
                close = getattr(iterator, "close", None)
                if close:
                    close()
                update_task(task_id, status="cancelled", message="任务已取消")
                return
            try:
                line = next(iterator)
            except StopIteration:
                break
            text = str(line)
            previous_progress = progress
            progress = _progress_from_line(text, progress)
            if any(token in text for token in failure_tokens):
                failed_message = text.strip()[-1000:]
            pending_log += text
            now = time.monotonic()
            if now - last_update >= 0.25 or progress != previous_progress or failed_message:
                update_task(task_id, progress=progress, message=text.strip()[-1000:], append_log=pending_log)
                pending_log = ""
                last_update = now
            yield line
        if pending_log:
            update_task(task_id, progress=progress, append_log=pending_log)
        if failed_message:
            update_task(task_id, status="failed", message=failed_message)
        elif is_cancel_requested(task_id):
            update_task(task_id, status="cancelled", message="任务已取消")
        else:
            update_task(task_id, status="completed", progress=100, message="任务已完成")
    except GeneratorExit:
        close = getattr(stream, "close", None)
        if close:
            close()
        if is_cancel_requested(task_id):
            update_task(task_id, status="cancelled", message="任务已取消")
        else:
            update_task(task_id, status="interrupted", message="前端连接中断，可点击重试恢复")
        raise
    except Exception as exc:
        update_task(task_id, status="failed", message=str(exc), append_log=f"\n{exc}\n")
        raise
    finally:
        unregister_cancel_callback(task_id)


async def track_async_stream(
    task_id: str,
    stream: AsyncIterable[str],
    *,
    failure_tokens: tuple[str, ...] = ("[致命错误]", "[错误]"),
) -> AsyncIterator[str]:
    progress = 5
    failed_message = ""
    update_task(task_id, status="running", progress=progress, message="任务正在运行")
    try:
        async for line in stream:
            text = str(line)
            progress = _progress_from_line(text, progress)
            if any(token in text for token in failure_tokens):
                failed_message = text.strip()[-1000:]
            update_task(task_id, progress=progress, message=text.strip()[-1000:], append_log=text)
            yield line
        if is_cancel_requested(task_id):
            update_task(task_id, status="cancelled", message="任务已取消")
        elif failed_message:
            update_task(task_id, status="failed", message=failed_message)
        else:
            update_task(task_id, status="completed", progress=100, message="任务已完成")
    except GeneratorExit:
        update_task(task_id, status="interrupted", message="前端连接中断")
        raise
    except BaseException as exc:
        if is_cancel_requested(task_id):
            update_task(task_id, status="cancelled", message="任务已取消")
        else:
            update_task(task_id, status="interrupted", message=str(exc))
        raise
    finally:
        unregister_cancel_callback(task_id)


ensure_task_table()
