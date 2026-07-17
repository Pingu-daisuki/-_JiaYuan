# backend/routes/library.py
from difflib import SequenceMatcher
import os
import re
import unicodedata

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.db import get_db_connection
from core.document_parser import MIME_TYPE_BY_DOCUMENT_TYPE, preview_text
from core.paths import DATA_DIR, UPLOAD_DIR
from core.processor import (
    VECTOR_WRITE_LOCK,
    get_vector_collection,
    update_vector_course_metadata,
)

router = APIRouter()
BACKEND_DIR = DATA_DIR
UPLOAD_ROOT = os.path.realpath(UPLOAD_DIR)

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


def _normalized_folder_name(name: str) -> str:
    normalized = (name or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="文件夹名称不能为空")
    if len(normalized) > 100:
        raise HTTPException(status_code=400, detail="文件夹名称不能超过 100 个字符")
    return normalized


def _require_folder(conn, folder_id: int):
    if folder_id == 0:
        return None
    folder = conn.execute(
        "SELECT id, course_name, parent_id FROM courses WHERE id = ?",
        (folder_id,),
    ).fetchone()
    if not folder:
        raise HTTPException(status_code=404, detail=f"目标文件夹不存在: {folder_id}")
    return folder


def _normalize_search_text(value: str):
    """统一大小写、全半角和标点，让中英文文件名都可稳定比较。"""
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return re.sub(r"[^\w]+", "", normalized, flags=re.UNICODE).replace("_", "")


def _character_bigrams(value: str):
    if len(value) < 2:
        return {value} if value else set()
    return {value[index:index + 2] for index in range(len(value) - 1)}


def _fuzzy_match_score(query: str, candidate: str):
    """返回 0~1 的相似度；包含匹配优先，拼错一两个字时回退到序列与二元组相似度。"""
    normalized_query = _normalize_search_text(query)
    normalized_candidate = _normalize_search_text(candidate)
    if not normalized_query or not normalized_candidate:
        return 0.0
    if normalized_query == normalized_candidate:
        return 1.0
    if normalized_query in normalized_candidate:
        coverage = len(normalized_query) / len(normalized_candidate)
        return min(0.99, 0.9 + (0.09 * coverage))
    if len(normalized_query) == 1:
        return 0.0

    sequence_score = SequenceMatcher(None, normalized_query, normalized_candidate).ratio()
    query_bigrams = _character_bigrams(normalized_query)
    candidate_bigrams = _character_bigrams(normalized_candidate)
    bigram_score = (
        (2 * len(query_bigrams & candidate_bigrams))
        / (len(query_bigrams) + len(candidate_bigrams))
        if query_bigrams and candidate_bigrams
        else 0.0
    )
    return max(sequence_score * 0.88, bigram_score * 0.92)


def _name_match_score(query: str, name: str):
    """文件扩展名不应拉低匹配率，同时保留按完整文件名搜索的能力。"""
    stem, _ = os.path.splitext(name or "")
    return max(_fuzzy_match_score(query, name), _fuzzy_match_score(query, stem))


def _course_path(course_id, course_lookup):
    names = []
    visited = set()
    current_id = course_id
    while current_id and current_id not in visited:
        visited.add(current_id)
        course = course_lookup.get(current_id)
        if not course:
            break
        names.append(course["course_name"])
        current_id = course["parent_id"]
    names.reverse()
    return "根目录" if not names else "根目录 / " + " / ".join(names)


def _resolve_library_file(file_path: str):
    resolved = file_path if os.path.isabs(file_path) else os.path.join(BACKEND_DIR, file_path)
    resolved = os.path.realpath(resolved)
    try:
        inside_uploads = os.path.commonpath([UPLOAD_ROOT, resolved]) == UPLOAD_ROOT
    except ValueError:
        inside_uploads = False
    if not inside_uploads:
        raise HTTPException(status_code=403, detail="文件路径不在安全上传目录内")
    return resolved


def _sync_file_course_metadata(file_id: int, course_id: int):
    """文件移动后同步 Chroma 元数据，否则课程范围检索会命中旧目录。"""
    update_vector_course_metadata(file_id, course_id)


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


