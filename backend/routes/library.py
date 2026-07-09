# backend/routes/library.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
from core.db import get_db_connection
from core.processor import collection  # 导入 ChromaDB collection 用于删除

router = APIRouter()

# =====================================================================
# ✨ 数据模型定义区 (绝对唯一，绝无分身)
# =====================================================================
class CourseCreate(BaseModel):
    course_name: str
    parent_id: int = None # 支持树形父文件夹

class FolderRenameReq(BaseModel):
    new_name: str

class MoveFileReq(BaseModel):
    course_id: int


# =====================================================================
# 📁 文件夹管理路由 (增、删、改、查)
# =====================================================================

# 获取所有分类文件夹
@router.get("/folders")
def get_folders():
    conn = get_db_connection()
    folders = conn.execute("SELECT * FROM courses ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(f) for f in folders]

# 创建新分类文件夹
@router.post("/folders")
def create_folder(req: CourseCreate):
    conn = get_db_connection()
    db_parent = None if req.parent_id == 0 else req.parent_id
    conn.execute("INSERT INTO courses (course_name, parent_id) VALUES (?, ?)", (req.course_name, db_parent))
    conn.commit()
    conn.close()
    return {"message": "分类创建成功"}

# 重命名文件夹
@router.put("/folders/{folder_id}")
def rename_folder(folder_id: int, req: FolderRenameReq):
    conn = get_db_connection()
    conn.execute("UPDATE courses SET course_name = ? WHERE id = ?", (req.new_name, folder_id))
    conn.commit()
    conn.close()
    return {"message": "文件夹重命名成功"}

# 安全删除文件夹 (防数据丢失策略)
@router.delete("/folders/{folder_id}")
def delete_folder(folder_id: int):
    conn = get_db_connection()
    # 策略 1：文件降级回根目录
    conn.execute("UPDATE knowledge_files SET course_id = NULL WHERE course_id = ?", (folder_id,))
    # 策略 2：子文件夹降级回根目录
    conn.execute("UPDATE courses SET parent_id = NULL WHERE parent_id = ?", (folder_id,))
    # 策略 3：销毁空壳
    conn.execute("DELETE FROM courses WHERE id = ?", (folder_id,))
    conn.commit()
    conn.close()
    return {"message": "文件夹已删除，内部文件已安全移至根目录"}


# =====================================================================
# 📄 课件管理路由 (移动、删除、查询)
# =====================================================================

# 获取某分类下的文件（传 0 代表获取未分类文件）
@router.get("/files/{course_id}")
def get_files(course_id: int):
    conn = get_db_connection()
    if course_id == 0:
        files = conn.execute("SELECT * FROM knowledge_files WHERE course_id IS NULL OR course_id = 0 ORDER BY created_at DESC").fetchall()
    else:
        files = conn.execute("SELECT * FROM knowledge_files WHERE course_id = ? ORDER BY created_at DESC", (course_id,)).fetchall()
    conn.close()
    return [dict(f) for f in files]

# 移动文件位置
@router.put("/files/{file_id}/move")
def move_file(file_id: int, req: MoveFileReq):
    conn = get_db_connection()
    db_course_id = None if req.course_id == 0 else req.course_id
    conn.execute("UPDATE knowledge_files SET course_id = ? WHERE id = ?", (db_course_id, file_id))
    conn.commit()
    conn.close()
    return {"message": "文件已成功移动"}

# 终极双重删除 (物理文件 + 向量碎片)
@router.delete("/files/{file_id}")
def delete_file(file_id: int):
    conn = get_db_connection()
    file_record = conn.execute("SELECT file_path FROM knowledge_files WHERE id = ?", (file_id,)).fetchone()
    
    if not file_record:
        conn.close()
        raise HTTPException(status_code=404, detail="文件不存在")

    # 1. 物理斩草
    if os.path.exists(file_record["file_path"]):
        os.remove(file_record["file_path"])

    # 2. 向量除根
    try:
        collection.delete(where={"file_id": file_id})
    except Exception as e:
        print(f"ChromaDB 删除警告 (可能为空): {e}")

    # 3. 数据库销户
    conn.execute("DELETE FROM knowledge_files WHERE id = ?", (file_id,))
    conn.commit()
    conn.close()
    
    return {"message": "课件及向量记忆已彻底清除"}