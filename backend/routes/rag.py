# backend/routes/rag.py
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional
import asyncio
import hashlib
import ipaddress
import os
import re
import socket
import threading
import uuid
from contextlib import closing
from urllib.parse import urljoin, urlparse

import httpx

# 引入你的多引擎动态解析逻辑
from core.processor import (
    DEFAULT_MIN_RELEVANCE,
    delete_vectors_for_file,
    insufficient_evidence_response,
    process_and_vectorize_document_stream,
    retrieve_relevant_context,
    update_vector_course_metadata,
)
from core.db import calculate_file_sha256, get_db_connection, update_file_ingestion
from core.document_parser import (
    DocumentValidationError,
    MAX_UPLOAD_BYTES,
    canonical_mime_type,
    decode_text_bytes,
    document_type_from_filename,
    extract_html_segments_from_text,
    validate_document_file,
)
from core.paths import DATA_DIR, UPLOAD_DIR
from core.tasks import create_task, list_tasks, register_retry_handler, track_stream

router = APIRouter()
UPLOAD_CHUNK_SIZE = 1024 * 1024
MAX_WEB_BYTES = 10 * 1024 * 1024
MAX_WEB_REDIRECTS = 5
WEB_TIMEOUT_SECONDS = 20


def _tracked_ingestion_response(stream, *, file_id: int, title: str, engine: str, retryable: bool = True):
    task_id = create_task(
        "document_ingestion",
        title,
        payload={"file_id": file_id, "engine": engine},
        retryable=retryable,
    )
    return StreamingResponse(
        track_stream(task_id, stream),
        media_type="text/event-stream",
        headers={"X-Task-ID": task_id},
    )


def _assert_course_exists(course_id: int):
    if course_id == 0:
        return
    conn = get_db_connection()
    try:
        exists = conn.execute("SELECT 1 FROM courses WHERE id = ?", (course_id,)).fetchone()
    finally:
        conn.close()
    if not exists:
        raise HTTPException(status_code=404, detail=f"目标文件夹不存在: {course_id}")


def _move_reused_file_to_course(file_record: dict, course_id: int):
    previous_course_id = file_record.get("course_id") or 0
    if previous_course_id == course_id:
        return file_record
    update_vector_course_metadata(file_record["id"], course_id)
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE knowledge_files SET course_id = ?, updated_at = datetime('now', 'localtime') "
            "WHERE id = ?",
            (None if course_id == 0 else course_id, file_record["id"]),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        try:
            update_vector_course_metadata(file_record["id"], previous_course_id)
        except Exception:
            pass
        raise
    finally:
        conn.close()
    file_record["course_id"] = None if course_id == 0 else course_id
    return file_record


def _normalize_engine(engine: str):
    return "pymupdf" if not engine or engine == "pypdf" else engine.lower()


def _safe_document_filename(filename: str):
    safe_name = os.path.basename((filename or "").strip())
    if not safe_name:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    try:
        document_type_from_filename(safe_name)
    except DocumentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return safe_name


def _resolve_file_path(file_path: str):
    if os.path.isabs(file_path):
        return file_path
    return os.path.join(DATA_DIR, file_path)


def _allocate_upload_path(filename: str, file_sha256: str):
    """避免不同内容的同名 PDF 覆盖已有文件。"""
    candidate = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(candidate):
        return candidate, filename

    stem, extension = os.path.splitext(filename)
    collision_name = f"{stem}_{file_sha256[:8]}{extension}"
    candidate = os.path.join(UPLOAD_DIR, collision_name)
    suffix = 2
    while os.path.exists(candidate):
        collision_name = f"{stem}_{file_sha256[:8]}_{suffix}{extension}"
        candidate = os.path.join(UPLOAD_DIR, collision_name)
        suffix += 1
    return candidate, collision_name


def _reuse_ready_file_stream(file_record, requested_course_id: int):
    existing_course_id = file_record["course_id"] if file_record["course_id"] is not None else 0
    unit_labels = {"page": "页", "slide": "张幻灯片", "heading": "个章节", "web_section": "个网页章节"}
    unit_type = file_record["unit_type"] or "page"
    unit_count = file_record["unit_count"] or file_record["page_count"] or 0
    yield f"[状态] ready（复用已有索引）\n"
    yield (
        f"[复用] ✅ 检测到相同 SHA-256，直接复用文件 #{file_record['id']}："
        f"{file_record['file_name']}（{unit_count} {unit_labels.get(unit_type, '个单元')} / "
        f"{file_record['chunk_count']} 块 / {file_record['engine'] or '未知引擎'}）\n"
    )
    if existing_course_id != requested_course_id:
        yield f"[提示] 文件已归档在课程 {existing_course_id}，本次未重复创建或移动记录。\n"
    yield "[系统] ✅ 已复用现有向量索引，无需再次解析。\n"


