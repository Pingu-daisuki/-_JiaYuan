# backend/routes/engine.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import threading

from core.engine_init import (
    cancel_engine_initialization,
    get_engine_device,
    init_engine_stream,
    is_initialized,
)
from core.tasks import (
    create_task,
    register_cancel_callback,
    register_retry_handler,
    track_stream,
)

router = APIRouter()


def _new_engine_task(engine: str, use_gpu: bool):
    task_id = create_task(
        "engine_init",
        f"初始化 {engine.upper()}（{'GPU' if use_gpu else 'CPU'}）",
        payload={"engine": engine, "use_gpu": use_gpu},
        retryable=True,
    )
    register_cancel_callback(task_id, lambda: cancel_engine_initialization(engine))
    stream = track_stream(task_id, init_engine_stream(engine, use_gpu))
    return task_id, stream


def _retry_engine_task(payload: dict) -> str:
    task_id, stream = _new_engine_task(str(payload["engine"]), bool(payload.get("use_gpu")))

    def consume():
        for _ in stream:
            pass

    threading.Thread(target=consume, name=f"engine-task-{task_id[:8]}", daemon=True).start()
    return task_id


register_retry_handler("engine_init", _retry_engine_task)


@router.get("/status/{engine}")
def get_engine_status(engine: str):
    """前端在用户点击引擎选项时先调用这个，判断要不要弹出下载提示，
    并把已初始化的运行设备（cpu/cuda）一起带回去，方便前端展示"""
    initialized = is_initialized(engine)
    return {
        "engine": engine,
        "initialized": initialized,
        "device": get_engine_device(engine) if initialized else None,
    }


@router.get("/init/{engine}")
def init_engine(engine: str, use_gpu: bool = False):
    """流式触发指定引擎的首次模型下载/初始化。
    use_gpu=true 时会安装 CUDA 版 torch/torchvision 并把设备偏好写入配置。"""
    if engine not in {"marker", "mineru"}:
        raise HTTPException(status_code=400, detail=f"不支持的引擎: {engine}")
    task_id, stream = _new_engine_task(engine, use_gpu)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"X-Task-ID": task_id},
    )


@router.post("/cancel/{engine}")
def cancel_engine_init(engine: str):
    """取消当前初始化，并由后端回收 pip/模型下载/探针的完整进程树。"""
    if engine not in {"marker", "mineru"}:
        raise HTTPException(status_code=400, detail=f"不支持的引擎: {engine}")
    cancelling = cancel_engine_initialization(engine)
    return {
        "engine": engine,
        "cancelling": cancelling,
        "message": "已请求取消初始化" if cancelling else "当前没有正在运行的初始化任务",
    }
