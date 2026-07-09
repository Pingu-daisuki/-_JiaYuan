import os
import sys
import sqlite3
import json
import requests
import chromadb
import subprocess
import shutil
from typing import List

# =====================================================================
# ⚙️ 核心配置类 (内存状态)
# =====================================================================
class LLMConfig:
    API_KEY = "YOUR_DEEPSEEK_API_KEY"
    BASE_URL = "https://api.deepseek.com/v1"
    CHAT_MODEL = "deepseek-chat"
    # 默认解析引擎，可选: "pypdf", "marker", "mineru"
    PDF_ENGINE = "pypdf" 


# =====================================================================
# 💾 路径与数据库初始化
# =====================================================================
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(CURRENT_DIR, 'campus_assistant.db')

# ChromaDB 本地持久化路径
CHROMA_DATA_DIR = os.path.join(CURRENT_DIR, 'chroma_data')
chroma_client = chromadb.PersistentClient(path=CHROMA_DATA_DIR)


# =====================================================================
# 💾 API 配置的持久化读写
# =====================================================================

def save_user_api_config(api_key: str, base_url: str, chat_model: str, pdf_engine: str = "pypdf"):
    """ 用户修改配置后，永久存入本地 SQLite，并支持切换 PDF 引擎 """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    config_data = {
        "api_key": api_key,
        "base_url": base_url,
        "chat_model": chat_model,
        "pdf_engine": pdf_engine
    }
    config_json = json.dumps(config_data)
    
    cursor.execute("""
        INSERT INTO `script_configs` (`script_name`, `account`, `encrypted_secret`)
        VALUES ('llm_core', 'default_user', ?)
        ON CONFLICT(`script_name`) DO UPDATE SET `encrypted_secret` = ?
    """, (config_json, config_json))
    
    conn.commit()
    conn.close()
    print(f"⚙️ 配置已保存！当前 AI 引擎已就绪，PDF 核心解析引擎已切换为: [{pdf_engine}]")
    
    LLMConfig.API_KEY = api_key
    LLMConfig.BASE_URL = base_url
    LLMConfig.CHAT_MODEL = chat_model
    LLMConfig.PDF_ENGINE = pdf_engine


def load_user_api_config():
    """ 软件启动时，自动加载历史配置与引擎偏好 """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT `encrypted_secret` FROM `script_configs` WHERE `script_name` = 'llm_core'")
        row = cursor.fetchone()
        if row:
            config_data = json.loads(row[0])
            LLMConfig.API_KEY = config_data.get("api_key", LLMConfig.API_KEY)
            LLMConfig.BASE_URL = config_data.get("base_url", LLMConfig.BASE_URL)
            LLMConfig.CHAT_MODEL = config_data.get("chat_model", LLMConfig.CHAT_MODEL)
            LLMConfig.PDF_ENGINE = config_data.get("pdf_engine", "pypdf")
            print(f"🤖 历史配置加载成功。当前 PDF 引擎: [{LLMConfig.PDF_ENGINE}]")
    except sqlite3.OperationalError:
        print("⚠️ 未找到配置表，请先执行建表脚本。")
    finally:
        conn.close()


# =====================================================================
# 🛠️ 阶段一：数据准备与多引擎动态解析 (按需下载与降级兜底)
# =====================================================================

def extract_with_pypdf(pdf_path: str) -> str:
    """ 引擎1 (基础兜底): pypdf 纯文本极速提取 """
    from pypdf import PdfReader
    reader = PdfReader(pdf_path)
    return "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])


