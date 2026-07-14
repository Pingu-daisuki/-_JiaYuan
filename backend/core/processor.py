# backend/core/processor.py
import os
import uuid
import json
import re
import math
import unicodedata
import fitz # PyMuPDF
import subprocess
import shutil
import tempfile
import queue
import threading
import time
from datetime import datetime
from collections import Counter
from chromadb.utils import embedding_functions
import chromadb
from core.db import get_db_connection, update_file_ingestion
from core.document_parser import (
    document_type_from_filename,
    extract_markdown_segments_from_text,
    extract_native_document,
)
from core.engine_init import (
    _build_subprocess_env,
    _find_cli,
    build_engine_command,
    get_engine_device,
    is_initialized,
    MARKER_PAGE_SEPARATOR,
    read_markdown_output,
)
from core.paths import DATA_DIR, VECTOR_DB_DIR, resource_path

# 初始化向量数据库路径与客户端
CHROMA_DATA_DIR = VECTOR_DB_DIR
BACKEND_DIR = DATA_DIR
TESSERACT_DIR = resource_path("source", "tesseract")
TESSERACT_EXE = os.path.join(TESSERACT_DIR, "tesseract.exe")
TESSDATA_DIR = os.path.join(TESSERACT_DIR, "tessdata")
OCR_LANGUAGE = "chi_sim"
OCR_DPI = 150
ENGINE_TIMEOUT_SECONDS = {
    # 实测扫描页完整视觉后处理约需 1.5 分钟，6 页文献在 GPU 上可能接近 10 分钟。
    # 心跳会持续反馈进度；15 分钟仍未结束才判为异常并回收子进程。
    "marker": 900,
    "mineru": 900,
}
ENGINE_HEARTBEAT_SECONDS = 5
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
RETRIEVAL_CANDIDATE_COUNT = 10
RETRIEVAL_MMR_POOL_SIZE = 8
RETRIEVAL_FINAL_COUNT = 3
DEFAULT_MIN_RELEVANCE = float(os.getenv("RAG_MIN_RELEVANCE", "0.55"))
MMR_LAMBDA = 0.72
EMBEDDING_MODEL_NAME = os.getenv("RAG_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
EMBEDDING_LOCAL_FILES_ONLY = os.getenv("RAG_EMBEDDING_LOCAL_FILES_ONLY", "0") == "1"
RERANKER_MODEL_NAME = os.getenv("RAG_RERANKER_MODEL", "BAAI/bge-reranker-base")
RERANKER_DEVICE = os.getenv("RAG_RERANKER_DEVICE", "cpu")
# 默认允许首次查询自动下载；设 RAG_RERANKER_LOCAL_FILES_ONLY=1 可强制纯离线，
# 模型缺失时会安全降级到 hybrid-fallback。
RERANKER_LOCAL_FILES_ONLY = os.getenv("RAG_RERANKER_LOCAL_FILES_ONLY", "0") == "1"

ENGINE_ALIASES = {"pypdf": "pymupdf"}  # 兼容旧版前端和 localStorage 中的历史值
ENGINE_LABELS = {
    "pymupdf": "PyMuPDF",
    "marker": "Marker",
    "mineru": "MinerU",
}
NATIVE_ENGINE_BY_DOCUMENT_TYPE = {
    "docx": "python-docx",
    "pptx": "python-pptx",
    "markdown": "markdown",
    "html": "html",
}
DOCUMENT_TYPE_LABELS = {
    "pdf": "PDF",
    "docx": "DOCX",
    "pptx": "PPTX",
    "markdown": "Markdown",
    "html": "HTML",
}

chroma_client = chromadb.PersistentClient(path=CHROMA_DATA_DIR)
VECTOR_WRITE_LOCK = threading.Lock()
RERANKER_LOCK = threading.Lock()
_RERANKER_MODEL = None
_RERANKER_LOAD_ATTEMPTED = False
_RERANKER_LOAD_ERROR = None

embedding_options = {"local_files_only": True} if EMBEDDING_LOCAL_FILES_ONLY else {}
bge_embeddings = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=EMBEDDING_MODEL_NAME,
    **embedding_options,
)
collection = chroma_client.get_or_create_collection(
    name="xmu_course_materials_v2",
    embedding_function=bge_embeddings
)


def _page_record(page: int, text: str) -> dict:
    """统一页级文本结构；page 使用 1-based，0 表示解析器未提供可靠页码。"""
    return {"page": page, "text": (text or "").strip()}


def _document_segment(
    text: str,
    *,
    section: str = "正文",
    location_type: str = "heading",
    location_index: int = 0,
):
    return {
        "text": (text or "").strip(),
        "section": (section or "正文").strip()[:180],
        "location_type": location_type,
        "location_index": max(0, int(location_index or 0)),
        "page": max(0, int(location_index or 0)) if location_type == "page" else 0,
    }


def _local_timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _pdf_page_count(pdf_path: str) -> int:
    with fitz.open(pdf_path) as document:
        return len(document)

def _find_tesseract() -> str:
    """优先使用项目自带的 Tesseract，未打包时再查找系统命令。"""
    if os.path.isfile(TESSERACT_EXE):
        return TESSERACT_EXE
    cli_path = _find_cli("tesseract")
    if cli_path:
        return cli_path
    raise FileNotFoundError("未找到 Tesseract OCR 程序")