@router.get("/search")
def search_library(
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(30, ge=1, le=100),
):
    """跨目录模糊搜索课程和文件，支持子串、大小写/全半角和少量错字。"""
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="搜索关键词不能为空")

    conn = get_db_connection()
    try:
        course_rows = conn.execute(
            "SELECT id, course_name, parent_id, created_at FROM courses"
        ).fetchall()
        file_rows = conn.execute(
            """
            SELECT id, course_id, file_name, status, page_count, engine,
                   elapsed_ms, chunk_count, error_message, created_at,
                   document_type, mime_type, source_kind, source_url,
                   unit_type, unit_count
            FROM knowledge_files
            """
        ).fetchall()
    finally:
        conn.close()

    course_lookup = {row["id"]: dict(row) for row in course_rows}
    results = []
    minimum_score = 0.42

    for row in course_rows:
        score = _name_match_score(query, row["course_name"])
        if score < minimum_score:
            continue
        results.append({
            "type": "folder",
            "id": row["id"],
            "name": row["course_name"],
            "course_name": row["course_name"],
            "parent_id": row["parent_id"],
            "path": _course_path(row["id"], course_lookup),
            "score": round(score, 4),
            "created_at": row["created_at"],
        })

    for row in file_rows:
        score = _name_match_score(query, row["file_name"])
        if score < minimum_score:
            continue
        results.append({
            "type": "file",
            "id": row["id"],
            "name": row["file_name"],
            "file_name": row["file_name"],
            "course_id": row["course_id"] or 0,
            "path": _course_path(row["course_id"], course_lookup),
            "score": round(score, 4),
            "status": row["status"],
            "page_count": row["page_count"],
            "engine": row["engine"],
            "elapsed_ms": row["elapsed_ms"],
            "chunk_count": row["chunk_count"],
            "error_message": row["error_message"],
            "document_type": row["document_type"],
            "mime_type": row["mime_type"],
            "source_kind": row["source_kind"],
            "source_url": row["source_url"],
            "unit_type": row["unit_type"],
            "unit_count": row["unit_count"],
            "created_at": row["created_at"],
        })

    results.sort(key=lambda item: (-item["score"], item["type"] != "folder", item["name"]))
    return {"query": query, "total": len(results), "results": results[:limit]}

# 创建新分类文件夹
@router.post("/folders")
def create_folder(req: CourseCreate):
    conn = get_db_connection()
    try:
        parent_id = int(req.parent_id or 0)
        _require_folder(conn, parent_id)
        db_parent = None if parent_id == 0 else parent_id
        cursor = conn.execute(
            "INSERT INTO courses (course_name, parent_id) VALUES (?, ?)",
            (_normalized_folder_name(req.course_name), db_parent),
        )
        conn.commit()
        return {
            "message": "分类创建成功",
            "id": cursor.lastrowid,
            "parent_id": parent_id,
        }
    finally:
        conn.close()

# 重命名文件夹
@router.put("/folders/{folder_id}")
def rename_folder(folder_id: int, req: FolderRenameReq):
    conn = get_db_connection()
    try:
        _require_folder(conn, folder_id)
        conn.execute(
            "UPDATE courses SET course_name = ? WHERE id = ?",
            (_normalized_folder_name(req.new_name), folder_id),
        )
        conn.commit()
        return {"message": "文件夹重命名成功"}
    finally:
        conn.close()

# 安全删除文件夹 (防数据丢失策略)
@router.delete("/folders/{folder_id}")
def delete_folder(folder_id: int):
    conn = get_db_connection()
    affected_file_ids = [
        row["id"]
        for row in conn.execute("SELECT id FROM knowledge_files WHERE course_id = ?", (folder_id,)).fetchall()
    ]
    # 策略 1：文件降级回根目录
    conn.execute("UPDATE knowledge_files SET course_id = NULL WHERE course_id = ?", (folder_id,))
    # 策略 2：子文件夹降级回根目录
    conn.execute("UPDATE courses SET parent_id = NULL WHERE parent_id = ?", (folder_id,))
    # 策略 3：销毁空壳
    conn.execute("DELETE FROM courses WHERE id = ?", (folder_id,))
    conn.commit()
    conn.close()

    try:
        for file_id in affected_file_ids:
            _sync_file_course_metadata(file_id, 0)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"文件夹已删除，但向量课程范围同步失败: {exc}")
    return {"message": "文件夹已删除，内部文件已安全移至根目录"}


