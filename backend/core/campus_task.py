# backend/core/campus_task.py
import asyncio
import os

async def execute_xmu_sign(student_id: str = "", password: str = ""):
    """
    异步调用本机的 xmu-rollcall-cli 工具进行厦大自动签到
    """
    # 完美复刻你 bat 脚本里的路径
    target_dir = r"C:\Users\rongqueen\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\Scripts"
    
    # 拼接可执行文件路径
    xmu_cmd = os.path.join(target_dir, "xmu")

    try:
        # 使用 asyncio 创建异步子进程，在后台默默跑命令
        process = await asyncio.create_subprocess_shell(
            f'"{xmu_cmd}" start',
            cwd=target_dir,  # 相当于 cd /d ...
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