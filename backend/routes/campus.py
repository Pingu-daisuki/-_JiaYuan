# backend/routes/campus.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import asyncio
import json
from datetime import datetime
from core.db import get_db_connection
from core.campus_core import XmuNativeBot

router = APIRouter()

def ensure_campus_table():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(campus_config)")
    columns = [col[1] for col in cursor.fetchall()]
    if columns and "real_name" not in columns:
        conn.execute("DROP TABLE campus_config")
        
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
    conn.commit()
    conn.close()

# 📝 请求模型拆分
class AccountReq(BaseModel):
    student_id: str
    password: str

class StrategyReq(BaseModel):
    mode: str = "default"
    check_interval: int = 5
    answer_threshold: int = 0
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
@router.get("/stream_sign/{student_id}")
async def stream_sign(student_id: str):
    ensure_campus_table()
    conn = get_db_connection()
    config = conn.execute("SELECT * FROM campus_config WHERE student_id = ?", (student_id,)).fetchone()
    conn.close()

    async def generate_log():
        if not config:
            yield f"data: [错误] ❌ 找不到学号 {student_id} 的配置。\n\n"
            return
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
                if not bot.is_active_time():
                    yield f"data: [休眠] 💤 当前不在课程活跃时段内，引擎默默潜伏中...\n\n"
                    await asyncio.sleep(60)
                    continue

                query_count += 1
                try:
                    resp = await asyncio.to_thread(bot.session.get, url)
                    rollcalls = resp.json().get('rollcalls', [])
                    if query_count % max(1, (30 // bot.check_interval)) == 0:
                        yield f"data: [监控] 📡 巡航中 | 累计扫描: {query_count}次 | 状态: 正常\n\n"

                    for rc in rollcalls:
                        if rc.get('status') == 'absent':
                            title = rc.get('course_title', '未知课程')
                            rid = rc.get('rollcall_id')
                            yield f"data: [警报] 🚨 监测到漏签课程: {title}!\n\n"
                            answered_count = rc.get('answered_count', rc.get('attendee_count', 0))
                            if bot.answer_threshold > 0 and answered_count < bot.answer_threshold:
                                yield f"data: [潜伏] 🤫 已签 {answered_count} 人，未达防风控阀值 {bot.answer_threshold} 人，继续潜伏...\n\n"
                                continue
                            
                            yield f"data: [行动] ⚡ 发动定点攻破程序...\n\n"
                            if rc.get('is_radar'): success, msg = await asyncio.to_thread(bot.send_radar, rid)
                            elif rc.get('is_number'): success, msg = await asyncio.to_thread(bot.send_code, rid)
                            else: success, msg = False, "未知的签到特征"
                            yield f"data: [战果] {'🏆' if success else '⚠️'} {msg}\n\n"
                except Exception as e:
                     yield f"data: [网络] 📡 信号轻微抖动: {str(e)[:40]}\n\n"
                await asyncio.sleep(bot.check_interval)
        except Exception as e:
            yield f"data: [致命错误] 引擎因外部摩擦断开: {str(e)}\n\n"

    return StreamingResponse(generate_log(), media_type="text/event-stream")