def _ocr_page_with_tesseract(page, image_path: str, tesseract_path: str) -> str:
    """将单个 PDF 页面渲染为图片，再交给 Tesseract 识别。"""
    zoom = OCR_DPI / 72
    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(zoom, zoom),
        colorspace=fitz.csRGB,
        alpha=False,
    )
    pixmap.save(image_path)

    cmd = [tesseract_path, image_path, "stdout", "-l", OCR_LANGUAGE, "--psm", "3"]
    if os.path.isdir(TESSDATA_DIR):
        cmd.extend(["--tessdata-dir", TESSDATA_DIR])

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    if result.returncode != 0:
        error_detail = result.stderr.strip()[-500:]
        raise RuntimeError(f"Tesseract OCR 失败: {error_detail or '未知错误'}")
    return result.stdout


def extract_pages_with_pymupdf(pdf_path: str):
    """按页提取文字层，并仅对无文字层页面调用 Tesseract。"""
    doc = fitz.open(pdf_path)
    page_texts = []
    ocr_page_count = 0
    total_page_count = len(doc)

    try:
        with tempfile.TemporaryDirectory(prefix="jiayuan_ocr_") as temp_dir:
            tesseract_path = None
            for page_index, page in enumerate(doc):
                page_text = page.get_text("text")
                if not page_text or not page_text.strip():
                    if tesseract_path is None:
                        tesseract_path = _find_tesseract()
                    image_path = os.path.join(temp_dir, f"page_{page_index + 1}.png")
                    page_text = _ocr_page_with_tesseract(page, image_path, tesseract_path)
                    ocr_page_count += 1

                if page_text and page_text.strip():
                    page_texts.append(_page_record(page_index + 1, page_text))
    finally:
        doc.close()

    return page_texts, ocr_page_count, total_page_count


def extract_with_pymupdf(pdf_path: str):
    """兼容旧调用：返回全文、OCR 页数和总页数。"""
    page_texts, ocr_page_count, total_page_count = extract_pages_with_pymupdf(pdf_path)
    return "\n\n".join(page["text"] for page in page_texts), ocr_page_count, total_page_count


_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_NUMBERED_HEADING_RE = re.compile(
    r"^\s*(?:第[一二三四五六七八九十百千万0-9]+[章节部分]|(?:[一二三四五六七八九十]+|\d+(?:\.\d+){0,3})[、．.])\s*(.{1,160})$"
)


def _section_title(line: str):
    """从 Markdown 或常见中文编号中提取章节标题。"""
    clean_line = line.strip()
    markdown_match = _MARKDOWN_HEADING_RE.match(clean_line)
    if markdown_match:
        return markdown_match.group(1).strip()

    numbered_match = _NUMBERED_HEADING_RE.match(clean_line)
    if numbered_match:
        return clean_line
    return None


def _split_page_sections(text: str):
    """在单页内按标题分段；不允许任何片段跨越页边界。"""
    current_section = "正文"
    current_lines = []
    sections = []

    def flush_section():
        section_text = "\n".join(current_lines).strip()
        if section_text:
            sections.append((current_section[:180], section_text))

    for line in text.splitlines():
        title = _section_title(line)
        if title:
            flush_section()
            current_lines = []
            current_section = title
        current_lines.append(line)

    flush_section()
    return sections or [("正文", text.strip())]


