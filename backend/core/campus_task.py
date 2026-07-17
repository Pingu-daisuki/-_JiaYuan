# backend/core/campus_task.py
import asyncio
import os
import shutil

async def execute_xmu_sign(student_id: str = "", password: str = ""):
    """
    异步调用本机的 xmu-rollcall-cli 工具进行厦大自动签到
    """
    try:
        xmu_cmd = shutil.which("xmu") or shutil.which("xmu.exe")
        if not xmu_cmd:
            return {"status": "fatal", "log": "未在 PATH 中找到 xmu 命令"}
        target_dir = os.path.dirname(xmu_cmd)
        process = await asyncio.create_subprocess_exec(
            xmu_cmd,
            "start",
            cwd=target_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # 等待脚本执行完毕，并抓取控制台的全部输出
        stdout, stderr = await process.communicate()
        
        # Windows 控制台默认是 gbk 编码，做安全解码防止乱码
        log_output = stdout.decode('gbk', errors='ignore') if stdout else ""
        err_output = stderr.decode('gbk', errors='ignore') if stderr else ""
        
        full_log = log_output + "\n" + err_output

        # 判断执行是否成功
        if process.returncode == 0:
            return {"status": "success", "log": full_log.strip()}
        else:
            return {"status": "error", "log": full_log.strip()}
            
    except Exception as e:
        return {"status": "fatal", "log": str(e)}