def _write_staged_upload(upload_file: UploadFile):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    staging_path = os.path.join(UPLOAD_DIR, f".upload_{uuid.uuid4().hex}.tmp")
    digest = hashlib.sha256()
    try:
        total_bytes = 0
        with open(staging_path, "wb") as buffer:
            while chunk := upload_file.file.read(UPLOAD_CHUNK_SIZE):
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="单个文件不能超过 100 MB")
                digest.update(chunk)
                buffer.write(chunk)
        return staging_path, digest.hexdigest()
    except Exception:
        try:
            os.remove(staging_path)
        except FileNotFoundError:
            pass
        raise


def _write_staged_bytes(content: bytes):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    staging_path = os.path.join(UPLOAD_DIR, f".upload_{uuid.uuid4().hex}.tmp")
    with open(staging_path, "wb") as file:
        file.write(content)
    return staging_path, hashlib.sha256(content).hexdigest()


def _register_staged_document(
    staging_path: str,
    file_sha256: str,
    filename: str,
    course_id: int,
    engine: str,
    document_type: str,
    mime_type: str,
    *,
    source_kind: str = "upload",
    source_url: str | None = None,
):
    """把已校验的暂存文件原子登记到状态机；返回复用记录或新记录信息。"""
    conn = get_db_connection()
    conn.execute("BEGIN IMMEDIATE")
    file_path = None
    try:
        ready_query = (
            "SELECT * FROM knowledge_files "
            "WHERE file_sha256 = ? AND status = 'ready' AND source_kind = ?"
        )
        ready_params = [file_sha256, source_kind]
        if source_kind == "url":
            ready_query += " AND source_url = ?"
            ready_params.append(source_url)
        ready_query += " ORDER BY id ASC"
        ready_records = conn.execute(ready_query, ready_params).fetchall()
        for ready_record in ready_records:
            if os.path.isfile(_resolve_file_path(ready_record["file_path"])):
                os.remove(staging_path)
                conn.commit()
                return {"reused": dict(ready_record)}

            conn.execute(
                """
                UPDATE knowledge_files
                SET status = 'failed', chunk_count = 0,
                    error_message = '原始文档缺失，SHA-256 复用校验失败',
                    completed_at = datetime('now', 'localtime'),
                    updated_at = datetime('now', 'localtime')
                WHERE id = ?
                """,
                (ready_record["id"],),
            )
            try:
                delete_vectors_for_file(ready_record["id"])
            except Exception:
                pass

        active_record = conn.execute(
            """
            SELECT id, status FROM knowledge_files
            WHERE file_sha256 = ? AND status IN ('uploaded', 'parsing', 'indexing')
            ORDER BY id DESC LIMIT 1
            """,
            (file_sha256,),
        ).fetchone()
        if active_record:
            conn.commit()
            os.remove(staging_path)
            raise HTTPException(
                status_code=409,
                detail=f"相同文件 #{active_record['id']} 正处于 {active_record['status']} 状态，请勿重复提交",
            )

        file_path, stored_filename = _allocate_upload_path(filename, file_sha256)
        os.replace(staging_path, file_path)
        db_course_id = None if course_id == 0 else course_id
        unit_type = {
            "pdf": "page",
            "pptx": "slide",
            "docx": "heading",
            "markdown": "heading",
            "html": "web_section",
        }[document_type]
        cursor = conn.execute(
            """
            INSERT INTO knowledge_files (
                course_id, file_name, file_path, status, engine, file_sha256,
                document_type, mime_type, source_kind, source_url, unit_type,
                unit_count, page_count, chunk_count, elapsed_ms, error_message, updated_at
            ) VALUES (?, ?, ?, 'uploaded', ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, NULL,
                      datetime('now', 'localtime'))
            """,
            (
                db_course_id, stored_filename, file_path, engine, file_sha256,
                document_type, mime_type, source_kind, source_url, unit_type,
            ),
        )
        conn.commit()
        return {
            "reused": None,
            "file_id": cursor.lastrowid,
            "file_path": file_path,
            "stored_filename": stored_filename,
            "document_type": document_type,
            "mime_type": mime_type,
            "source_kind": source_kind,
            "source_url": source_url,
        }
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        if os.path.isfile(staging_path):
            os.remove(staging_path)
        if file_path and os.path.isfile(file_path):
            os.remove(file_path)
        raise
    finally:
        conn.close()


class UrlImportRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    course_id: int = 0
    engine: str = "pymupdf"


class ImportPreflightRequest(BaseModel):
    file_name: str
    file_size: int = 0
    file_sha256: str | None = None
    course_id: int = 0


@router.post("/preflight")
def import_preflight(req: ImportPreflightRequest):
    """导入前检查重复文件和同名历史版本，并返回透明的粗略耗时估算。"""
    _assert_course_exists(req.course_id)
    extension = os.path.splitext(req.file_name)[1].lower()
    estimated_pages = max(1, round(req.file_size / (350 * 1024))) if extension == ".pdf" else None
    estimated_seconds = max(2, round(req.file_size / (1024 * 1024) * (2.2 if extension == ".pdf" else 0.7)))
    with closing(get_db_connection()) as conn:
        duplicate = None
        if req.file_sha256:
            row = conn.execute(
                "SELECT id,file_name,course_id,status,updated_at FROM knowledge_files "
                "WHERE file_sha256=? ORDER BY status='ready' DESC, updated_at DESC LIMIT 1",
                (req.file_sha256,),
            ).fetchone()
            duplicate = dict(row) if row else None
        versions = [dict(row) for row in conn.execute(
            "SELECT id,file_name,course_id,status,file_sha256,updated_at FROM knowledge_files "
            "WHERE lower(file_name)=lower(?) ORDER BY updated_at DESC LIMIT 8",
            (req.file_name,),
        ).fetchall()]
    return {
        "exact_duplicate": duplicate,
        "same_name_versions": versions,
        "estimate": {
            "pages": estimated_pages,
            "seconds": estimated_seconds,
            "disk_bytes": max(req.file_size, int(req.file_size * 1.35)),
            "is_estimate": True,
        },
    }
async def _assert_public_web_url(url: str):
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="网页地址只允许 HTTP 或 HTTPS")
    if not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="网页地址格式不安全")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise HTTPException(status_code=400, detail="禁止导入本机或内网网页")
    try:
        direct_ip = ipaddress.ip_address(hostname)
        addresses = [direct_ip]
    except ValueError:
        try:
            loop = asyncio.get_running_loop()
            address_info = await loop.getaddrinfo(
                hostname,
                parsed.port or (443 if parsed.scheme.lower() == "https" else 80),
                type=socket.SOCK_STREAM,
            )
            addresses = {ipaddress.ip_address(item[4][0]) for item in address_info}
        except (socket.gaierror, ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail="网页域名无法解析") from exc

    if not addresses or any(not address.is_global for address in addresses):
        raise HTTPException(status_code=400, detail="禁止导入本机、内网、保留地址或链路本地网页")


async def _download_web_page(url: str):
    current_url = url.strip()
    headers = {
        "User-Agent": "XMU-JiaYuan-RAG/1.0 (+local document importer)",
        "Accept": "text/html,application/xhtml+xml",
    }
    timeout = httpx.Timeout(WEB_TIMEOUT_SECONDS, connect=10.0)
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            for redirect_count in range(MAX_WEB_REDIRECTS + 1):
                await _assert_public_web_url(current_url)
                async with client.stream("GET", current_url, headers=headers) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise HTTPException(status_code=502, detail="网页重定向缺少目标地址")
                        if redirect_count >= MAX_WEB_REDIRECTS:
                            raise HTTPException(status_code=400, detail="网页重定向次数过多")
                        current_url = urljoin(current_url, location)
                        continue
                    if response.status_code >= 400:
                        raise HTTPException(
                            status_code=502,
                            detail=f"网页返回 HTTP {response.status_code}",
                        )

                    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    if content_type not in {"text/html", "application/xhtml+xml"}:
                        raise HTTPException(status_code=400, detail="目标地址返回的不是 HTML 网页")

                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > MAX_WEB_BYTES:
                            raise HTTPException(status_code=413, detail="网页正文超过 10 MB")
                    return bytes(content), str(response.url)
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"网页抓取失败: {exc}") from exc

    raise HTTPException(status_code=502, detail="网页抓取未返回内容")


def _web_snapshot_filename(source_url: str, file_sha256: str, page_title: str = ""):
    parsed = urlparse(source_url)
    path_name = os.path.basename(parsed.path.rstrip("/")) or "index"
    stem = page_title.strip() or os.path.splitext(path_name)[0]
    safe_stem = re.sub(r"[^0-9A-Za-z\u3400-\u9fff._-]+", "_", stem).strip("._-") or "page"
    safe_host = re.sub(r"[^0-9A-Za-z.-]+", "_", parsed.hostname or "website")
    base_name = f"{safe_host}_{safe_stem}_{file_sha256[:8]}"[:170].rstrip("._-")
    return f"{base_name}.html"


