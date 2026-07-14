import asyncio
import json
import os
import traceback

import urllib3
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from core.db import get_db_connection
from core.oj_core import OJClient, STATUS_NAME, build_prompt, call_llm
from core.paths import DATA_DIR

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

router = APIRouter()

CONFIG_PATH = os.path.join(DATA_DIR, "config.json")


def sse(message):
    return f"data: {message}\n\n"


@router.get("/stream_solve")
async def stream_solve(
    contest_id: str,
    student_id: str,
    model: str,
    contest_password: str = "",
    interval: int = 5,
    api_key: str = "",
    base_url: str = "",
    model_id: str = "",
    model_type: str = "cloud",
):
    async def generate_log():
        try:
            with get_db_connection() as conn:
                user = conn.execute(
                    "SELECT * FROM campus_config WHERE student_id = ?", # 👈 将 accounts 换成 campus_config
                    (student_id,),
                ).fetchone()

            if not user:
                yield sse("[错误] 未在数据库中找到该身份档案，请确认是否已保存账号。")
                return

            llm_api_key = api_key
            language = "C++"
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as file:
                    local_config = json.load(file)
                llm_api_key = llm_api_key or local_config.get("llm_api_key", "")
                language = local_config.get("language", "C++")

            if not llm_api_key and not base_url:
                yield sse("[错误] 未找到大模型 API Key，请先在设置页保存模型配置。")
                return

            llm_model = model_id or model

            client = OJClient(user["student_id"], user["password"])

            yield sse("[系统] 正在验证统一身份认证...")
            await asyncio.to_thread(client.login)
            yield sse("[认证] 身份认证登录成功。")

            yield sse(f"[系统] 正在检索实验编号 [{contest_id}]...")
            contest_title = await asyncio.to_thread(client.enter_contest, contest_id, contest_password)
            yield sse(f"[实验] 已进入实验：{contest_title or contest_id}")

            problems = await asyncio.to_thread(client.get_problem_list, contest_id)
            yield sse(f"[系统] 成功加载题目列表，共 {len(problems)} 道题。")

            for problem in problems:
                problem_id = problem.get("id") or problem.get("_id")
                title = problem.get("title", "未知题目")
                if not problem_id:
                    yield sse(f"[跳过] 题目 {title} 缺少 problem_id。")
                    continue

                if problem.get("my_status") == 0:
                    yield sse(f"[系统] [{problem_id}] {title} 已通过，自动跳过。")
                    continue

                yield sse(f"[处理] 正在攻克：[{problem_id}] {title} ...")

                languages = problem.get("languages") or [language]
                use_lang = language if language in languages else languages[0]
                prompt = build_prompt(problem, use_lang)

                yield sse(f"[API] 正在请求大模型 API (Model: {model}) 生成 {use_lang} 代码...")
                code = await asyncio.to_thread(
                    call_llm,
                    prompt,
                    llm_api_key,
                    llm_model,
                    base_url,
                    model_type,
                )

                yield sse("[提交] 方案已生成，正在向 OJ 提交代码...")
                submit_result = await asyncio.to_thread(
                    client.submit,
                    problem_id,
                    contest_id,
                    code,
                    use_lang,
                )

                if submit_result.get("status") == "cooldown":
                    wait_seconds = submit_result.get("wait", interval)
                    yield sse(f"[冷却] OJ 限制提交频率，等待 {wait_seconds} 秒后继续。")
                    await asyncio.sleep(wait_seconds)
                    submit_result = await asyncio.to_thread(
                        client.submit,
                        problem_id,
                        contest_id,
                        code,
                        use_lang,
                    )

                submission_id = submit_result["id"]
                yield sse(f"[提交] 提交成功 (ID: {submission_id})，正在轮询评测结果...")

                result_data = await asyncio.to_thread(client.poll_result, submission_id)
                result_code = result_data.get("result", "unknown")
                status_text = STATUS_NAME.get(result_code, f"未知状态码({result_code})")
                yield sse(f"[结果] 做题结果: {status_text}")

                if result_code == -2:
                    err = result_data.get("statistic_info", {}).get("err_info", "")
                    yield sse(f"[错误] 编译报错: {err[:150]}...")

                yield sse(f"[休眠] 防风控冷却中，等待 {interval} 秒后继续...")
                await asyncio.sleep(interval)

            yield sse("[系统] 托管结束，所有未通过题目已处理完毕。")

        except Exception as exc:
            error_details = traceback.format_exc()
            yield sse("[错误] 自动化流程遇到异常，已中断。")
            yield sse(f"[错误] 报错详情: {exc}")
            for line in error_details.splitlines()[-5:]:
                if line.strip():
                    yield sse(f"[错误] {line}")

    return StreamingResponse(generate_log(), media_type="text/event-stream")