def build_document_chunks(segments, *, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    """按页、幻灯片或章节边界切片，不允许片段跨越来源定位单元。"""
    chunks = []
    next_chunk_index = 0
    step = max(1, chunk_size - overlap)

    for segment in segments:
        page = int(segment.get("page") or 0)
        location_type = str(segment.get("location_type") or ("page" if page else "heading"))
        location_index = int(segment.get("location_index") or page or 0)
        section_hint = str(segment.get("section") or "正文")
        text = str(segment.get("text") or "").strip()
        if not text:
            continue

        for section, section_text in _split_page_sections(text):
            effective_section = section_hint if section == "正文" and section_hint else section
            start = 0
            while start < len(section_text):
                chunk_text = section_text[start:start + chunk_size].strip()
                if chunk_text:
                    chunks.append(
                        {
                            "text": chunk_text,
                            "page": page,
                            "section": effective_section,
                            "location_type": location_type,
                            "location_index": location_index,
                            "chunk_index": next_chunk_index,
                        }
                    )
                    next_chunk_index += 1
                start += step

    return chunks


def build_page_chunks(page_texts, *, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    """兼容旧调用：把 PDF 页记录转换为通用定位单元。"""
    segments = [
        _document_segment(
            item.get("text"),
            location_type="page",
            location_index=int(item.get("page") or 0),
        )
        for item in page_texts
    ]
    return build_document_chunks(segments, chunk_size=chunk_size, overlap=overlap)


def _read_marker_page_texts(markdown: str):
    """解析 Marker paginate_output 写入的 {0}<separator> 页边界。"""
    marker_pattern = re.compile(r"\{(?P<page_id>\d+)\}" + re.escape(MARKER_PAGE_SEPARATOR))
    matches = list(marker_pattern.finditer(markdown))
    if not matches:
        return []

    pages = []
    for index, match in enumerate(matches):
        content_end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        page_text = markdown[match.end():content_end].strip()
        if page_text:
            pages.append(_page_record(int(match.group("page_id")) + 1, page_text))
    return pages


def _mineru_value_to_text(value):
    """将 MinerU content_list 中的文本、列表或嵌套内容转成可检索文本。"""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(part for item in value if (part := _mineru_value_to_text(item)))
    if isinstance(value, dict):
        preferred_keys = (
            "text", "content", "text_level", "list_items", "table_body",
            "table_caption", "image_caption", "image_footnote", "equation_latex",
        )
        return "\n".join(
            part
            for key in preferred_keys
            if key in value and (part := _mineru_value_to_text(value[key]))
        )
    return ""


def _read_mineru_page_texts(output_dir: str):
    """读取 MinerU content_list 的 page_idx；该文件是其可靠的页级输出。"""
    content_lists = []
    for root, _, files in os.walk(output_dir):
        for filename in files:
            lower_name = filename.lower()
            if lower_name.endswith("_content_list.json") or lower_name.endswith("_content_list_v2.json"):
                content_lists.append(os.path.join(root, filename))

    for path in sorted(content_lists):
        try:
            with open(path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue

        if isinstance(data, dict):
            data = data.get("content_list") or data.get("contents") or []
        if not isinstance(data, list):
            continue

        by_page = {}
        for item in data:
            if not isinstance(item, dict) or not isinstance(item.get("page_idx"), int):
                continue
            text = _mineru_value_to_text(item)
            if text:
                by_page.setdefault(item["page_idx"], []).append(text)

        if by_page:
            return [
                _page_record(page_index + 1, "\n".join(parts))
                for page_index, parts in sorted(by_page.items())
            ]
    return []


def _read_external_page_texts(engine: str, output_dir: str, markdown: str):
    if engine == "marker":
        page_texts = _read_marker_page_texts(markdown)
        if page_texts:
            return page_texts
    elif engine == "mineru":
        page_texts = _read_mineru_page_texts(output_dir)
        if page_texts:
            return page_texts

    # 老版本输出或异常格式没有可靠的页边界时，宁可标记为未知页码，
    # 也不按字符比例猜测引用页。
    return [_page_record(0, markdown)] if markdown.strip() else []


def _external_output_segments(document_type: str, page_texts, markdown: str):
    """把 Marker/MinerU 输出映射为统一的页/幻灯片/章节定位。"""
    if document_type == "pdf":
        return [
            _document_segment(
                item.get("text"),
                location_type="page",
                location_index=int(item.get("page") or 0),
            )
            for item in page_texts
            if str(item.get("text") or "").strip()
        ]

    if document_type == "pptx" and any(int(item.get("page") or 0) > 0 for item in page_texts):
        return [
            _document_segment(
                item.get("text"),
                section=f"幻灯片 {int(item.get('page') or index)}",
                location_type="slide",
                location_index=int(item.get("page") or index),
            )
            for index, item in enumerate(page_texts, start=1)
            if str(item.get("text") or "").strip()
        ]

    location_type = (
        "slide" if document_type == "pptx"
        else "web_section" if document_type == "html"
        else "heading"
    )
    return extract_markdown_segments_from_text(markdown, location_type=location_type)


def delete_vectors_for_file(file_id: int):
    """按 file_id 幂等删除全部向量，供失败补偿和文件删除共同使用。"""
    with VECTOR_WRITE_LOCK:
        collection.delete(where={"file_id": file_id})


def _mark_ingestion_failed(
    file_id: int,
    engine: str,
    started_at: float,
    error: Exception | str,
    page_count: int = 0,
    unit_type: str = "page",
    unit_count: int = 0,
):
    """失败补偿：先清除可能已写入的向量，再持久化 failed 状态。"""
    cleanup_errors = []
    try:
        delete_vectors_for_file(file_id)
    except Exception as exc:
        cleanup_errors.append(f"向量补偿删除失败: {exc}")

    message = str(error).strip() or type(error).__name__
    if cleanup_errors:
        message = f"{message}；{'；'.join(cleanup_errors)}"
    try:
        update_file_ingestion(
            file_id,
            "failed",
            engine=engine,
            page_count=page_count,
            unit_type=unit_type,
            unit_count=unit_count,
            elapsed_ms=max(0, int((time.monotonic() - started_at) * 1000)),
            chunk_count=0,
            error_message=message[:4000],
            completed_at=_local_timestamp(),
        )
    except Exception as exc:
        cleanup_errors.append(f"失败状态写入失败: {exc}")

    return cleanup_errors


def recover_interrupted_ingestions():
    """服务启动时把上次异常退出遗留的中间态补偿为 failed。"""
    conn = get_db_connection()
    try:
        interrupted_files = conn.execute(
            """
            SELECT id, status, engine FROM knowledge_files
            WHERE status IN ('uploaded', 'parsing', 'indexing')
            ORDER BY id
            """
        ).fetchall()
    finally:
        conn.close()

    recovered = []
    for file_record in interrupted_files:
        cleanup_error = None
        try:
            delete_vectors_for_file(file_record["id"])
        except Exception as exc:
            cleanup_error = f"；向量补偿删除失败: {exc}"
        update_file_ingestion(
            file_record["id"],
            "failed",
            engine=file_record["engine"],
            chunk_count=0,
            error_message=(
                f"服务重启时发现遗留状态 {file_record['status']}，已中止本次入库"
                f"{cleanup_error or ''}"
            )[:4000],
            completed_at=_local_timestamp(),
        )
        recovered.append(file_record["id"])
    return recovered


def backfill_ready_file_metrics():
    """从原文件和 Chroma 元数据补齐旧 ready 记录的类型、定位单元和块数。"""
    conn = get_db_connection()
    try:
        ready_files = conn.execute(
            """
            SELECT id, file_name, file_path, page_count, chunk_count, engine,
                   document_type, unit_type, unit_count
            FROM knowledge_files
            WHERE status = 'ready'
              AND (chunk_count = 0 OR engine IS NULL OR unit_count = 0)
            ORDER BY id
            """
        ).fetchall()
    finally:
        conn.close()

    updated_file_ids = []
    for file_record in ready_files:
        try:
            stored = collection.get(
                where={"file_id": file_record["id"]},
                include=["metadatas"],
            )
        except Exception:
            continue
        ids = stored.get("ids") or []
        metadatas = stored.get("metadatas") or []
        if not ids:
            continue

        stored_path = file_record["file_path"]
        resolved_path = stored_path if os.path.isabs(stored_path) else os.path.join(BACKEND_DIR, stored_path)
        document_type = file_record["document_type"] or document_type_from_filename(file_record["file_name"])
        unit_type = file_record["unit_type"] or ("page" if document_type == "pdf" else "heading")
        page_count = file_record["page_count"] or 0
        if document_type == "pdf" and os.path.isfile(resolved_path):
            try:
                page_count = _pdf_page_count(resolved_path)
            except Exception:
                pass

        location_indexes = [
            int(metadata.get("location_index") or metadata.get("page") or 0)
            for metadata in metadatas
            if metadata
        ]
        unit_count = file_record["unit_count"] or max(location_indexes or [0])
        if document_type == "pdf" and page_count:
            unit_type = "page"
            unit_count = page_count

        engine = file_record["engine"]
        if not engine:
            engine = next(
                (metadata.get("engine") for metadata in metadatas if metadata and metadata.get("engine")),
                None,
            )
        try:
            update_file_ingestion(
                file_record["id"],
                page_count=page_count,
                chunk_count=len(ids),
                engine=engine,
                document_type=document_type,
                unit_type=unit_type,
                unit_count=unit_count,
            )
            updated_file_ids.append(file_record["id"])
        except Exception:
            continue
    return updated_file_ids

def _terminate_process_tree(process):
    """超时时终止解析器及其 Windows 子进程，避免 GPU 任务残留。"""
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
        else:
            process.kill()
    except (OSError, subprocess.SubprocessError):
        try:
            process.kill()
        except OSError:
            pass


def _extract_with_external_engine_stream(engine: str, pdf_path: str):
    """运行外部引擎，并持续产生日志/心跳，最终通过 StopIteration 返回 Markdown。"""
    if not is_initialized(engine):
        raise RuntimeError(f"{engine.upper()} 尚未完成扫描件初始化验证")

    output_dir = os.path.join(os.path.dirname(pdf_path), f"{engine}_{uuid.uuid4().hex[:6]}")
    use_gpu = get_engine_device(engine) == "cuda"
    cmd = build_engine_command(engine, pdf_path, output_dir, use_gpu=use_gpu)
    timeout_seconds = ENGINE_TIMEOUT_SECONDS[engine]

    process = None
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_build_subprocess_env(use_gpu),
            bufsize=1,
        )
        output_queue = queue.Queue()
        recent_output = []

        def pump_output():
            try:
                for line in iter(process.stdout.readline, ""):
                    output_queue.put(line)
            finally:
                output_queue.put(None)

        threading.Thread(target=pump_output, daemon=True).start()
        started_at = time.monotonic()
        last_heartbeat_at = started_at

        while True:
            now = time.monotonic()
            if now - started_at >= timeout_seconds:
                _terminate_process_tree(process)
                raise TimeoutError(
                    f"{engine.upper()} 超过 {timeout_seconds // 60} 分钟仍未完成，已停止该任务。"
                )
            try:
                line = output_queue.get(timeout=1)
            except queue.Empty:
                now = time.monotonic()
                if now - last_heartbeat_at >= ENGINE_HEARTBEAT_SECONDS:
                    elapsed = int(now - started_at)
                    yield f"[{engine.upper()}] 正在 GPU 解析，已运行 {elapsed} 秒…\n"
                    last_heartbeat_at = now
                continue

            if line is None:
                break
            line = line.strip()
            if line:
                recent_output.append(line)
                recent_output = recent_output[-20:]
                yield f"[{engine.upper()}] {line}\n"

        return_code = process.wait()
        if return_code != 0:
            detail = "\n".join(recent_output)[-1000:]
            raise RuntimeError(f"{engine.upper()} 进程失败（返回码 {return_code}）: {detail}")

        content = read_markdown_output(output_dir)
        if not content.strip():
            raise RuntimeError(f"{engine.upper()} 运行完毕，但未生成非空 Markdown")
        return {
            "text": content,
            "pages": _read_external_page_texts(engine, output_dir, content),
        }
    finally:
        if process is not None and process.poll() is None:
            _terminate_process_tree(process)
        shutil.rmtree(output_dir, ignore_errors=True)


def extract_with_marker(pdf_path: str) -> str:
    stream = _extract_with_external_engine_stream("marker", pdf_path)
    while True:
        try:
            next(stream)
        except StopIteration as done:
            return done.value["text"]


def extract_with_mineru(pdf_path: str) -> str:
    stream = _extract_with_external_engine_stream("mineru", pdf_path)
    while True:
        try:
            next(stream)
        except StopIteration as done:
            return done.value["text"]

# =====================================================================
# 🚀 通用文档流式处理闭环
# =====================================================================
def process_and_vectorize_document_stream(
    file_path: str,
    filename: str,
    file_id: int,
    course_id: int,
    engine: str = "pymupdf",
    *,
    document_type: str | None = None,
    mime_type: str | None = None,
    source_kind: str = "upload",
    source_url: str | None = None,
    replace_existing: bool = False,
):
    requested_engine = ENGINE_ALIASES.get(engine, engine)
    document_type = document_type or document_type_from_filename(filename)
    effective_engine = requested_engine
    started_at = time.monotonic()
    full_text = ""
    segments = []
    page_count = 0
    unit_type = "page" if document_type == "pdf" else "heading"
    unit_count = 0
    ingestion_ready = False
    try:
        if requested_engine not in ENGINE_LABELS:
            raise ValueError(f"不支持的文档解析引擎: {requested_engine}")
        if document_type in {"docx", "pptx"}:
            if requested_engine not in {"marker", "mineru"}:
                effective_engine = NATIVE_ENGINE_BY_DOCUMENT_TYPE[document_type]
        elif document_type == "html":
            # MinerU 本地 CLI 当前不接收 HTML；Marker 可处理，其他选择走安全原生提取。
            effective_engine = "marker" if requested_engine == "marker" else "html"
        elif document_type == "markdown":
            effective_engine = "markdown"

        engine_label = ENGINE_LABELS.get(effective_engine, effective_engine)
        document_label = DOCUMENT_TYPE_LABELS.get(document_type, document_type.upper())
        update_file_ingestion(
            file_id,
            "parsing",
            engine=effective_engine,
            elapsed_ms=0,
            page_count=0,
            document_type=document_type,
            mime_type=mime_type,
            source_kind=source_kind,
            source_url=source_url,
            unit_type=unit_type,
            unit_count=0,
            chunk_count=0,
            error_message=None,
            started_at=_local_timestamp(),
            completed_at=None,
        )
        yield f"[状态] uploaded → parsing\n"
        yield f"[系统] 🚀 开始处理 {document_label}: {filename} (采用引擎: {engine_label})\n"

        if document_type == "pdf":
            page_count = _pdf_page_count(file_path)
            unit_type = "page"
            unit_count = page_count

        if effective_engine in {"mineru", "marker"}:
            device = get_engine_device(effective_engine).upper()
            yield f"[解析] 🧠 正在启用 {ENGINE_LABELS[effective_engine]}（运行设备: {device}）深度视觉提取...\n"
            extraction_stream = _extract_with_external_engine_stream(effective_engine, file_path)
            while True:
                try:
                    yield next(extraction_stream)
                except StopIteration as done:
                    extraction_result = done.value
                    full_text = extraction_result["text"]
                    segments = _external_output_segments(
                        document_type,
                        extraction_result["pages"],
                        full_text,
                    )
                    break
            if document_type == "pptx":
                unit_type = "slide"
            elif document_type == "html":
                unit_type = "web_section"
            elif document_type == "pdf":
                unit_type = "page"
            else:
                unit_type = "heading"
            if document_type == "pdf":
                unit_count = page_count
            else:
                unit_count = max(
                    [int(segment.get("location_index") or 0) for segment in segments] or [len(segments)]
                )
        elif document_type == "pdf":
            yield "[解析] 📄 正在调用 PyMuPDF 提取文字层...\n"
            page_texts, ocr_page_count, total_page_count = extract_pages_with_pymupdf(file_path)
            page_count = total_page_count
            unit_count = total_page_count
            segments = [
                _document_segment(
                    page["text"],
                    location_type="page",
                    location_index=page["page"],
                )
                for page in page_texts
            ]
            full_text = "\n\n".join(segment["text"] for segment in segments)
            if ocr_page_count:
                yield f"[OCR] 🖼️ 检测到 {ocr_page_count}/{total_page_count} 页无文字层，已用 Tesseract 完成识别。\n"
        else:
            yield f"[解析] 📄 正在使用 {engine_label} 提取结构化文本...\n"
            extraction_result = extract_native_document(file_path, document_type)
            segments = extraction_result["segments"]
            full_text = extraction_result["text"]
            unit_type = extraction_result["unit_type"]
            unit_count = extraction_result["unit_count"]
            effective_engine = extraction_result["engine"]

        if not full_text or not full_text.strip():
            raise RuntimeError("未能提取到任何文本")

        yield "[切片] ✂️ 文本提取成功，正在按来源位置与章节进行切片...\n"
        chunks = build_document_chunks(segments)
        if not chunks:
            raise RuntimeError("已提取到文本，但未生成可入库的文档片段")

        update_file_ingestion(
            file_id,
            "indexing",
            engine=effective_engine,
            page_count=page_count,
            unit_type=unit_type,
            unit_count=unit_count,
            chunk_count=0,
            elapsed_ms=max(0, int((time.monotonic() - started_at) * 1000)),
            error_message=None,
        )
        yield "[状态] parsing → indexing\n"

        yield f"[向量化] 🧠 共生成 {len(chunks)} 个片段。准备写入 ChromaDB...\n"
        
        # 一次性提交同一文件的全部切片。逐片 add 会反复触发 HNSW compaction，
        # 在 Windows 本地持久化库中更容易留下半完成的索引文件。
        yield f"[数据库] ⏳ 正在批量写入 {len(chunks)} 个片段...\n"
        # 同一持久化 HNSW 索引不允许两个上传请求同时 compaction。
        # 锁只覆盖实际写入，解析/OCR 仍可并行执行。
        if replace_existing:
            yield "[数据库] 🧹 正在替换本文件的旧向量索引...\n"
        with VECTOR_WRITE_LOCK:
            # 无论新入库还是重建都先按 file_id 清理，保证重试幂等且不会残留孤儿片段。
            collection.delete(where={"file_id": file_id})
            collection.add(
                documents=[chunk["text"] for chunk in chunks],
                metadatas=[
                    {
                        "file_id": file_id,
                        "course_id": course_id,
                        "source": filename,
                        "page": chunk["page"],
                        "section": chunk["section"],
                        "document_type": document_type,
                        "source_kind": source_kind,
                        "source_url": source_url or "",
                        "location_type": chunk["location_type"],
                        "location_index": chunk["location_index"],
                        "chunk_index": chunk["chunk_index"],
                        "engine": effective_engine,
                    }
                    for chunk in chunks
                ],
                ids=[f"file_{file_id}_chunk_{index}_{uuid.uuid4()}" for index in range(len(chunks))],
            )

        elapsed_ms = max(0, int((time.monotonic() - started_at) * 1000))
        update_file_ingestion(
            file_id,
            "ready",
            engine=effective_engine,
            page_count=page_count,
            unit_type=unit_type,
            unit_count=unit_count,
            chunk_count=len(chunks),
            elapsed_ms=elapsed_ms,
            error_message=None,
            completed_at=_local_timestamp(),
        )
        ingestion_ready = True
        yield f"[数据库] ✅ 写入完成: {len(chunks)}/{len(chunks)}\n"
        unit_labels = {"page": "页", "slide": "张幻灯片", "heading": "个章节", "web_section": "个网页章节"}
        yield f"[状态] indexing → ready（{unit_count} {unit_labels.get(unit_type, '个单元')} / {len(chunks)} 块 / {elapsed_ms} ms）\n"
        yield "[系统] ✅ 该课件档案已成功转化为高维向量记忆！\n"

    except GeneratorExit:
        if not ingestion_ready:
            _mark_ingestion_failed(
                file_id, effective_engine, started_at, "客户端中断了入库流",
                page_count, unit_type, unit_count,
            )
        raise
    except Exception as exc:
        cleanup_errors = _mark_ingestion_failed(
            file_id, effective_engine, started_at, exc, page_count, unit_type, unit_count
        )
        yield f"[致命异常] 💥 处理中断: {str(exc)}。已按 file_id 补偿删除向量。\n"
        for cleanup_error in cleanup_errors:
            yield f"[清理警告] ⚠️ {cleanup_error}\n"
        yield "[状态] → failed（原始文件和错误记录已保留，可重新入库）\n"


def process_and_vectorize_pdf_stream(*args, **kwargs):
    """兼容旧模块调用；新代码应使用通用文档入口。"""
    yield from process_and_vectorize_document_stream(*args, **kwargs)

def _build_retrieval_filter(course_id=None, course_ids=None, file_ids=None):
    """组合 Chroma where 条件：课程与指定文件同时存在时取交集。"""
    filters = []
    normalized_course_ids = sorted({int(value) for value in (course_ids or [])})
    if normalized_course_ids:
        if len(normalized_course_ids) == 1:
            filters.append({"course_id": normalized_course_ids[0]})
        else:
            filters.append({"course_id": {"$in": normalized_course_ids}})
    elif course_id is not None:
        filters.append({"course_id": int(course_id)})

    normalized_file_ids = sorted({int(file_id) for file_id in (file_ids or [])})
    if normalized_file_ids:
        filters.append({"file_id": {"$in": normalized_file_ids}})

    if not filters:
        return None
    if len(filters) == 1:
        return filters[0]
    return {"$and": filters}


def insufficient_evidence_response(diagnostics=None):
    return {
        "context": "",
        "sources": [],
        "has_sufficient_evidence": False,
        "message": "资料库没有足够依据",
        "retrieval": diagnostics or {},
    }


def _tokenize_for_bm25(text: str):
    """无需 jieba 的中英混合分词：英文词 + 中文单字/双字词。"""
    normalized = unicodedata.normalize("NFKC", text or "").lower()
    segments = re.findall(r"[a-z0-9]+(?:[._+/-][a-z0-9]+)*|[\u3400-\u9fff]+", normalized)
    tokens = []
    for segment in segments:
        if re.fullmatch(r"[\u3400-\u9fff]+", segment):
            tokens.extend(character for character in segment if character.strip())
            tokens.extend(segment[index:index + 2] for index in range(len(segment) - 1))
        else:
            tokens.append(segment)
    return tokens


def _bm25_scores(query: str, documents):
    tokenized_documents = [_tokenize_for_bm25(document) for document in documents]
    query_tokens = _tokenize_for_bm25(query)
    document_count = len(tokenized_documents)
    if not query_tokens or not document_count:
        return [0.0] * document_count

    document_frequencies = Counter()
    for tokens in tokenized_documents:
        document_frequencies.update(set(tokens))
    average_length = sum(len(tokens) for tokens in tokenized_documents) / document_count or 1.0
    k1 = 1.5
    b = 0.75
    raw_scores = []
    for tokens in tokenized_documents:
        term_frequencies = Counter(tokens)
        document_length = len(tokens) or 1
        score = 0.0
        for token in set(query_tokens):
            frequency = term_frequencies.get(token, 0)
            if not frequency:
                continue
            document_frequency = document_frequencies.get(token, 0)
            inverse_document_frequency = math.log(
                1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
            )
            denominator = frequency + k1 * (1 - b + b * document_length / average_length)
            score += inverse_document_frequency * frequency * (k1 + 1) / denominator
        raw_scores.append(score)

    maximum_score = max(raw_scores, default=0.0)
    if maximum_score <= 0:
        return [0.0] * document_count
    return [score / maximum_score for score in raw_scores]


def _query_coverage_score(query: str, document: str):
    query_tokens = _tokenize_for_bm25(query)
    key_tokens = {token for token in query_tokens if len(token) > 1}
    if not key_tokens:
        key_tokens = set(query_tokens)
    if not key_tokens:
        return 0.0
    document_tokens = set(_tokenize_for_bm25(document))
    return len(key_tokens & document_tokens) / len(key_tokens)


def _cosine_similarity(left, right):
    if left is None or right is None or len(left) == 0 or len(right) == 0:
        return 0.0
    dot_product = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
    right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return max(-1.0, min(1.0, dot_product / (left_norm * right_norm)))


def _lexical_similarity(left: str, right: str):
    left_tokens = set(_tokenize_for_bm25(left))
    right_tokens = set(_tokenize_for_bm25(right))
    union = left_tokens | right_tokens
    return len(left_tokens & right_tokens) / len(union) if union else 0.0


def _vector_relevance(distance):
    if distance is None:
        return 0.0
    # Chroma 默认 L2 距离；对归一化向量有 cos ≈ 1 - L2²/2。
    return max(0.0, min(1.0, 1.0 - float(distance) / 2.0))


def _mmr_select(candidates, pool_size=RETRIEVAL_MMR_POOL_SIZE):
    selected = []
    remaining = list(candidates)
    while remaining and len(selected) < pool_size:
        best_candidate = None
        best_mmr_score = -float("inf")
        for candidate in remaining:
            redundancy = 0.0
            if selected:
                similarities = []
                for selected_candidate in selected:
                    if candidate.get("embedding") is not None and selected_candidate.get("embedding") is not None:
                        similarities.append(
                            max(0.0, _cosine_similarity(candidate["embedding"], selected_candidate["embedding"]))
                        )
                    else:
                        similarities.append(
                            _lexical_similarity(candidate["document"], selected_candidate["document"])
                        )
                redundancy = max(similarities, default=0.0)
            mmr_score = MMR_LAMBDA * candidate["hybrid_score"] - (1 - MMR_LAMBDA) * redundancy
            if mmr_score > best_mmr_score:
                best_candidate = candidate
                best_mmr_score = mmr_score
        best_candidate["mmr_score"] = best_mmr_score
        selected.append(best_candidate)
        remaining = [candidate for candidate in remaining if candidate is not best_candidate]
    return selected


def _get_reranker():
    global _RERANKER_MODEL, _RERANKER_LOAD_ATTEMPTED, _RERANKER_LOAD_ERROR
    if _RERANKER_LOAD_ATTEMPTED:
        return _RERANKER_MODEL
    with RERANKER_LOCK:
        if _RERANKER_LOAD_ATTEMPTED:
            return _RERANKER_MODEL
        _RERANKER_LOAD_ATTEMPTED = True
        try:
            from sentence_transformers import CrossEncoder

            _RERANKER_MODEL = CrossEncoder(
                RERANKER_MODEL_NAME,
                device=RERANKER_DEVICE,
                local_files_only=RERANKER_LOCAL_FILES_ONLY,
                max_length=512,
            )
        except Exception as exc:
            _RERANKER_LOAD_ERROR = str(exc)
            _RERANKER_MODEL = None
    return _RERANKER_MODEL


def _reranker_passages(document: str, window_size: int = 360):
    """长 chunk 用首尾重叠窗口重排，避免关键词在 512 token 截断区之外。"""
    clean_document = (document or "").strip()
    if len(clean_document) <= window_size:
        return [clean_document]
    starts = {0, max(0, len(clean_document) - window_size)}
    middle_start = max(0, len(clean_document) // 2 - window_size // 2)
    starts.add(middle_start)
    return [clean_document[start:start + window_size] for start in sorted(starts)]


def _rerank_candidates(query: str, candidates):
    reranker = _get_reranker()
    if reranker is None:
        for candidate in candidates:
            candidate["reranker_score"] = None
            candidate["final_score"] = candidate["hybrid_score"]
        return "hybrid-fallback"

    pairs = []
    candidate_indexes = []
    for candidate_index, candidate in enumerate(candidates):
        for passage in _reranker_passages(candidate["document"]):
            pairs.append([query, passage])
            candidate_indexes.append(candidate_index)
    with RERANKER_LOCK:
        raw_scores = reranker.predict(pairs, batch_size=4, show_progress_bar=False)
    candidate_scores = [[] for _ in candidates]
    for candidate_index, raw_score in zip(candidate_indexes, raw_scores):
        reranker_score = float(raw_score)
        if not 0.0 <= reranker_score <= 1.0:
            reranker_score = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, reranker_score))))
        candidate_scores[candidate_index].append(reranker_score)
    for candidate, scores in zip(candidates, candidate_scores):
        reranker_score = max(scores, default=0.0)
        candidate["reranker_score"] = reranker_score
        candidate["final_score"] = (
            0.70 * reranker_score
            + 0.18 * candidate["vector_score"]
            + 0.08 * candidate["bm25_score"]
            + 0.04 * candidate["coverage_score"]
        )
    return RERANKER_MODEL_NAME


