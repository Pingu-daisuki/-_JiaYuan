from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# 核心魔法：直接导入你写好的 RAG 引擎！
import rag_kernel

app = FastAPI(title="Campus Assistant Local API")

# 允许前端跨域请求（极其重要，否则 Vue/React 连不上）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================
# 📦 数据传输模型 (定义前后端通信的 JSON 格式)
# =========================================================
class ChatRequest(BaseModel):
    query: str
    course_id: int = 1

class ConfigRequest(BaseModel):
    api_key: str
    base_url: str = "https://api.deepseek.com/v1"
    chat_model: str = "deepseek-chat"
    pdf_engine: str = "pypdf"

# =========================================================
# 🚀 路由接口定义
# =========================================================

@app.post("/api/chat")
async def chat_with_rag(request: ChatRequest):
    """ 聊天主接口：接收前端提问，返回大模型回答与参考文档 """
    # 1. 调动内核进行检索
    matched_contexts = rag_kernel.chroma_vector_search(
        request.query, 
        course_id=request.course_id, 
        top_k=2
    )
    
    # 2. 呼叫大模型
    answer = rag_kernel.ask_llm_with_rag(request.query, matched_contexts)
    
    # 3. 将结果打包成 JSON 返回给前端
    return {
        "answer": answer,
        "contexts": matched_contexts
    }

@app.post("/api/config")
async def update_config(request: ConfigRequest):
    """ 配置接口：接收前端传来的新设置并保存 """
    try:
        rag_kernel.save_user_api_config(
            request.api_key, 
            request.base_url, 
            request.chat_model, 
            request.pdf_engine
        )
        return {"status": "success", "message": "配置已更新并在本地持久化"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

# =========================================================
# 🏃‍♂️ 启动服务器
# =========================================================
if __name__ == "__main__":
    # 启动时自动加载历史配置
    rag_kernel.load_user_api_config()
    print("🚀 后端服务准备就绪！正在监听 8000 端口...")
    uvicorn.run(app, host="127.0.0.1", port=8000)