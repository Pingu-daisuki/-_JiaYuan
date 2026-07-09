# backend/routes/rag.py
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import shutil
import os

# 引入你的多引擎动态解析逻辑
from core.processor import process_and_vectorize_pdf_stream, retrieve_relevant_context
from core.db import get_db_connection

router = APIRouter()
UPLOAD_DIR = "uploads"

@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    course_id: int = Form(0),
    engine: str = Form("pypdf") # ✨ 新增：接收前端送来的引擎参数，默认 pypdf
):
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="目前仅支持 PDF")
        
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # 先存入 SQLite，获得唯一的 file_id
    conn = get_db_connection()
    cursor = conn.cursor()
    db_course_id = None if course_id == 0 else course_id
    cursor.execute(
        "INSERT INTO knowledge_files (course_id, file_name, file_path) VALUES (?, ?, ?)",
        (db_course_id, file.filename, file_path)
    )
    file_id = cursor.lastrowid
    conn.commit()
    conn.close()
        
    # ✨ 核心改动：把 engine 引擎参数也一起丢给大脑去动态调度！
    return StreamingResponse(
        process_and_vectorize_pdf_stream(file_path, file.filename, file_id, course_id, engine), 
        media_type="text/event-stream"
    )

class QueryRequest(BaseModel):
    query: str

@router.post("/retrieve")
async def retrieve_context(req: QueryRequest):
    context = retrieve_relevant_context(req.query)
    return {"context": context}