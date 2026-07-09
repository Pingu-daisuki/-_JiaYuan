from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import openai # 这个库兼容几乎所有遵循OpenAI协议的模型

app = FastAPI()

class ChatRequest(BaseModel):
    message: str
    api_key: str
    base_url: str  # 动态配置模型地址
    model_name: str

@app.post("/api/chat")
async def chat_with_model(req: ChatRequest):
    # 动态初始化客户端，适应不同厂商的模型
    client = openai.OpenAI(
        api_key=req.api_key,
        base_url=req.base_url
    )
    
    try:
        response = client.chat.completions.create(
            model=req.model_name,
            messages=[{"role": "user", "content": req.message}]
        )
        return {"reply": response.choices[0].message.content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))