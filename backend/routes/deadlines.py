# backend/routes/deadlines.py
import asyncio
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

# 导入你的核心业务逻辑和数据库操作
from core.campus_core import XmuNativeBot
from core import db

# 创建路由器实例，并在 main.py 中挂载
router = APIRouter(
    prefix="/deadlines",
    tags=["Deadline Board"]
)

@router.get("/{student_id}")
async def get_student_deadlines(
    student_id: str, 
    sync: bool = Query(False, description="是否强制从畅课同步最新数据")
):
    """
    获取指定学号的作业和考试死线。
    - sync=False (默认): 直接从 campus_assistant.db 快速读取缓存数据
    - sync=True: 触发后台 XmuNativeBot 模拟登录并拉取最新数据，更新入库后返回
    """
    
    # 1. 默认快速读取数据库缓存（加快前端渲染）
    if not sync:
        try:
            # 假设 db.py 中有一个 get_deadlines 函数
            cached_data = db.get_deadlines(student_id) 
            return {
                "status": "success",
                "message": "读取缓存成功",
                "data": cached_data
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"数据库读取失败: {str(e)}")

    # 2. 强制同步逻辑：需要从数据库取出账号密码，调用核心抓取
    # 假设 db.py 中有一个获取账号信息的函数
    account_info = db.get_account_info(student_id)
    if not account_info:
        raise HTTPException(status_code=404, detail="未在数据库中找到该学号的认证信息")
    
    password = account_info.get("password")
    if not password:
        raise HTTPException(status_code=400, detail="该账号密码信息不全，无法完成统一身份认证")

    # 3. 初始化并调用你写的原生签到 Bot
    bot = XmuNativeBot(student_id=student_id, password=password)
    
    try:
        # 调用核心登录机制（复用你的 xmulogin 统一身份认证）
        login_success = await bot.login()
        if not login_success:
            raise HTTPException(status_code=401, detail="统一身份认证失败，请检查账号密码")

        # 4. 执行抓取 (因为 fetch_deadlines 里用的是 requests 同步请求，最好用 to_thread 防止阻塞异步进程)
        success, result = await asyncio.to_thread(bot.fetch_deadlines)

        if not success:
            # 如果抓取失败，result 里面是错误信息文本
            raise HTTPException(status_code=502, detail=result)

        # 5. 抓取成功，将获取到的 List 存入数据库
        # 假设 db.py 有一个 save_deadlines 函数，会清空旧数据或做 UPSERT 更新
        db.save_deadlines(student_id, result)

        return {
            "status": "success",
            "message": "畅课数据同步成功",
            "data": result
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"抓取流程发生未知致命错误: {str(e)}")