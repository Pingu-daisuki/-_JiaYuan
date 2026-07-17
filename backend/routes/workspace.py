"""首页工作区、持久化对话与可验证引用接口。"""

from __future__ import annotations

import json
import re
import uuid
from contextlib import closing
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from core.db import get_db_connection
from core.maintenance import run_data_check
from core.processor import VECTOR_WRITE_LOCK, get_vector_collection
from core.tasks import ensure_task_table


router = APIRouter()


class ConversationCreate(BaseModel):
    title: str = "新对话"
    course_id: int | None = None
    retrieval_scope: dict = Field(default_factory=lambda: {"mode": "all"})


class ConversationUpdate(BaseModel):
    title: str | None = None
    course_id: int | None = None
    retrieval_scope: dict | None = None
    pinned: bool | None = None


class MessageCreate(BaseModel):
    role: str
    content: str = ""
    sources: list[dict] = Field(default_factory=list)


class MessageUpdate(BaseModel):
    pinned: bool


class ReviewCreate(BaseModel):
    title: str
    due_at: str
    course_id: int | None = None
    file_id: int | None = None


class ReviewUpdate(BaseModel):
    status: str


class ActivityCreate(BaseModel):
    item_type: str
    item_id: str
    title: str
    course_id: int | None = None


def _scope(value: str | None) -> dict:
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {"mode": "all"}
    except json.JSONDecodeError:
        return {"mode": "all"}


def _conversation(row) -> dict:
    item = dict(row)
    item["pinned"] = bool(item["pinned"])
    item["retrieval_scope"] = _scope(item.pop("retrieval_scope_json", None))
    return item


def _message(row) -> dict:
    item = dict(row)
    item["pinned"] = bool(item["pinned"])
    try:
        item["sources"] = json.loads(item.pop("sources_json") or "[]")
    except json.JSONDecodeError:
        item["sources"] = []
    return item


