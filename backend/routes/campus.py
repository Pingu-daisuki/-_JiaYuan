# backend/routes/campus.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import asyncio
import json
import threading
from datetime import datetime
from core.db import get_db_connection
from core.campus_core import XmuNativeBot, extract_rollcalls
from core.tasks import (
    create_task,
    get_task,
    register_cancel_callback,
    track_async_stream,
)

router = APIRouter()
_CAMPUS_TABLE_LOCK = threading.Lock()

def ensure_campus_table():
    """原地升级身份表；任何旧版认证资料都不得因字段升级被删除。"""
    with _CAMPUS_TABLE_LOCK:
        conn = get_db_connection()
        try:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS campus_config (
                    student_id TEXT PRIMARY KEY,
                    password TEXT NOT NULL,
                    real_name TEXT DEFAULT '',
                    mode TEXT DEFAULT 'default',
                    check_interval INTEGER DEFAULT 5,
                    answer_threshold INTEGER DEFAULT 0,
                    time_slots TEXT DEFAULT '[]',
                    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
                );
            ''')
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(campus_config)").fetchall()
            }
            missing_columns = {
                "real_name": "TEXT DEFAULT ''",
                "mode": "TEXT DEFAULT 'default'",
                "check_interval": "INTEGER DEFAULT 5",
                "answer_threshold": "INTEGER DEFAULT 0",
                "time_slots": "TEXT DEFAULT '[]'",
                # SQLite 不能通过 ALTER TABLE 添加非恒定时间函数默认值。
                "updated_at": "TEXT DEFAULT NULL",
            }
            for column_name, definition in missing_columns.items():
                if column_name not in columns:
                    conn.execute(
                        f"ALTER TABLE campus_config ADD COLUMN {column_name} {definition}"
                    )
            conn.execute(
                "UPDATE campus_config SET updated_at = datetime('now', 'localtime') "
                "WHERE updated_at IS NULL OR updated_at = ''"
            )
            conn.commit()
        finally:
            conn.close()

# 📝 请求模型拆分
class AccountReq(BaseModel):
    student_id: str
    password: str

class StrategyReq(BaseModel):
    mode: str = "default"
    check_interval: int = Field(default=5, ge=1, le=300)
    answer_threshold: int = Field(default=0, ge=0)
    time_slots: list = []

# 💾 1. 获取所有账号
@router.get("/accounts")
def get_accounts():
    ensure_campus_table()
    conn = get_db_connection()
    rows = conn.execute("SELECT student_id, real_name, mode, check_interval, answer_threshold, time_slots FROM campus_config").fetchall()
    conn.close()
    return [dict(r) for r in rows]

# 👤 2. 独立窗口：仅验证并保存账号信息
@router.post("/account")
async def add_account(req: AccountReq):
    ensure_campus_table()
    bot = XmuNativeBot(student_id=req.student_id, password=req.password)
    
    try:
        await bot.login()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"统一认证失败，请检查密码: {str(e)}")

    try:
        profile_resp = await asyncio.to_thread(bot.session.get, "https://lnt.xmu.edu.cn/api/profile", timeout=5.0)
        real_name = profile_resp.json().get("name", req.student_id)
    except Exception:
        real_name = req.student_id

    conn = get_db_connection()
    # 检查是否已存在，如果存在只更新密码和名字，保留旧策略
    existing = conn.execute("SELECT * FROM campus_config WHERE student_id = ?", (req.student_id,)).fetchone()
    if existing:
        conn.execute("UPDATE campus_config SET password=?, real_name=?, updated_at=datetime('now', 'localtime') WHERE student_id=?", 
                     (req.password, real_name, req.student_id))
    else:
        conn.execute('''
            INSERT INTO campus_config (student_id, password, real_name, mode, check_interval, answer_threshold, time_slots)
            VALUES (?, ?, ?, 'default', 5, 0, '[]')
        ''', (req.student_id, req.password, real_name))
    conn.commit()
    conn.close()
    
    return {"message": f"🎉 成功登记守护对象: {real_name}"}

# ⚙️ 3. 独立窗口：仅更新特定账号的防风控策略
@router.put("/strategy/{student_id}")
def update_strategy(student_id: str, req: StrategyReq):
    ensure_campus_table()
    conn = get_db_connection()
    conn.execute('''
        UPDATE campus_config 
        SET mode=?, check_interval=?, answer_threshold=?, time_slots=?, updated_at=datetime('now', 'localtime')
        WHERE student_id=?
    ''', (req.mode, req.check_interval, req.answer_threshold, json.dumps(req.time_slots), student_id))
    conn.commit()
    conn.close()
    return {"message": "✅ 专属巡航策略已更新"}

# 🗑️ 4. 新增：彻底删除账号
@router.delete("/account/{student_id}")
def delete_account(student_id: str):
    ensure_campus_table()
    conn = get_db_connection()
    conn.execute("DELETE FROM campus_config WHERE student_id = ?", (student_id,))
    conn.commit()
    conn.close()
    return {"message": "账号及策略已彻底清除"}

# 🚀 5. 指定学号启动监控 (流式接口保持不变)
@router.post("/rollcall/tasks/{student_id}", status_code=201)
def create_rollcall_task(student_id: str):
    ensure_campus_table()
    conn = get_db_connection()
    try:
        account = conn.execute(
            "SELECT real_name FROM campus_config WHERE student_id = ?", (student_id,)
        ).fetchone()
    finally:
        conn.close()
    if not account:
        raise HTTPException(status_code=404, detail="身份资料不存在")
    task_id = create_task(
        "rollcall_monitor",
        f"RollCall 监控：{account['real_name'] or student_id}",
        payload={"student_id": student_id},
        retryable=False,
    )
    return {"task_id": task_id}


@router.get("/stream_sign/{student_id}")
async def stream_sign(student_id: str, task_id: str | None = None):
    ensure_campus_table()
    conn = get_db_connection()
    config = conn.execute("SELECT * FROM campus_config WHERE student_id = ?", (student_id,)).fetchone()
    conn.close()
    if not config:
        raise HTTPException(status_code=404, detail=f"找不到学号 {student_id} 的配置")
    if task_id:
        task = get_task(task_id)
        if (
            not task
            or task["task_type"] != "rollcall_monitor"
            or task["payload"].get("student_id") != student_id
        ):
            raise HTTPException(status_code=404, detail="RollCall 任务不存在")
        if task["status"] != "queued":
            raise HTTPException(status_code=409, detail="RollCall 任务已经启动或结束")
    else:
        task_id = create_task(
            "rollcall_monitor",
            f"RollCall 监控：{config['real_name'] or student_id}",
            payload={"student_id": student_id},
            retryable=False,
        )
    cancel_event = threading.Event()
    register_cancel_callback(task_id, cancel_event.set)

    async def sleep_or_cancel(seconds: int) -> bool:
        remaining = max(0, int(seconds))
        while remaining > 0 and not cancel_event.is_set():
            step = min(1, remaining)
            await asyncio.sleep(step)
            remaining -= step
        return cancel_event.is_set()

    async def generate_log():
        bot = XmuNativeBot(student_id=config["student_id"], password=config["password"], mode=config["mode"],
                           check_interval=config["check_interval"], answer_threshold=config["answer_threshold"], time_slots=json.loads(config["time_slots"]))
        yield f"data: [系统] 🚀 厦大原生监控引擎启动 | 守护对象: {config['real_name']} ({student_id})\n\n"
        yield f"data: [策略] 模式: {bot.mode.upper()} | 扫描间隔: {bot.check_interval}s | 阈值: {bot.answer_threshold}人\n\n"
        
        try:
            yield "data: [认证] ⏳ 正在安全注入缓存登录凭证...\n\n"
            await bot.login()
            yield f"data: [认证] ✅ 欢迎回来，{config['real_name']}同学！导航就绪。\n\n"
            
            url = "https://lnt.xmu.edu.cn/api/radar/rollcalls"
            query_count = 0
            while True:
                if cancel_event.is_set():
                    yield "data: [系统] 监控任务已安全停止。\n\n"
                    return
                if not bot.is_active_time():
                    yield f"data: [休眠] 💤 当前不在课程活跃时段内，引擎默默潜伏中...\n\n"
                    if await sleep_or_cancel(60):
                        continue
                    continue

                query_count += 1
                try:
                    resp = await asyncio.to_thread(bot.session.get, url, timeout=10)
                    resp.raise_for_status()
                    rollcalls = extract_rollcalls(resp.json())
                    if query_count % max(1, (30 // bot.check_interval)) == 0:
                        yield f"data: [监控] 📡 巡航中 | 累计扫描: {query_count}次 | 状态: 正常\n\n"

                    for rc in rollcalls:
                        if rc.get('status') == 'absent':
                            title = rc.get('course_title', '未知课程')
                            rid = rc.get('rollcall_id') or rc.get('rollcallId') or rc.get('id')
                            yield f"data: [警报] 🚨 监测到漏签课程: {title}!\n\n"
                            if bot.answer_threshold > 0:
                                answered_count = await asyncio.to_thread(bot.get_answered_count, rc)
                                if answered_count is None:
                                    yield "data: [阈值] ⚠️ 暂时无法读取已签到人数，本轮不会冒险签到。\n\n"
                                    continue
                                if answered_count < bot.answer_threshold:
                                    yield f"data: [潜伏] 🤫 已签 {answered_count} 人，未达防风控阈值 {bot.answer_threshold} 人，继续潜伏...\n\n"
                                    continue
                                yield f"data: [阈值] ✅ 已签 {answered_count} 人，达到设定阈值 {bot.answer_threshold} 人。\n\n"
                            
                            yield f"data: [行动] ⚡ 发动定点攻破程序...\n\n"
                            if rc.get('is_radar'): success, msg = await asyncio.to_thread(bot.send_radar, rid)
                            elif rc.get('is_number'): success, msg = await asyncio.to_thread(bot.send_code, rid)
                            else: success, msg = False, "未知的签到特征"
                            yield f"data: [战果] {'🏆' if success else '⚠️'} {msg}\n\n"
                except Exception as e:
                     yield f"data: [网络] 📡 信号轻微抖动: {str(e)[:40]}\n\n"
                await sleep_or_cancel(bot.check_interval)
        except Exception as e:
            yield f"data: [致命错误] 引擎因外部摩擦断开: {str(e)}\n\n"

    return StreamingResponse(
        track_async_stream(task_id, generate_log(), failure_tokens=("[致命错误]",)),
        media_type="text/event-stream",
        headers={"X-Task-ID": task_id},
    )
