# backend/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# ✨ 核心校验 1：确保把 campus 模块正确引入
from routes import chat, rag, library, campus, oj, engine
from routes import deadlines
from core.paths import ensure_runtime_dirs
from core.processor import backfill_ready_file_metrics, recover_interrupted_ingestions


ensure_runtime_dirs()

app = FastAPI(title="厦大_JiaYuan RAG Backend", version="1.0.0")


@app.get("/api/health", tags=["System"])
def health_check():
    return {"status": "ok", "app": "jiayuan", "version": app.version}


@app.on_event("startup")
def recover_interrupted_file_ingestions():
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

app.add_middleware(
    CORSMiddleware,
    # Electron loadFile() 的 Origin 是 null；后端仅监听 127.0.0.1。
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "null"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(deadlines.router, prefix="/api")
app.include_router(chat.router, prefix="/api/chat", tags=["Model Gateway"])
app.include_router(rag.router, prefix="/api/rag", tags=["RAG Engine"])
app.include_router(engine.router, prefix="/api/engine", tags=["PDF Engine Initialization"])
app.include_router(library.router, prefix="/api/library", tags=["Library Management"])

# ✨ 核心校验 2：必须使用 prefix="/api/campus"，与前端的 /api/campus/trigger_sign 严丝合缝
app.include_router(campus.router, prefix="/api/campus", tags=["Campus Tools"])
app.include_router(oj.router, prefix="/api/oj", tags=["OJ Engine"])

if __name__ == "__main__":
    import uvicorn
    reload_enabled = os.getenv("JIAYUAN_RELOAD", "0") == "1" and not getattr(sys, "frozen", False)
    port = int(os.getenv("JIAYUAN_PORT", "8000"))
    uvicorn.run("main:app", host="127.0.0.1", port=port, reload=reload_enabled)