@router.get("/dashboard")
def dashboard():
    ensure_task_table()
    now = datetime.now()
    seven_days = now + timedelta(days=7)
    with closing(get_db_connection()) as conn:
        deadlines = [dict(row) for row in conn.execute(
            "SELECT * FROM deadlines WHERE COALESCE(is_submitted, 0) = 0 "
            "AND deadline >= ? AND deadline <= ? ORDER BY deadline LIMIT 20",
            (now.isoformat(sep=" ", timespec="seconds"), seven_days.isoformat(sep=" ", timespec="seconds")),
        ).fetchall()]
        documents = [dict(row) for row in conn.execute(
            "SELECT id, file_name, course_id, status, error_message, updated_at, created_at "
            "FROM knowledge_files WHERE status != 'ready' ORDER BY updated_at DESC LIMIT 20"
        ).fetchall()]
        recent_files = [dict(row) for row in conn.execute(
            "SELECT f.id, f.file_name, f.course_id, f.status, f.updated_at, c.course_name "
            "FROM knowledge_files f LEFT JOIN courses c ON c.id=f.course_id "
            "ORDER BY COALESCE((SELECT MAX(a.accessed_at) FROM recent_activity a "
            "WHERE a.item_type='file' AND a.item_id=CAST(f.id AS TEXT)), f.updated_at, f.created_at) DESC LIMIT 8"
        ).fetchall()]
        conversations = [_conversation(row) for row in conn.execute(
            "SELECT c.*, courses.course_name, "
            "(SELECT COUNT(*) FROM conversation_messages m WHERE m.conversation_id=c.id) AS message_count "
            "FROM conversations c LEFT JOIN courses ON courses.id=c.course_id "
            "ORDER BY c.pinned DESC, c.updated_at DESC LIMIT 8"
        ).fetchall()]
        reviews = [dict(row) for row in conn.execute(
            "SELECT r.*, c.course_name FROM review_items r LEFT JOIN courses c ON c.id=r.course_id "
            "WHERE r.status='pending' AND r.due_at <= ? ORDER BY r.due_at LIMIT 12",
            (seven_days.isoformat(timespec="seconds"),),
        ).fetchall()]
        rollcall = [dict(row) for row in conn.execute(
            "SELECT id, title, status, progress, message, updated_at FROM background_tasks "
            "WHERE task_type='rollcall_monitor' ORDER BY updated_at DESC LIMIT 8"
        ).fetchall()]
        task_summary = dict(conn.execute(
            "SELECT SUM(status IN ('queued','running','cancelling')) AS active, "
            "SUM(status IN ('failed','interrupted')) AS failed, "
            "SUM(status IN ('failed','interrupted') AND retryable=1) AS retryable "
            "FROM background_tasks"
        ).fetchone())
    health = run_data_check(False)
    return {
        "deadlines": deadlines,
        "documents": documents,
        "task_summary": {key: int(value or 0) for key, value in task_summary.items()},
        "recent_files": recent_files,
        "conversations": conversations,
        "reviews": reviews,
        "rollcall": rollcall,
        "health": health,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


@router.get("/conversations")
def list_conversations(q: str = Query(default="", max_length=120), course_id: int | None = None):
    clauses = []
    params: list[object] = []
    if q.strip():
        clauses.append("(c.title LIKE ? OR EXISTS (SELECT 1 FROM conversation_messages m WHERE m.conversation_id=c.id AND m.content LIKE ?))")
        needle = f"%{q.strip()}%"
        params.extend([needle, needle])
    if course_id is not None:
        clauses.append("c.course_id IS NULL" if course_id == 0 else "c.course_id=?")
        if course_id != 0:
            params.append(course_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with closing(get_db_connection()) as conn:
        rows = conn.execute(
            f"SELECT c.*, courses.course_name, (SELECT COUNT(*) FROM conversation_messages m WHERE m.conversation_id=c.id) AS message_count "
            f"FROM conversations c LEFT JOIN courses ON courses.id=c.course_id {where} "
            "ORDER BY c.pinned DESC, c.updated_at DESC LIMIT 200",
            params,
        ).fetchall()
    return {"conversations": [_conversation(row) for row in rows]}


@router.post("/conversations", status_code=201)
def create_conversation(req: ConversationCreate):
    conversation_id = uuid.uuid4().hex
    title = (req.title or "新对话").strip()[:120] or "新对话"
    with closing(get_db_connection()) as conn:
        conn.execute(
            "INSERT INTO conversations (id,title,course_id,retrieval_scope_json) VALUES (?,?,?,?)",
            (conversation_id, title, req.course_id or None, json.dumps(req.retrieval_scope, ensure_ascii=False)),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
    return _conversation(row)


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str):
    with closing(get_db_connection()) as conn:
        row = conn.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        messages = conn.execute(
            "SELECT * FROM conversation_messages WHERE conversation_id=? ORDER BY created_at, rowid",
            (conversation_id,),
        ).fetchall()
    if not row:
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"conversation": _conversation(row), "messages": [_message(item) for item in messages]}


@router.patch("/conversations/{conversation_id}")
def update_conversation(conversation_id: str, req: ConversationUpdate):
    fields, values = [], []
    if req.title is not None:
        fields.append("title=?")
        values.append(req.title.strip()[:120] or "新对话")
    if "course_id" in req.model_fields_set:
        fields.append("course_id=?")
        values.append(req.course_id or None)
    if req.retrieval_scope is not None:
        fields.append("retrieval_scope_json=?")
        values.append(json.dumps(req.retrieval_scope, ensure_ascii=False))
    if req.pinned is not None:
        fields.append("pinned=?")
        values.append(int(req.pinned))
    if not fields:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")
    fields.append("updated_at=datetime('now','localtime')")
    values.append(conversation_id)
    with closing(get_db_connection()) as conn:
        cursor = conn.execute(f"UPDATE conversations SET {', '.join(fields)} WHERE id=?", values)
        conn.commit()
        row = conn.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
    if not cursor.rowcount:
        raise HTTPException(status_code=404, detail="对话不存在")
    return _conversation(row)


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str):
    with closing(get_db_connection()) as conn:
        cursor = conn.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
        conn.commit()
    if not cursor.rowcount:
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"message": "对话已删除"}


@router.post("/conversations/{conversation_id}/messages", status_code=201)
def create_message(conversation_id: str, req: MessageCreate):
    if req.role not in {"user", "assistant"}:
        raise HTTPException(status_code=400, detail="消息角色不合法")
    message_id = uuid.uuid4().hex
    with closing(get_db_connection()) as conn:
        if not conn.execute("SELECT 1 FROM conversations WHERE id=?", (conversation_id,)).fetchone():
            raise HTTPException(status_code=404, detail="对话不存在")
        conn.execute(
            "INSERT INTO conversation_messages (id,conversation_id,role,content,sources_json) VALUES (?,?,?,?,?)",
            (message_id, conversation_id, req.role, req.content, json.dumps(req.sources, ensure_ascii=False)),
        )
        conn.execute("UPDATE conversations SET updated_at=datetime('now','localtime') WHERE id=?", (conversation_id,))
        conn.commit()
        row = conn.execute("SELECT * FROM conversation_messages WHERE id=?", (message_id,)).fetchone()
    return _message(row)


@router.patch("/messages/{message_id}")
def update_message(message_id: str, req: MessageUpdate):
    with closing(get_db_connection()) as conn:
        cursor = conn.execute("UPDATE conversation_messages SET pinned=? WHERE id=?", (int(req.pinned), message_id))
        conn.commit()
    if not cursor.rowcount:
        raise HTTPException(status_code=404, detail="消息不存在")
    return {"id": message_id, "pinned": req.pinned}


