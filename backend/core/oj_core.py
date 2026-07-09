# backend/core/oj_core.py
import json
import time
import requests
import urllib3
import re

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
BASE_URL = "https://xmuoj.com"

def build_prompt(problem, language):
    title = problem.get("title", "")
    description = problem.get("description", "")
    input_desc = problem.get("input_description", "")
    output_desc = problem.get("output_description", "")
    hint = problem.get("hint", "")
    samples = problem.get("samples", [])

    sample_text = ""
    for i, s in enumerate(samples):
        sample_text += f"\n样例输入{i+1}:\n{s.get('input','')}\n样例输出{i+1}:\n{s.get('output','')}\n"

    lang_hint = {
        "C": "请使用标准 C 语言 (C99) 编写。",
        "C++": "请使用 C++ (支持 STL) 编写。",
        "Java": "请使用 Java 编写，主类名必须是 Main。",
        "Python3": "请使用 Python3 编写。",
    }.get(language, "")

    prompt = f"""请解决以下算法题。{lang_hint}
只输出完整可编译/运行的代码，不要任何解释文字，不要 Markdown 代码块标记（不要```）。

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
    return prompt

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
                "Referer": BASE_URL + "/",
            })

    def login(self):
        self.session.get(BASE_URL + "/")
        self._refresh_csrf_header()
        resp = self.session.post(BASE_URL + "/api/login", json={
            "username": self.username,
            "password": self.password,
        })
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            raise RuntimeError(f"登录失败: {data}")
        self._refresh_csrf_header()
        return True

    def enter_contest(self, contest_id, contest_password):
        info = self.session.get(BASE_URL + "/api/contest", params={"id": contest_id}).json()
        if info.get("error"):
            raise RuntimeError(f"获取实验信息失败: {info}")
        
        if info["data"].get("contest_type") == "Password Protected":
            if not contest_password:
                raise RuntimeError("该实验需要密码，但未输入")
            resp = self.session.post(BASE_URL + "/api/contest/password", json={
                "contest_id": int(contest_id),
                "password": contest_password,
            })
            resp.raise_for_status()
            if resp.json().get("error"):
                raise RuntimeError("实验密码验证失败")
        return info['data']['title']

    def get_problem_list(self, contest_id):
        resp = self.session.get(BASE_URL + "/api/contest/problem", params={"contest_id": contest_id})
        resp.raise_for_status()
        raw = resp.json()
        data = raw.get("data", [])
        if isinstance(data, dict):
            data = data.get("results", [])
        return data

    def submit(self, problem_id, contest_id, code, language="C++"):
        self._refresh_csrf_header()
        resp = self.session.post(BASE_URL + "/api/submission", json={
            "problem_id": problem_id,
            "contest_id": int(contest_id),
            "language": language,
            "code": code,
        })
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            msg = str(data.get("data", ""))
            m = re.search(r"(\d+)\s*seconds?", msg)
            if m: return {"status": "cooldown", "wait": int(m.group(1)) + 1}
            raise RuntimeError(f"提交失败: {data}")
        return {"status": "success", "id": data["data"]["submission_id"]}

    def get_result_once(self, submission_id):
        resp = self.session.get(BASE_URL + "/api/submission", params={"id": submission_id})
        resp.raise_for_status()
        return resp.json().get("data", {})