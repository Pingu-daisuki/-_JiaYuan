# backend/core/campus_core.py
import math
import time
import uuid
import asyncio
from datetime import datetime
from xmulogin import xmulogin

BASE_URL = "https://lnt.xmu.edu.cn"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://ids.xmu.edu.cn/authserver/login",
}

class XmuNativeBot:
    def __init__(self, student_id, password, mode="default", check_interval=5, answer_threshold=0, time_slots=None):
        self.student_id = student_id
        self.password = password
        self.session = None
        
        # --- 策略配置 ---
        self.mode = mode                     # "default" 或 "custom"
        self.check_interval = check_interval # 轮询间隔(秒)
        self.answer_threshold = answer_threshold # 已签到多少人再签到
        self.time_slots = time_slots or []   # 格式: [{"start": "08:00", "end": "11:50"}]

    async def login(self):
        """调用 xmulogin 统一身份认证，并接管 Session"""
        self.session = await asyncio.to_thread(xmulogin, type=3, username=self.student_id, password=self.password)
        if not self.session:
            raise Exception("统一身份认证失败，请检查账号密码。")
        self.session.headers.update(HEADERS)
        return True

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