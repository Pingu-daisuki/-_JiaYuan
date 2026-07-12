# backend/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# ✨ 核心校验 1：确保把 campus 模块正确引入
from routes import chat, rag, library, campus, oj
from backend.routes import deadlines
app.include_router(deadlines.router, prefix="/api")

os.makedirs("uploads", exist_ok=True)
os.makedirs("vector_db", exist_ok=True)

app = FastAPI(title="厦大_JiaYuan RAG Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/api/uploads", StaticFiles(directory="uploads"), name="uploads")

app.include_router(chat.router, prefix="/api/chat", tags=["Model Gateway"])
app.include_router(rag.router, prefix="/api/rag", tags=["RAG Engine"])
app.include_router(library.router, prefix="/api/library", tags=["Library Management"])

# ✨ 核心校验 2：必须使用 prefix="/api/campus"，与前端的 /api/campus/trigger_sign 严丝合缝
app.include_router(campus.router, prefix="/api/campus", tags=["Campus Tools"])
app.include_router(oj.router, prefix="/api/oj", tags=["OJ Engine"])

if __name__ == "__main__":
    import uvicorn
    # 确保端口为 8000
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)