@router.post("/import-url")
async def import_web_url(req: UrlImportRequest):
    _assert_course_exists(req.course_id)
    raw_html, final_url = await _download_web_page(req.url)
    try:
        decoded_html = decode_text_bytes(raw_html)
        _, safe_html_text, page_title = extract_html_segments_from_text(decoded_html)
        safe_html = safe_html_text.encode("utf-8")
    except (DocumentValidationError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=f"网页正文解析失败: {exc}") from exc

    staging_path, file_sha256 = _write_staged_bytes(safe_html)
    filename = _web_snapshot_filename(final_url, file_sha256, page_title)
    try:
        validation = validate_document_file(staging_path, filename, "text/html")
    except DocumentValidationError as exc:
        if os.path.isfile(staging_path):
            os.remove(staging_path)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    engine = _normalize_engine(req.engine)
    registered = _register_staged_document(
        staging_path,
        file_sha256,
        filename,
        req.course_id,
        engine,
        validation["document_type"],
        validation["mime_type"],
        source_kind="url",
        source_url=final_url,
    )
    if registered["reused"]:
        registered["reused"] = _move_reused_file_to_course(registered["reused"], req.course_id)
        return _tracked_ingestion_response(
            _reuse_ready_file_stream(registered["reused"], req.course_id),
            file_id=registered["reused"]["id"],
            title=f"导入网页：{filename}",
            engine=engine,
            retryable=False,
        )

    return _tracked_ingestion_response(
        process_and_vectorize_document_stream(
            registered["file_path"],
            registered["stored_filename"],
            registered["file_id"],
            req.course_id,
            engine,
            document_type="html",
            mime_type=canonical_mime_type("html"),
            source_kind="url",
            source_url=final_url,
        ),
        file_id=registered["file_id"],
        title=f"导入网页：{filename}",
        engine=engine,
    )

@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    course_id: int = Form(0),
    engine: str = Form("pymupdf")
):
    _assert_course_exists(course_id)
    filename = _safe_document_filename(file.filename)
    engine = _normalize_engine(engine)
    staging_path, file_sha256 = _write_staged_upload(file)
    try:
        validation = validate_document_file(
            staging_path,
            filename,
            file.content_type,
        )
    except DocumentValidationError as exc:
        if os.path.isfile(staging_path):
            os.remove(staging_path)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    registered = _register_staged_document(
        staging_path,
        file_sha256,
        filename,
        course_id,
        engine,
        validation["document_type"],
        validation["mime_type"],
    )
    if registered["reused"]:
        registered["reused"] = _move_reused_file_to_course(registered["reused"], course_id)
        return _tracked_ingestion_response(
            _reuse_ready_file_stream(registered["reused"], course_id),
            file_id=registered["reused"]["id"],
            title=f"导入资料：{filename}",
            engine=engine,
            retryable=False,
        )

    return _tracked_ingestion_response(
        process_and_vectorize_document_stream(
            registered["file_path"],
            registered["stored_filename"],
            registered["file_id"],
            course_id,
            engine,
            document_type=registered["document_type"],
            mime_type=registered["mime_type"],
        ),
        file_id=registered["file_id"],
        title=f"导入资料：{filename}",
        engine=engine,
    )


def _prepare_reindex_stream(file_id: int, engine: str, *, allow_interrupted: bool = False):
    conn = get_db_connection()
    try:
        file_record = conn.execute(
            "SELECT * FROM knowledge_files WHERE id = ?",
            (file_id,),
        ).fetchone()
    finally:
        conn.close()

    if not file_record:
        raise HTTPException(status_code=404, detail="文件不存在")
    resolved_path = _resolve_file_path(file_record["file_path"])
    if not os.path.isfile(resolved_path):
        raise HTTPException(status_code=404, detail="原始文档不存在，无法重建索引")
    if file_record["status"] in {"uploaded", "parsing", "indexing"}:
        if not allow_interrupted:
            raise HTTPException(status_code=409, detail=f"文件正处于 {file_record['status']} 状态")
        delete_vectors_for_file(file_id)
        update_file_ingestion(file_id, "failed", error_message="正在恢复上次中断的入库任务")

    course_id = file_record["course_id"] if file_record["course_id"] is not None else 0
    engine = _normalize_engine(engine)
    try:
        validation = validate_document_file(
            resolved_path,
            file_record["file_name"],
            file_record["mime_type"],
        )
    except DocumentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    file_sha256 = file_record["file_sha256"] or calculate_file_sha256(resolved_path)
    update_file_ingestion(
        file_id,
        "uploaded",
        engine=engine,
        file_sha256=file_sha256,
        elapsed_ms=0,
        page_count=0,
        document_type=validation["document_type"],
        mime_type=validation["mime_type"],
        unit_count=0,
        chunk_count=0,
        error_message=None,
        started_at=None,
        completed_at=None,
    )
    return file_record, engine, process_and_vectorize_document_stream(
            resolved_path,
            file_record["file_name"],
            file_id,
            course_id,
            engine,
            document_type=validation["document_type"],
            mime_type=validation["mime_type"],
            source_kind=file_record["source_kind"] or "upload",
            source_url=file_record["source_url"],
            replace_existing=True,
        )