# =====================================================================
# 📄 课件管理路由 (移动、删除、查询)
# =====================================================================


@router.get("/documents/{file_id}/content")
def get_document_content(file_id: int):
    conn = get_db_connection()
    try:
        record = conn.execute(
            "SELECT file_name, file_path, document_type, mime_type FROM knowledge_files WHERE id = ?",
            (file_id,),
        ).fetchone()
    finally:
        conn.close()
    if not record:
        raise HTTPException(status_code=404, detail="文件不存在")

    resolved_path = _resolve_library_file(record["file_path"])
    if not os.path.isfile(resolved_path):
        raise HTTPException(status_code=404, detail="原始文件不存在")
    document_type = record["document_type"] or "pdf"
    media_type = record["mime_type"] or MIME_TYPE_BY_DOCUMENT_TYPE.get(document_type, "application/octet-stream")
    return FileResponse(
        resolved_path,
        media_type=media_type,
        filename=record["file_name"],
        content_disposition_type="inline" if document_type == "pdf" else "attachment",
    )


@router.get("/documents/{file_id}/preview")
def get_document_preview(file_id: int):
    conn = get_db_connection()
    try:
        record = conn.execute(
            """
            SELECT file_name, file_path, document_type, source_kind, source_url
            FROM knowledge_files WHERE id = ?
            """,
            (file_id,),
        ).fetchone()
    finally:
        conn.close()
    if not record:
        raise HTTPException(status_code=404, detail="文件不存在")

    document_type = record["document_type"] or "pdf"
    if document_type not in {"markdown", "html"}:
        raise HTTPException(status_code=400, detail="该格式不支持文本预览")
    resolved_path = _resolve_library_file(record["file_path"])
    if not os.path.isfile(resolved_path):
        raise HTTPException(status_code=404, detail="原始文件不存在")
    try:
        text = preview_text(resolved_path, document_type)
    except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=f"预览生成失败: {exc}") from exc
    return {
        "file_name": record["file_name"],
        "document_type": document_type,
        "source_kind": record["source_kind"],
        "source_url": record["source_url"],
        "text": text,
    }

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
    previous_course_id = 0
    vector_synced = False
    try:
        file_record = conn.execute(
            "SELECT id, course_id FROM knowledge_files WHERE id = ?",
            (file_id,),
        ).fetchone()
        if not file_record:
            raise HTTPException(status_code=404, detail="文件不存在")
        _require_folder(conn, req.course_id)
        previous_course_id = file_record["course_id"] or 0
        if previous_course_id == req.course_id:
            return {"message": "文件已在目标文件夹中", "course_id": req.course_id}
        db_course_id = None if req.course_id == 0 else req.course_id
        # 向量加载可能较慢，不在 SQLite 写事务持锁期间执行。
        _sync_file_course_metadata(file_id, req.course_id)
        vector_synced = True
        conn.execute(
            "UPDATE knowledge_files SET course_id = ? WHERE id = ?",
            (db_course_id, file_id),
        )
        conn.commit()
        return {"message": "文件已成功移动", "course_id": req.course_id}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        if vector_synced:
            try:
                _sync_file_course_metadata(file_id, previous_course_id)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"文件移动失败，已回滚: {exc}") from exc
    finally:
        conn.close()

# 终极双重删除 (物理文件 + 向量碎片)
@router.delete("/files/{file_id}")
def delete_file(file_id: int):
    conn = get_db_connection()
    file_record = conn.execute("SELECT file_path FROM knowledge_files WHERE id = ?", (file_id,)).fetchone()
    
    if not file_record:
        conn.close()
        raise HTTPException(status_code=404, detail="文件不存在")

    # 1. 物理斩草
    resolved_path = _resolve_library_file(file_record["file_path"])
    if os.path.exists(resolved_path):
        os.remove(resolved_path)

    # 2. 向量除根
    try:
        with VECTOR_WRITE_LOCK:
            get_vector_collection().delete(where={"file_id": file_id})
    except Exception as e:
        print(f"ChromaDB 删除警告 (可能为空): {e}")

    # 3. 数据库销户
    conn.execute("DELETE FROM knowledge_files WHERE id = ?", (file_id,))
    conn.commit()
    conn.close()
    
    return {"message": "课件及向量记忆已彻底清除"}
