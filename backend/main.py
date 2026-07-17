# backend/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import sys
import threading

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from core.paths import ensure_runtime_dirs
from core.maintenance import apply_pending_restore

ensure_runtime_dirs()
apply_pending_restore()

# 路由和数据库模块必须在待恢复数据应用完成后加载。
from routes import chat, rag, library, campus, oj, engine, tasks, system, workspace
from routes import deadlines
from core.processor import backfill_ready_file_metrics, recover_interrupted_ingestions
from core.tasks import recover_interrupted_tasks

app = FastAPI(title="厦大_JiaYuan RAG Backend", version="1.0.0")


@app.get("/api/health", tags=["System"])
def health_check():
    return {"status": "ok", "app": "jiayuan", "version": app.version}


@app.on_event("startup")
def recover_interrupted_file_ingestions():
    recover_interrupted_tasks()
    # 历史补偿可能首次加载 Chroma/向量模型；不能让它阻塞健康接口和桌面窗口。
    def maintain_vector_state():
        try:
            recovered_file_ids = recover_interrupted_ingestions()
            if recovered_file_ids:
                print(f"[RAG 恢复] 已将异常中断的文件标记为 failed: {recovered_file_ids}")
        except Exception as exc:
            print(f"[RAG 恢复警告] 中断任务补偿失败: {exc}")
        try:
            backfilled_file_ids = backfill_ready_file_metrics()
            if backfilled_file_ids:
                print(f"[RAG 迁移] 已补齐旧 ready 文件指标: {backfilled_file_ids}")
        except Exception as exc:
            print(f"[RAG 迁移警告] 旧文件指标补齐失败: {exc}")

    threading.Thread(
        target=maintain_vector_state,
        name="jiayuan-vector-maintenance",
        daemon=True,
    ).start()

app.add_middleware(
    CORSMiddleware,
    # Electron loadFile() 的 Origin 是 null；后端仅监听 127.0.0.1。
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "null"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Task-ID"],
)

app.include_router(deadlines.router, prefix="/api")
app.include_router(chat.router, prefix="/api/chat", tags=["Model Gateway"])
app.include_router(rag.router, prefix="/api/rag", tags=["RAG Engine"])
app.include_router(engine.router, prefix="/api/engine", tags=["PDF Engine Initialization"])
app.include_router(library.router, prefix="/api/library", tags=["Library Management"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["Background Tasks"])
app.include_router(system.router, prefix="/api/system", tags=["Data Maintenance"])
app.include_router(workspace.router, prefix="/api/workspace", tags=["Learning Workspace"])

# ✨ 核心校验 2：必须使用 prefix="/api/campus"，与前端的 /api/campus/trigger_sign 严丝合缝
app.include_router(campus.router, prefix="/api/campus", tags=["Campus Tools"])
app.include_router(oj.router, prefix="/api/oj", tags=["OJ Engine"])

if __name__ == "__main__":
    import uvicorn
    reload_enabled = os.getenv("JIAYUAN_RELOAD", "0") == "1" and not getattr(sys, "frozen", False)
    port = int(os.getenv("JIAYUAN_PORT", "8000"))
    uvicorn.run("main:app", host="127.0.0.1", port=port, reload=reload_enabled)
