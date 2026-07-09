from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import asyncio
import re
import requests
from core.db import get_db_connection
from core.oj_core import OJClient, build_prompt

router = APIRouter()

# 判题结果映射
STATUS_NAME = {
    0: "Accepted ✅", -1: "Wrong Answer ❌", -2: "Compile Error ⚠️",
    1: "CPU Time Limit Exceeded ❌", 2: "Real Time Limit Exceeded ❌",
    3: "Memory Limit Exceeded ❌", 4: "Runtime Error ❌", 5: "System Error ⚠️",
    8: "Partial Accepted 🟡"
}

@router.get("/stream_solve")
async def stream_solve(contest_id: str, contest_password: str = ""):
    conn = get_db_connection()
    config = conn.execute("SELECT * FROM oj_config LIMIT 1").fetchone()
    conn.close()

    async def generate_log():
        if not config:
            yield "data: [错误] ❌ 未检测到配置，请先保存信息。\n\n"
            return
        
        client = OJClient(config["username"], config["password"])
        yield "data: [系统] 🚀 自动刷题引擎启动...\n\n"

        try:
            await asyncio.to_thread(client.login)
            yield f"data: [认证] ✅ 登录成功: {config['username']}\n\n"
            
            title = await asyncio.to_thread(client.enter_contest, contest_id, contest_password)
            yield f"data: [实验] ✅ 成功进入: {title}\n\n"

            problems = await asyncio.to_thread(client.get_problem_list, contest_id)
            
            for p in problems:
                if p.get("my_status") == 0: continue

                pid = p.get("id") or p.get("_id")
                yield f"data: [处理] ⚔️ 开始攻破: [{pid}] {p.get('title')}\n\n"
                
                # 动态生成 prompt
                prompt = build_prompt(p, config["language"])

                # 安全提取代码的核心函数
                def _call_llm_safe():
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config['llm_model']}:generateContent"
                    resp = requests.post(url, headers={"Content-Type": "application/json", "x-goog-api-key": config["llm_api_key"]},
                                         json={"contents": [{"role": "user", "parts": [{"text": prompt}]}]}, verify=False)
                    resp.raise_for_status()
                    raw_text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                    
                    # 动态生成 fence，彻底避免渲染污染
                    fence = chr(96) * 3 
                    # 使用正则提取代码块
                    pattern = fence + r'[a-zA-Z]*\s*\n(.*?)(?:' + fence + r'|$)'
                    match = re.search(pattern, raw_text, re.DOTALL)
                    return match.group(1).strip() if match else raw_text.strip()

                code = await asyncio.to_thread(_call_llm_safe)
                
                # 提交逻辑
                res = await asyncio.to_thread(client.submit, pid, contest_id, code, config["language"])
                yield f"data: [提交] 📤 已提交，等待判题...\n\n"
                
                await asyncio.sleep(5) # 基础防风控

            yield "data: [系统] 🎉 任务完成。\n\n"
        except Exception as e:
            yield f"data: [错误] ❌ 执行异常: {str(e)}\n\n"

    return StreamingResponse(generate_log(), media_type="text/event-stream")