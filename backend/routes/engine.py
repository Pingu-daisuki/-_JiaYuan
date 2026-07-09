# backend/routes/engine.py
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from core.engine_init import is_initialized, init_engine_stream, get_engine_device

router = APIRouter()


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
    return StreamingResponse(init_engine_stream(engine, use_gpu), media_type="text/event-stream")