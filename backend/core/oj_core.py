# backend/core/oj_core.py
import re
import time

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://xmuoj.com"

STATUS_NAME = {
    0: "Accepted",
    -1: "Wrong Answer",
    -2: "Compile Error",
    1: "CPU Time Limit Exceeded",
    2: "Real Time Limit Exceeded",
    3: "Memory Limit Exceeded",
    4: "Runtime Error",
    5: "System Error",
    6: "Pending",
    7: "Judging",
    8: "Partial Accepted",
    "timeout": "轮询超时，评测可能仍在进行",
}


def build_prompt(problem, language):
    title = problem.get("title", "")
    description = problem.get("description", "")
    input_desc = problem.get("input_description", "")
    output_desc = problem.get("output_description", "")
    hint = problem.get("hint", "")
    samples = problem.get("samples", [])

    sample_text = ""
    for i, sample in enumerate(samples, start=1):
        if not isinstance(sample, dict):
            continue
        sample_text += (
            f"\n样例输入{i}:\n{sample.get('input', '')}"
            f"\n样例输出{i}:\n{sample.get('output', '')}\n"
        )

    lang_hint = {
        "C": "请使用标准 C 语言（C99）编写。",
        "C++": "请使用 C++ 编写，可以使用 STL。",
        "Java": "请使用 Java 编写，主类名必须是 Main。",
        "Python3": "请使用 Python3 编写。",
    }.get(language, "")

    return f"""请解决下面的算法题。{lang_hint}
只输出完整、可编译或可运行的代码，不要解释，不要使用 Markdown 代码块。

题目标题: {title}

题目描述:
{description}

输入格式:
{input_desc}

输出格式:
{output_desc}

提示:
{hint}

样例:
{sample_text}
"""


def _strip_markdown_fence(text):
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def _call_gemini(prompt, api_key, model, base_url=None):
    api_root = (base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    if api_root.endswith("/models"):
        api_root = api_root[:-7]
    url = f"{api_root}/models/{model}:generateContent"
    resp = requests.post(
        url,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        json={"contents": [{"role": "user", "parts": [{"text": prompt}]}]},
        verify=False,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()

    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"解析 Gemini 响应失败: {exc}, 原始返回: {str(data)[:200]}")


def _call_openai_compatible(prompt, api_key, model, base_url):
    api_root = base_url.rstrip("/")
    url = api_root if api_root.endswith("/chat/completions") else f"{api_root}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    resp = requests.post(
        url,
        headers=headers,
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": "You are an online judge coding assistant. Return code only."},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        },
        verify=False,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()

    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"解析 OpenAI-compatible 响应失败: {exc}, 原始返回: {str(data)[:200]}")


def call_llm(prompt, api_key, model="gemini-1.5-flash", base_url="", model_type="cloud"):
    if not base_url:
        text = _call_gemini(prompt, api_key, model)
    elif "generativelanguage.googleapis.com" in base_url or model.startswith("gemini-"):
        text = _call_gemini(prompt, api_key, model, base_url)
    else:
        text = _call_openai_compatible(prompt, api_key, model, base_url)

    return _strip_markdown_fence(text)


class OJClient:
    def __init__(self, username, password):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; auto-solver-script/1.0)",
        })
        self.session.verify = False
        self.username = username
        self.password = password

    def _refresh_csrf_header(self):
        token = self.session.cookies.get("csrftoken")
        if token:
            self.session.headers.update({
                "X-Csrftoken": token,
                "X-CSRFToken": token,
                "Referer": BASE_URL + "/",
            })

    def login(self):
        self.session.get(BASE_URL + "/", timeout=30)
        self._refresh_csrf_header()
        resp = self.session.post(
            BASE_URL + "/api/login",
            json={"username": self.username, "password": self.password},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            raise RuntimeError(f"登录失败: {data}")
        self._refresh_csrf_header()
        return True

    def enter_contest(self, contest_id, contest_password):
        resp = self.session.get(BASE_URL + "/api/contest", params={"id": contest_id}, timeout=30)
        resp.raise_for_status()
        info = resp.json()
        if info.get("error"):
            raise RuntimeError(f"获取实验信息失败: {info}")

        contest = info.get("data") or {}
        if contest.get("contest_type") == "Password Protected":
            if not contest_password:
                raise RuntimeError("该实验需要密码，但未输入")
            self._refresh_csrf_header()
            pass_resp = self.session.post(
                BASE_URL + "/api/contest/password",
                json={"contest_id": int(contest_id), "password": contest_password},
                timeout=30,
            )
            pass_resp.raise_for_status()
            pass_data = pass_resp.json()
            if pass_data.get("error"):
                raise RuntimeError(f"实验密码验证失败: {pass_data}")

        return contest.get("title", "")

    def get_problem_list(self, contest_id):
        resp = self.session.get(
            BASE_URL + "/api/contest/problem",
            params={"contest_id": contest_id},
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()
        if raw.get("error"):
            raise RuntimeError(f"获取题目列表失败: {raw}")

        data = raw.get("data", [])
        if isinstance(data, dict):
            data = data.get("results", [])
        return data or []

    def submit(self, problem_id, contest_id, code, language="C++"):
        self._refresh_csrf_header()
        resp = self.session.post(
            BASE_URL + "/api/submission",
            json={
                "problem_id": problem_id,
                "contest_id": int(contest_id),
                "language": language,
                "code": code,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            msg = str(data.get("data", ""))
            match = re.search(r"(\d+)\s*seconds?", msg)
            if match:
                return {"status": "cooldown", "wait": int(match.group(1)) + 1}
            raise RuntimeError(f"提交失败: {data}")

        submission_id = (data.get("data") or {}).get("submission_id")
        if not submission_id:
            raise RuntimeError(f"提交成功但未返回 submission_id: {data}")
        return {"status": "success", "id": submission_id}

    def get_result_once(self, submission_id):
        resp = self.session.get(BASE_URL + "/api/submission", params={"id": submission_id}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            raise RuntimeError(f"获取提交结果失败: {data}")
        return data.get("data", {})

    def poll_result(self, submission_id, timeout=60, interval=2):
        elapsed = 0
        while elapsed < timeout:
            data = self.get_result_once(submission_id)
            result = data.get("result")
            if result not in (6, 7, "Pending", "Judging"):
                return data
            time.sleep(interval)
            elapsed += interval
        return {"result": "timeout"}
