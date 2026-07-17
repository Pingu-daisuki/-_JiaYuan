# backend/core/campus_core.py
import math
import time
import uuid
import asyncio
import requests # <--- 新增
import re
from datetime import datetime
from xmulogin import xmulogin

BASE_URL = "https://lnt.xmu.edu.cn"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://ids.xmu.edu.cn/authserver/login",
}

ANSWER_COUNT_KEYS = {
    "answered_count", "answer_count", "attendee_count", "attend_count",
    "present_count", "signed_count", "signed_in_count",
    "answered_num", "attend_num", "present_num",
    "answeredCount", "answerCount", "attendeeCount", "attendCount",
    "presentCount", "signedCount", "signedInCount",
    "answeredNum", "attendNum", "presentNum",
}
ANSWER_LIST_KEYS = {
    "answered_students", "answered_users", "attendees",
    "present_students", "signed_students", "signed_users",
    "answeredStudents", "answeredUsers", "presentStudents", "signedStudents", "signedUsers",
}
STUDENT_RECORD_LIST_KEYS = {"student_rollcalls", "studentRollcalls", "rollcall_students"}
ANSWERED_STATUSES = {
    "answered", "answer", "present", "attended", "attend", "signed", "success",
    "completed", "complete", "submitted", "normal", "yes", "1",
}
UNANSWERED_STATUSES = {
    "absent", "unanswered", "not_answered", "pending", "waiting", "no", "0",
}


def _nonnegative_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    if isinstance(value, str):
        normalized = value.strip()
        if normalized.isdigit():
            return int(normalized)
    return None


def _count_answered_student_records(records):
    if not isinstance(records, list):
        return None
    answered = 0
    saw_attendance_evidence = False
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in ("is_answered", "answered", "is_present", "present", "signed", "submitted"):
            if key in record and isinstance(record[key], bool):
                saw_attendance_evidence = True
                answered += int(record[key])
                break
        else:
            status = record.get("status") or record.get("attendance_status") or record.get("answer_status")
            if status is not None:
                normalized_status = str(status).strip().lower()
                if normalized_status in ANSWERED_STATUSES:
                    saw_attendance_evidence = True
                    answered += 1
                elif normalized_status in UNANSWERED_STATUSES:
                    saw_attendance_evidence = True
            elif any(record.get(key) for key in ("answered_at", "submitted_at", "attendance_time")):
                saw_attendance_evidence = True
                answered += 1
    return answered if saw_attendance_evidence else None


def extract_answered_count(payload):
    """兼容畅课不同版本的标量、嵌套对象和学生签到列表。"""
    candidates = []
    visited = set()

    def visit(value, path=()):
        if isinstance(value, (dict, list)):
            identity = id(value)
            if identity in visited:
                return
            visited.add(identity)

        if isinstance(value, dict):
            for key in ANSWER_COUNT_KEYS:
                if key in value:
                    count = _nonnegative_int(value[key])
                    if count is not None:
                        candidates.append(count)
            for key in ANSWER_LIST_KEYS:
                records = value.get(key)
                if isinstance(records, list):
                    candidates.append(len(records))
            for key in STUDENT_RECORD_LIST_KEYS:
                count = _count_answered_student_records(value.get(key))
                if count is not None:
                    candidates.append(count)
            for key, nested in value.items():
                normalized_key = re.sub(r"[^a-z0-9]+", "_", str(key)).strip("_").lower()
                normalized_path = path + (normalized_key,)
                path_label = "_".join(normalized_path)
                if (
                    any(token in path_label for token in ("answer", "attend", "present", "sign"))
                    and any(token in normalized_key for token in ("count", "num", "total"))
                ):
                    count = _nonnegative_int(nested)
                    if count is not None:
                        candidates.append(count)
                if (
                    isinstance(nested, list)
                    and any(token in normalized_key for token in ("answer", "attendee", "present", "signed"))
                    and any(token in normalized_key for token in ("student", "user", "member", "list"))
                ):
                    candidates.append(len(nested))
                visit(nested, normalized_path)
        elif isinstance(value, list):
            count = _count_answered_student_records(value)
            if count is not None:
                candidates.append(count)
            for nested in value:
                visit(nested, path)

    visit(payload)
    return max(candidates) if candidates else None


def _find_rollcall_id(payload):
    if not isinstance(payload, dict):
        return None
    for key in ("rollcall_id", "rollcallId"):
        if payload.get(key) is not None:
            return payload[key]
    nested_rollcall = payload.get("rollcall")
    if isinstance(nested_rollcall, dict):
        return nested_rollcall.get("id") or nested_rollcall.get("rollcall_id")
    return payload.get("id")


def extract_rollcalls(payload):
    """兼容 rollcalls 位于顶层或 data/result 等包装对象中的响应。"""
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("rollcalls", "radar_rollcalls", "radarRollcalls"):
        if isinstance(payload.get(key), list):
            return payload[key]
    for value in payload.values():
        nested = extract_rollcalls(value)
        if nested:
            return nested
    return []