@router.post("/files/{file_id}/reindex")
async def reindex_document(
    file_id: int,
    engine: str = Form("pymupdf"),
):
    """为已有资料重建统一的位置元数据，而不删除原始文档。"""
    file_record, engine, stream = _prepare_reindex_stream(file_id, engine)
    return _tracked_ingestion_response(
        stream,
        file_id=file_id,
        title=f"重新索引：{file_record['file_name']}",
        engine=engine,
    )


def _retry_ingestion_task(payload: dict) -> str:
    file_id = int(payload["file_id"])
    if any(
        task["status"] in {"queued", "running", "cancelling"}
        and task["task_type"] == "document_ingestion"
        and int(task["payload"].get("file_id", -1)) == file_id
        for task in list_tasks(500)
    ):
        raise RuntimeError("该文件已有入库任务正在运行")
    file_record, engine, stream = _prepare_reindex_stream(
        file_id,
        str(payload.get("engine") or "pymupdf"),
        allow_interrupted=True,
    )
    task_id = create_task(
        "document_ingestion",
        f"恢复索引：{file_record['file_name']}",
        payload={"file_id": file_id, "engine": engine},
        retryable=True,
    )
    tracked_stream = track_stream(task_id, stream)

    def consume():
        for _ in tracked_stream:
            pass

    threading.Thread(target=consume, name=f"ingestion-task-{task_id[:8]}", daemon=True).start()
    return task_id


register_retry_handler("document_ingestion", _retry_ingestion_task)


@router.get("/files/{file_id}/status")
def get_file_ingestion_status(file_id: int):
    conn = get_db_connection()
    try:
        file_record = conn.execute(
            """
            SELECT id, file_name, status, page_count, engine, elapsed_ms,
                   chunk_count, error_message, file_sha256, started_at,
                   completed_at, updated_at, document_type, mime_type,
                   source_kind, source_url, unit_type, unit_count
            FROM knowledge_files WHERE id = ?
            """,
            (file_id,),
        ).fetchone()
    finally:
        conn.close()
    if not file_record:
        raise HTTPException(status_code=404, detail="文件不存在")
    return dict(file_record)

class QueryRequest(BaseModel):
    query: str
    # None/省略 = 全库；0 = 仅根目录；正数 = 指定课程（含其子目录）。
    course_id: Optional[int] = None
    # 可选的精确文件范围；与 course_id 同时传入时取交集。
    file_ids: list[int] = Field(default_factory=list)
    n_results: int = Field(default=3, ge=1, le=3)
    min_relevance: float = Field(default=DEFAULT_MIN_RELEVANCE, ge=0.0, le=1.0)


def _expand_course_scope(course_id: int):
    """将树形课程目录展开为自身及所有子目录，供 Chroma $in 过滤。"""
    if course_id == 0:
        return [0]

    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            WITH RECURSIVE course_tree(id) AS (
                SELECT id FROM courses WHERE id = ?
                UNION ALL
                SELECT courses.id FROM courses JOIN course_tree
                ON courses.parent_id = course_tree.id
            )
            SELECT id FROM course_tree
            """,
            (course_id,),
        ).fetchall()
        return [row["id"] for row in rows]
    finally:
        conn.close()

@router.post("/retrieve")
async def retrieve_context(req: QueryRequest):
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=422, detail="检索问题不能为空")

    course_ids = None
    if req.course_id is not None:
        course_ids = _expand_course_scope(req.course_id)
        if not course_ids:
            return insufficient_evidence_response({"candidate_count": 0})

    return retrieve_relevant_context(
        query,
        n_results=req.n_results,
        course_ids=course_ids,
        file_ids=req.file_ids,
        min_relevance=req.min_relevance,
    )
