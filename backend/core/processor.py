# backend/core/processor.py
import os
import sys
import uuid
import fitz # PyMuPDF
import subprocess
import shutil
from chromadb.utils import embedding_functions
import chromadb
from core.db import get_db_connection
from core.engine_init import _find_cli, _build_subprocess_env, get_engine_device  # ✨ 复用引擎初始化那边已经修好的 PATH/环境变量/设备偏好逻辑

# 初始化向量数据库路径与客户端
CHROMA_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'vector_db')
chroma_client = chromadb.PersistentClient(path=CHROMA_DATA_DIR)

bge_embeddings = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="BAAI/bge-small-zh-v1.5"
)
collection = chroma_client.get_or_create_collection(
    name="xmu_course_materials_v2",
    embedding_function=bge_embeddings
)

def extract_with_pypdf(pdf_path: str) -> str:
    """基础兜底：轻量级字符提取"""
    doc = fitz.open(pdf_path)
    text = "".join([page.get_text() for page in doc])
    doc.close()
    return text

def extract_with_marker(pdf_path: str) -> str:
    output_dir = os.path.join(os.path.dirname(pdf_path), f"marker_{uuid.uuid4().hex[:6]}")
    cli_path = _find_cli("marker_single") or "marker_single"
    cmd = [cli_path, pdf_path, "--output_dir", output_dir]

    # ✨ 读取用户在"引擎初始化"时选择的运行设备（CPU/GPU），保持解析时和初始化时行为一致
    use_gpu = get_engine_device("marker") == "cuda"

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_build_subprocess_env(use_gpu),
    )
    if result.returncode != 0:
        raise Exception(f"Marker 进程失败: {result.stderr.decode('utf-8', errors='replace')[-500:]}")
        
    md_file_path = None
    for root, _, files in os.walk(output_dir):
        for f in files:
            if f.endswith('.md'):
                md_file_path = os.path.join(root, f)
                break
                
    if not md_file_path:
        raise Exception("Marker 运行完毕，但未找到输出的 Markdown 文件")
        
    with open(md_file_path, "r", encoding="utf-8") as f:
        content = f.read()
    shutil.rmtree(output_dir, ignore_errors=True)
    return content

def extract_with_mineru(pdf_path: str) -> str:
    output_dir = os.path.join(os.path.dirname(pdf_path), f"mineru_{uuid.uuid4().hex[:6]}")
    cli_path = _find_cli("magic-pdf") or "magic-pdf"
    cmd = [cli_path, "-p", pdf_path, "-o", output_dir, "-m", "auto"]

    # ✨ MinerU 的设备选择是通过 magic-pdf.json 里的 device-mode 字段生效的
    # （已经在引擎初始化阶段写好），这里的 env 只是保持 PATH/镜像源一致。
    use_gpu = get_engine_device("mineru") == "cuda"

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_build_subprocess_env(use_gpu),
    )
    if result.returncode != 0:
        raise Exception(f"MinerU 进程失败 (可能缺少模型或依赖): {result.stderr.decode('utf-8', errors='replace')[-500:]}")
        
    md_file_path = None
    for root, _, files in os.walk(output_dir):
        for f in files:
            if f.endswith('.md'):
                md_file_path = os.path.join(root, f)
                break
                
    if not md_file_path:
        raise Exception("MinerU 运行完毕，但未找到输出的 Markdown 文件")
        
    with open(md_file_path, "r", encoding="utf-8") as f:
        content = f.read()
    shutil.rmtree(output_dir, ignore_errors=True)
    return content

# =====================================================================
# 🚀 核心流式处理闭环 (带完整的 try...except 防炸墙)
# =====================================================================
def process_and_vectorize_pdf_stream(file_path: str, filename: str, file_id: int, course_id: int, engine: str = "pypdf"):
    yield f"[系统] 🚀 开始处理文件: {filename} (采用引擎: {engine})\n"
    
    full_text = ""
    try:
        if engine == "mineru":
            device = get_engine_device("mineru").upper()
            yield f"[解析] 🔬 正在调用 MinerU（运行设备: {device}），启动深度视觉模型中...\n"
            full_text = extract_with_mineru(file_path)
        elif engine == "marker":
            device = get_engine_device("marker").upper()
            yield f"[解析] 🧠 正在启用 Marker（运行设备: {device}）深度视觉提取...\n"
            full_text = extract_with_marker(file_path)
        else:
            yield "[解析] 📄 正在调用 PyMuPDF 提取纯文本...\n"
            full_text = extract_with_pypdf(file_path)

        if not full_text or not full_text.strip():
            yield "[错误] ❌ 未能提取到任何文本！已安全终止，未写入向量库。\n"
            conn = get_db_connection()
            conn.execute("DELETE FROM knowledge_files WHERE id = ?", (file_id,))
            conn.commit()
            conn.close()
            return

        yield "[切片] ✂️ 文本提取成功，正在进行段落滑动切片...\n"
        chunk_size = 500
        overlap = 50
        chunks = []
        start = 0
        while start < len(full_text):
            end = min(start + chunk_size, len(full_text))
            chunks.append(full_text[start:end])
            start += chunk_size - overlap

        yield f"[向量化] 🧠 共生成 {len(chunks)} 个片段。准备写入 ChromaDB...\n"
        
        for i, chunk in enumerate(chunks):
            collection.add(
                documents=[chunk],
                metadatas=[{"file_id": file_id, "course_id": course_id, "source": filename}],
                ids=[f"file_{file_id}_chunk_{i}_{uuid.uuid4()}"]
            )
            if i % 5 == 0 or i == len(chunks) - 1:
                yield f"[数据库] ⏳ 写入进度: {i+1}/{len(chunks)}\n"
                
        yield "[系统] ✅ 该课件档案已成功转化为高维向量记忆！\n"

    except Exception as e:
        yield f"[致命异常] 💥 处理中断: {str(e)}。系统已自动启动隔离机制，保护数据库完整性。\n"
        conn = get_db_connection()
        conn.execute("DELETE FROM knowledge_files WHERE id = ?", (file_id,))
        conn.commit()
        conn.close()

def retrieve_relevant_context(query: str, n_results: int = 3) -> str:
    try:
        results = collection.query(query_texts=[query], n_results=n_results)
        if results['documents'] and results['documents'][0]:
            return "\n---\n".join(results['documents'][0])
    except Exception as e:
        print(f"检索异常: {e}")
    return ""