class XmuNativeBot:
    def __init__(self, student_id, password, mode="default", check_interval=5, answer_threshold=0, time_slots=None):
        self.student_id = student_id
        self.password = password
        self.session = None
        
        # --- 策略配置 ---
        self.mode = mode                     # "default" 或 "custom"
        self.check_interval = max(1, int(check_interval or 5)) # 轮询间隔(秒)
        self.answer_threshold = max(0, int(answer_threshold or 0)) # 已签到多少人再签到
        self.time_slots = time_slots or []   # 格式: [{"start": "08:00", "end": "11:50"}]

    async def login(self):
        """调用 xmulogin 统一身份认证，并接管 Session"""
        self.session = await asyncio.to_thread(xmulogin, type=3, username=self.student_id, password=self.password)
        if not self.session:
            raise Exception("统一身份认证失败，请检查账号密码。")
        self.session.headers.update(HEADERS)
        return True

    def get_answered_count(self, rollcall):
        """优先读取雷达列表；列表未携带人数时再查询签到详情。"""
        count = extract_answered_count(rollcall)
        if count is not None:
            return count
        rollcall_id = _find_rollcall_id(rollcall)
        if rollcall_id is None or self.session is None:
            return None
        detail_url = f"{BASE_URL}/api/rollcall/{rollcall_id}/student_rollcalls"
        response = self.session.get(detail_url, timeout=10)
        response.raise_for_status()
        return extract_answered_count(response.json())

    def is_active_time(self):
        """根据当前模式和时间段判断是否处于监控激活期"""
        if self.mode == "default" or not self.time_slots:
            return True  # 默认模式 24 小时全天候
        
        now_time = datetime.now().strftime("%H:%M")
        for slot in self.time_slots:
            if slot["start"] <= now_time <= slot["end"]:
                return True
        return False
  # =========================================================================
    # 新增模块：死线看板数据抓取
    # =========================================================================
    def fetch_deadlines(self):
        """
        利用已认证的 Session 抓取畅课待办死线 (Deadlines)，包含详尽的报错容错逻辑
        """
        if not self.session:
            return False, "[Error] 尚未登录，无有效 Session" #[cite: 4]
            
        # 畅课待办接口 URL
        todo_url = f"{BASE_URL}/api/todos" #[cite: 4]
        
        try:
            # 1. 发起请求，设置超时时间防止网络拥塞导致后续看板任务卡死
            # 注意：如果顶层没有 import requests，这里可能会报 requests 相关的错，建议在文件头部加上 import requests
            response = self.session.get(todo_url, timeout=10) #[cite: 4]
            
            # 抛出非 200 状态码异常
            response.raise_for_status()
            
            # 2. JSON 解析容错
            try:
                todos_data = response.json()
            except ValueError as json_err:
                return False, f"[JSON_Parse_Error] 接口返回的数据非标准 JSON。状态码: {response.status_code}, 详细错误: {str(json_err)}"

            deadlines = []
            
            # 3. 结构安全性检查：现在明确知道列表的键名叫 'todo_list'
            items = todos_data.get('todo_list')
            if items is None:
                return False, f"[Data_Structure_Error] JSON 中未找到 'todo_list' 字段，当前返回的键名有: {list(todos_data.keys())}"
            if not isinstance(items, list):
                return False, f"[Data_Structure_Error] 'todo_list' 字段不是列表，当前类型为 {type(items).__name__}。"

            # 💡 打印第一条数据到终端，以防内部字段名对不上
            if len(items) > 0:
                print("\n" + "="*50)
                print("🎯 [DEBUG] 第一条作业/待办的真实结构：")
                print(items[0])
                print("="*50 + "\n")

            # 4. 单条数据解析容错 (加入常见的命名兼容)
            for item in items:
                try:
                    # 尝试多种可能的任务类型标识
                    task_type = item.get('type') or item.get('task_type') or 'assignment'
                    
                    deadlines.append({
                        # 兼容下划线和驼峰命名
                        'course_name': item.get('course_name') or item.get('courseName') or '未知课程',
                        'title': item.get('title') or item.get('name') or '未命名任务',
                        'deadline': item.get('end_time') or item.get('endTime') or item.get('deadline'),
                        'is_submitted': item.get('is_submitted') or item.get('isSubmitted') or False,
                        'type': task_type,
                        'source': 'TronClass'
                    })
                except Exception as item_err:
                    print(f"[Warning] 解析单个待办任务时发生异常: {str(item_err)}，异常数据体: {item}")
                    continue
                    
            return True, deadlines
         # 4. 单条数据解析容错
            for item in items:
                try:
                    if item.get('type') in ['assignment', 'quiz']:
                        deadlines.append({
                            'course_name': item.get('course_name', '未知课程'),
                            'title': item.get('title', '未命名任务'),
                            'deadline': item.get('end_time'),
                            'is_submitted': item.get('is_submitted', False),
                            'source': 'TronClass'
                        })
                except Exception as item_err:
                    # 单条任务解析异常不应该阻塞整个看板更新，记录日志后跳过当前条目
                    print(f"[Warning] 解析单个待办任务时发生异常: {str(item_err)}，异常数据体: {item}")
                    continue
                    
            return True, deadlines
            
        # 5. 网络请求维度的专属异常捕获
        except requests.exceptions.Timeout:
            return False, "[Network_Error] 请求畅课 API 超时，请检查服务器网络状况。"
        except requests.exceptions.ConnectionError:
            return False, "[Network_Error] 连接畅课服务器失败，目标域名可能无法解析或被拒绝。"
        except requests.exceptions.HTTPError as http_err:
            return False, f"[HTTP_Error] 接口请求遭到拒绝或资源不存在: {str(http_err)}"
        except Exception as e:
            # 兜底捕获
            return False, f"[Fatal_Error] 发生未知异常: {type(e).__name__} - {str(e)}"

    # =========================================================================
    # 完美复刻原源码：数字签到递归提取逻辑
    # =========================================================================
    def _find_number_code(self, data, depth=0, max_depth=10):
        if depth > max_depth: return None
        if isinstance(data, dict):
            num_code = data.get("number_code")
            if num_code is not None: return str(num_code)
            for v in data.values():
                res = self._find_number_code(v, depth + 1, max_depth)
                if res: return res
        elif isinstance(data, list):
            for item in data:
                res = self._find_number_code(item, depth + 1, max_depth)
                if res: return res
        return None

    def send_code(self, rollcall_id):
        code_url = f"{BASE_URL}/api/rollcall/{rollcall_id}/student_rollcalls"
        answer_url = f"{BASE_URL}/api/rollcall/{rollcall_id}/answer_number_rollcall"
        
        resp = self.session.get(code_url)
        if resp.status_code != 200: return False, "获取签到数据失败"
        
        num_code = self._find_number_code(resp.json())
        if not num_code: return False, "未能在响应中提取到 number_code"
        
        payload = {"deviceId": str(uuid.uuid4()), "numberCode": num_code}
        res = self.session.put(answer_url, json=payload)
        
        if res.status_code == 200: return True, f"数字码 [{num_code}] 提交成功"
        return False, f"提交数字码失败，状态码: {res.status_code}"

    # =========================================================================
    # 完美复刻原源码：雷达签到圆交点求解逻辑
    # =========================================================================
    def send_radar(self, rollcall_id):
        url = f"{BASE_URL}/api/rollcall/{rollcall_id}/answer"
        lat_1, lon_1 = 24.3, 118.0
        lat_2, lon_2 = 24.6, 118.2

        def build_payload(lat, lon):
            return {"accuracy": 35, "altitude": 0, "altitudeAccuracy": None, "deviceId": str(uuid.uuid4()), "heading": None, "latitude": lat, "longitude": lon, "speed": None}

        # 试探点 1
        res_1 = self.session.put(url, json=build_payload(lat_1, lon_1))
        if res_1.status_code == 200: return True, "雷达定位(点1)直接命中"
        dist_1 = res_1.json().get("distance")

        # 试探点 2
        res_2 = self.session.put(url, json=build_payload(lat_2, lon_2))
        if res_2.status_code == 200: return True, "雷达定位(点2)直接命中"
        dist_2 = res_2.json().get("distance")

        # 地理坐标与直角坐标互转
        def latlon_to_xy(lat, lon, lat0, lon0):
            R = 6371000
            x = math.radians(lon - lon0) * R * math.cos(math.radians(lat0))
            y = math.radians(lat - lat0) * R
            return x, y

        def xy_to_latlon(x, y, lat0, lon0):
            R = 6371000
            lat = lat0 + math.degrees(y / R)
            lon = lon0 + math.degrees(x / (R * math.cos(math.radians(lat0))))
            return lat, lon

        # 计算两圆交点
        def solve_two_points(lat1, lon1, lat2, lon2, d1, d2):
            lat0, lon0 = (lat1 + lat2) / 2, (lon1 + lon2) / 2
            x1, y1 = latlon_to_xy(lat1, lon1, lat0, lon0)
            x2, y2 = latlon_to_xy(lat2, lon2, lat0, lon0)
            
            D = math.hypot(x2 - x1, y2 - y1)
            if D > d1 + d2 or D < abs(d1 - d2): return None
            
            a = (d1**2 - d2**2 + D**2) / (2 * D)
            h = math.sqrt(abs(d1**2 - a**2))
            
            xm, ym = x1 + a * (x2 - x1) / D, y1 + a * (y2 - y1) / D
            rx, ry = -(y2 - y1) * (h / D), (x2 - x1) * (h / D)
            
            p1 = xy_to_latlon(xm + rx, ym + ry, lat0, lon0)
            p2 = xy_to_latlon(xm - rx, ym - ry, lat0, lon0)
            return p1, p2

        resolutions = solve_two_points(lat_1, lon_1, lat_2, lon_2, dist_1, dist_2)
        if not resolutions: return False, "雷达交点无解"

        for idx, (sol_lat, sol_lon) in enumerate(resolutions):
            res = self.session.put(url, json=build_payload(sol_lat, sol_lon))
            if res.status_code == 200:
                return True, f"雷达方程求解成功 (交点{idx+1})"
        
        return False, "尝试所有雷达解均失败"