def retrieve_relevant_context(
    query: str,
    n_results: int = RETRIEVAL_FINAL_COUNT,
    course_id=None,
    course_ids=None,
    file_ids=None,
    min_relevance: float = DEFAULT_MIN_RELEVANCE,
):
    """向量 Top 10 → BM25 融合 → MMR 去重 → reranker → 阈值后的 Top 3。"""
    try:
        query_args = {
            "query_texts": [query],
            "n_results": RETRIEVAL_CANDIDATE_COUNT,
            "include": ["documents", "metadatas", "distances", "embeddings"],
        }
        where = _build_retrieval_filter(course_id=course_id, course_ids=course_ids, file_ids=file_ids)
        if where is not None:
            query_args["where"] = where

        results = collection.query(**query_args)
        documents = (results.get("documents") or [[]])[0] or []
        metadatas = (results.get("metadatas") or [[]])[0] or []
        distances = (results.get("distances") or [[]])[0] or []
        raw_embeddings = results.get("embeddings")
        embeddings = raw_embeddings[0] if raw_embeddings is not None and len(raw_embeddings) else []
        if embeddings is None:
            embeddings = []
        if not documents:
            return insufficient_evidence_response({"candidate_count": 0})

        bm25_scores = _bm25_scores(query, documents)
        candidates = []
        for index, document in enumerate(documents):
            distance = distances[index] if index < len(distances) else None
            vector_score = _vector_relevance(distance)
            bm25_score = bm25_scores[index] if index < len(bm25_scores) else 0.0
            coverage_score = _query_coverage_score(query, document)
            candidates.append(
                {
                    "document": document,
                    "metadata": metadatas[index] if index < len(metadatas) and metadatas[index] else {},
                    "distance": distance,
                    "embedding": embeddings[index] if index < len(embeddings) else None,
                    "vector_score": vector_score,
                    "bm25_score": bm25_score,
                    "coverage_score": coverage_score,
                    "hybrid_score": 0.68 * vector_score + 0.22 * bm25_score + 0.10 * coverage_score,
                }
            )

        candidates.sort(key=lambda candidate: candidate["hybrid_score"], reverse=True)
        mmr_candidates = _mmr_select(candidates)
        reranker_name = _rerank_candidates(query, mmr_candidates)
        mmr_candidates.sort(key=lambda candidate: candidate["final_score"], reverse=True)

        selected_candidates = []
        seen_locations = set()
        for candidate in mmr_candidates:
            if candidate["final_score"] < min_relevance:
                continue
            metadata = candidate["metadata"]
            raw_page = metadata.get("page")
            page = raw_page if isinstance(raw_page, int) and raw_page > 0 else None
            location_type = metadata.get("location_type") or ("page" if page else "heading")
            raw_location_index = metadata.get("location_index")
            location_index = (
                raw_location_index
                if isinstance(raw_location_index, int) and raw_location_index > 0
                else page
            )
            location_key = (
                metadata.get("file_id"),
                location_type,
                location_index,
                metadata.get("section") or metadata.get("chunk_index"),
            )
            if location_key in seen_locations:
                continue
            seen_locations.add(location_key)
            selected_candidates.append(candidate)
            if len(selected_candidates) >= min(n_results, RETRIEVAL_FINAL_COUNT):
                break

        diagnostics = {
            "candidate_count": len(candidates),
            "mmr_count": len(mmr_candidates),
            "selected_count": len(selected_candidates),
            "min_relevance": min_relevance,
            "best_score": round(mmr_candidates[0]["final_score"], 6) if mmr_candidates else None,
            "reranker": reranker_name,
        }
        if not selected_candidates:
            return insufficient_evidence_response(diagnostics)

        context_parts = []
        sources = []
        for index, candidate in enumerate(selected_candidates):
            document = candidate["document"]
            metadata = candidate["metadata"]
            raw_page = metadata.get("page")
            page = raw_page if isinstance(raw_page, int) and raw_page > 0 else None
            document_type = str(metadata.get("document_type") or "pdf")
            source_kind = str(metadata.get("source_kind") or "upload")
            source_url = str(metadata.get("source_url") or "")
            location_type = str(metadata.get("location_type") or ("page" if page else "heading"))
            raw_location_index = metadata.get("location_index")
            location_index = (
                raw_location_index
                if isinstance(raw_location_index, int) and raw_location_index > 0
                else page
            )
            section = str(metadata.get("section") or "")
            file_name = str(metadata.get("source") or "未知文件")
            source = {
                "reference_id": index + 1,
                "file_id": metadata.get("file_id"),
                "file_name": file_name,
                "page": page,
                "document_type": document_type,
                "source_kind": source_kind,
                "source_url": source_url or None,
                "location_type": location_type,
                "location_index": location_index,
                "section": section,
                "chunk_index": metadata.get("chunk_index"),
                "engine": metadata.get("engine") or "未知",
                "distance": candidate["distance"],
                "score": round(candidate["final_score"], 6),
                "vector_score": round(candidate["vector_score"], 6),
                "bm25_score": round(candidate["bm25_score"], 6),
                "reranker_score": (
                    round(candidate["reranker_score"], 6)
                    if candidate["reranker_score"] is not None else None
                ),
            }
            sources.append(source)

            if location_type == "page" and location_index:
                location = f"第 {location_index} 页"
            elif location_type == "slide" and location_index:
                location = f"第 {location_index} 张幻灯片"
            elif section and section != "正文":
                location = f"章节：{section}"
            elif location_type == "web_section" and location_index:
                location = f"网页章节 {location_index}"
            else:
                location = "位置未标注"
            section_label = (
                f"｜{section}"
                if location_type in {"page", "slide"} and section and section != "正文"
                else ""
            )
            context_parts.append(
                f"【来源{index + 1}｜{file_name}｜{location}{section_label}】\n{document}"
            )

        return {
            "context": "\n\n---\n\n".join(context_parts),
            "sources": sources,
            "has_sufficient_evidence": True,
            "message": None,
            "retrieval": diagnostics,
        }
    except Exception as exc:
        print(f"检索异常: {exc}")
        return insufficient_evidence_response({"error": str(exc)[:300]})