@router.delete("/messages/{message_id}")
def delete_message(message_id: str):
    with closing(get_db_connection()) as conn:
        cursor = conn.execute("DELETE FROM conversation_messages WHERE id=?", (message_id,))
        conn.commit()
    if not cursor.rowcount:
        raise HTTPException(status_code=404, detail="消息不存在")
    return {"message": "消息已删除"}


@router.get("/conversations/{conversation_id}/export.md", response_class=PlainTextResponse)
def export_conversation(conversation_id: str):
    data = get_conversation(conversation_id)
    lines = [f"# {data['conversation']['title']}", ""]
    for message in data["messages"]:
        lines.extend(["## 你" if message["role"] == "user" else "## JiaYuan", "", message["content"], ""])
        if message["sources"]:
            lines.append("引用：" + "、".join(source.get("file_name", "未知资料") for source in message["sources"]))
            lines.append("")
    return "\n".join(lines)


@router.post("/activity")
def record_activity(req: ActivityCreate):
    with closing(get_db_connection()) as conn:
        conn.execute(
            "DELETE FROM recent_activity WHERE item_type=? AND item_id=?",
            (req.item_type, req.item_id),
        )
        conn.execute(
            "INSERT INTO recent_activity (item_type,item_id,title,course_id) VALUES (?,?,?,?)",
            (req.item_type, req.item_id, req.title[:180], req.course_id),
        )
        conn.execute("DELETE FROM recent_activity WHERE id NOT IN (SELECT id FROM recent_activity ORDER BY accessed_at DESC LIMIT 200)")
        conn.commit()
    return {"message": "已记录"}


@router.post("/reviews", status_code=201)
def create_review(req: ReviewCreate):
    review_id = uuid.uuid4().hex
    with closing(get_db_connection()) as conn:
        conn.execute(
            "INSERT INTO review_items (id,title,course_id,file_id,due_at) VALUES (?,?,?,?,?)",
            (review_id, req.title.strip()[:180], req.course_id, req.file_id, req.due_at),
        )
        conn.commit()
    return {"id": review_id}


@router.patch("/reviews/{review_id}")
def update_review(review_id: str, req: ReviewUpdate):
    if req.status not in {"pending", "completed", "dismissed"}:
        raise HTTPException(status_code=400, detail="复习状态不合法")
    with closing(get_db_connection()) as conn:
        cursor = conn.execute("UPDATE review_items SET status=? WHERE id=?", (req.status, review_id))
        conn.commit()
    if not cursor.rowcount:
        raise HTTPException(status_code=404, detail="复习项不存在")
    return {"id": review_id, "status": req.status}


@router.get("/citations/{file_id}/context")
def citation_context(file_id: int, chunk_index: int | None = None, location_index: int | None = None, query: str = ""):
    with closing(get_db_connection()) as conn:
        file_row = conn.execute(
            "SELECT f.id,f.file_name,f.course_id,f.document_type,c.course_name FROM knowledge_files f "
            "LEFT JOIN courses c ON c.id=f.course_id WHERE f.id=?",
            (file_id,),
        ).fetchone()
        related = conn.execute(
            "SELECT id,file_name,document_type FROM knowledge_files WHERE status='ready' "
            "AND id<>? AND ((course_id IS NULL AND ? IS NULL) OR course_id=?) ORDER BY updated_at DESC LIMIT 6",
            (file_id, file_row["course_id"] if file_row else None, file_row["course_id"] if file_row else None),
        ).fetchall() if file_row else []
    if not file_row:
        raise HTTPException(status_code=404, detail="引用文件不存在")
    where = {"file_id": file_id}
    with VECTOR_WRITE_LOCK:
        stored = get_vector_collection().get(where=where, include=["documents", "metadatas"])
    chunks = []
    for document, metadata in zip(stored.get("documents") or [], stored.get("metadatas") or []):
        idx = metadata.get("chunk_index")
        location = metadata.get("location_index") or metadata.get("page")
        distance = abs(int(idx or 0) - int(chunk_index or idx or 0))
        location_match = location_index is not None and int(location or -1) == location_index
        if chunk_index is not None and distance <= 1 or chunk_index is None and (location_match or location_index is None):
            chunks.append({"text": document, "metadata": metadata, "distance": distance})
    chunks.sort(key=lambda item: (item["distance"], int(item["metadata"].get("chunk_index") or 0)))
    selected = chunks[:3]
    terms = list(dict.fromkeys(re.findall(r"[\w\u4e00-\u9fff]{2,}", query)))[:12]
    return {
        "file": dict(file_row),
        "chunks": selected,
        "highlight_terms": terms,
        "related_files": [dict(row) for row in related],
    }