def extract_with_marker_lazy(pdf_path: str) -> str:
    """ 引擎2 (性能优先): Marker 按需下载与 Markdown 解析 """
    try:
        import marker
    except ImportError:
        print("\n🚀 [系统提示] 检测到首次启用【Marker 极速解析模式】！")
        print("⏳ 正在后台按需下载 Marker 引擎，请稍候...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "marker-pdf", "-q"])
            print("✅ Marker 引擎安装完成！")
        except Exception as e:
            print(f"❌ 下载 Marker 失败 ({e})，自动降级为基础模式...")
            return extract_with_pypdf(pdf_path)

    print(f"🧠 正在调用 Marker 引擎解析: {os.path.basename(pdf_path)}")
    output_dir = os.path.join(CURRENT_DIR, "marker_output")
    cmd = f"marker_single \"{pdf_path}\" --output_dir \"{output_dir}\""
    
    try:
        subprocess.run(cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        file_base = os.path.splitext(os.path.basename(pdf_path))[0]
        md_file_path = os.path.join(output_dir, file_base, f"{file_base}.md")
        
        with open(md_file_path, "r", encoding="utf-8") as f:
            content = f.read()
        shutil.rmtree(output_dir, ignore_errors=True)
        return content
    except Exception as e:
        print(f"⚠️ Marker 运行异常({e})，自动降级为基础文本提取...")
        shutil.rmtree(output_dir, ignore_errors=True)
        return extract_with_pypdf(pdf_path)


def extract_with_mineru_lazy(pdf_path: str) -> str:
    """ 引擎3 (精度优先): MinerU 按需下载与复杂公式解析 """
    try:
        import magic_pdf
    except ImportError:
        print("\n🚀 [系统提示] 检测到首次启用【MinerU 深度强力模式】！")
        print("⏳ 正在后台为您拉取 MinerU 硬核分析套件 (体积较大，请耐心等待)...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "magic-pdf[full]", "-q"])
            print("✅ MinerU 引擎安装完成！")
        except Exception as e:
            print(f"❌ 下载 MinerU 失败 ({e})，自动降级为基础模式...")
            return extract_with_pypdf(pdf_path)

    print(f"🔬 正在调用 MinerU 引擎，死磕理工科复杂排版与 LaTeX 公式...")
    output_dir = os.path.join(CURRENT_DIR, "mineru_output")
    cmd = f"magic-pdf -p \"{pdf_path}\" -o \"{output_dir}\" -m auto"
    
    try:
        subprocess.run(cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        file_base = os.path.splitext(os.path.basename(pdf_path))[0]
        md_file_path = os.path.join(output_dir, file_base, "auto", f"{file_base}.md")
        
        with open(md_file_path, "r", encoding="utf-8") as f:
            content = f.read()
        shutil.rmtree(output_dir, ignore_errors=True)
        return content
    except Exception as e:
        print(f"⚠️ MinerU 运行异常({e})，自动降级为基础文本提取...")
        shutil.rmtree(output_dir, ignore_errors=True)
        return extract_with_pypdf(pdf_path)


def extract_text_from_pdf(pdf_path: str) -> str:
    """ 🚦 交通警察：根据用户的引擎选择，将任务分发给不同的本地解析器 """
    engine = LLMConfig.PDF_ENGINE
    
    if engine == "mineru":
        return extract_with_mineru_lazy(pdf_path)
    elif engine == "marker":
        return extract_with_marker_lazy(pdf_path)
    else:
        print(f"🍃 启动 [轻量基础模式] 极速通读: {os.path.basename(pdf_path)}")
        return extract_with_pypdf(pdf_path)


def split_text_into_chunks(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """ 文本切块：针对 Markdown 可以后续升级按标题切块，目前先采用字符滑动窗口 """
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += (chunk_size - overlap)
    return chunks


def save_file_to_sqlite(file_name: str, file_path: str, course_id: int = None) -> int:
    """ 在 SQLite 中记录文件元数据 """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    collection_name = f"course_{course_id if course_id else 'general'}_collection"
    
    cursor.execute("""
        INSERT INTO `knowledge_files` (`course_id`, `file_name`, `file_path`, `vector_collection`, `status`)
        VALUES (?, ?, ?, ?, 'success')
    """, (course_id, file_name, file_path, collection_name))
    
    file_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return file_id


def import_new_file_pipeline(local_pdf_path: str, course_id: int = None) -> bool:
    """ 完整的数据清洗与向量化闭环 """
    if not os.path.exists(local_pdf_path):
        print(f"❌ 导入失败：找不到本地文件 {local_pdf_path}")
        return False
        
    try:
        file_name = os.path.basename(local_pdf_path)
        
        # 1. 动态调度引擎提取文本/Markdown
        extracted_text = extract_text_from_pdf(local_pdf_path)
        
        # 2. 文本切块
        chunks = split_text_into_chunks(extracted_text, chunk_size=500, overlap=50)
        if not chunks:
            print("⚠️ 警告：有效文本为空，跳过向量化。")
            return False
            
        # 3. 记入 SQLite
        file_id = save_file_to_sqlite(file_name, local_pdf_path, course_id)
        
        # 4. 写入 Chroma 本地向量空间
        print(f"🌌 正在计算高维向量特征，注入 Chroma 本地数据库...")
        collection_name = f"course_{course_id if course_id else 'general'}_collection"
        collection = chroma_client.get_or_create_collection(name=collection_name)
        
        ids = [f"file_{file_id}_chunk_{i}" for i in range(len(chunks))]
        metadatas = [{"file_id": file_id, "source": file_name} for _ in chunks]
        collection.add(documents=chunks, metadatas=metadatas, ids=ids)
        
        print(f"🎉【{file_name}】解析与向量归档完美收官！切分为 {len(chunks)} 个高维概念块。")
        return True
    except Exception as e:
        print(f"❌ 文件处理链路异常: {e}")
        return False


# =====================================================================
# 🛠️ 阶段二：语义检索与大模型问答
# =====================================================================

def chroma_vector_search(query: str, course_id: int = None, top_k: int = 3) -> List[str]:
    """ 从本地空间寻找最匹配的课本片段 """
    collection_name = f"course_{course_id if course_id else 'general'}_collection"
    print(f"🔎 检索中: 正在向量空间中寻找与【{query}】语义最近的参考资料...")
    
    try:
        collection = chroma_client.get_collection(name=collection_name)
    except Exception:
        print("⚠️ 知识库为空。")
        return []

    results = collection.query(query_texts=[query], n_results=top_k)
    
    if results['documents'] and results['documents'][0]:
        return results['documents'][0]
    return []


def ask_llm_with_rag(query: str, context_chunks: List[str]) -> str:
    """ 组装事实依据，呼叫大模型开卷考试 """
    if not context_chunks:
        return "抱歉，本地知识库未提供任何参考背景，AI 无法凭空解答。"

    context_text = "\n---\n".join(context_chunks)
    prompt = f"""你是一个严谨的辅助导师。请严格基于以下已知的课本/资料内容回答用户的问题。
要求：若需推导或分析，请保留原文的 LaTeX 数学公式和 Markdown 代码格式。如果已知内容未涉及相关知识，直接回复“抱歉，本地未检索到确切内容”，绝不瞎编。

【已知参考依据】：
{context_text}

【用户提问】：
{query}
"""
    if LLMConfig.API_KEY == "YOUR_DEEPSEEK_API_KEY":
        return f"\n[提示：配置未生效，系统展示模拟开卷 Prompt 预览]\n\n{prompt}"

    headers = {
        "Authorization": f"Bearer {LLMConfig.API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": LLMConfig.CHAT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1
    }
    
    try:
        response = requests.post(f"{LLMConfig.BASE_URL}/chat/completions", headers=headers, json=payload)
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        return f"大模型通信失败: {e}"


# =====================================================================
# 🏃‍♂️ 调试运转入口
# =====================================================================
if __name__ == "__main__":
    # 1. 软件启动
    load_user_api_config()
    
    # 【测试指引】：
    # 想要测试强力解析引擎？取消下方注释，把最后一个参数改为 "marker" 或 "mineru"。
    # save_user_api_config("YOUR_KEY", "https://api.deepseek.com/v1", "deepseek-chat", "marker")
    
    print("-" * 50)
    
    # 2. 模拟文件导入测试
    test_pdf_path = os.path.join(CURRENT_DIR, "test_course.pdf")
    if os.path.exists(test_pdf_path):
        import_new_file_pipeline(test_pdf_path, course_id=1)
    else:
        print("💡 放置一个 'test_course.pdf' 在同目录，即可测试真实解析链路。")
        
    print("-" * 50)
    
    # 3. 模拟问答
    test_query = "求解戴维南等效电路的步骤是什么？"
    matched_contexts = chroma_vector_search(test_query, course_id=1, top_k=2)
    output = ask_llm_with_rag(test_query, matched_contexts)
    
    print("\n💡 终极智能化输出：\n", output)