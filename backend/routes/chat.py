# backend/routes/chat.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import openai

router = APIRouter()

class ModelConfig(BaseModel):
    name: str
    type: str
    apiKey: str
    baseUrl: str
    modelId: str

class ChatRequest(BaseModel):
    message: str
    config: ModelConfig
    context: str = "" 

@router.post("/")
async def chat_with_model_stream(req: ChatRequest):
    api_key = req.config.apiKey if req.config.apiKey else "dummy_key"
    
    client = openai.OpenAI(
        api_key=api_key,
        base_url=req.config.baseUrl
    )
    
    system_prompt = "你是厦大_JiaYuan助手。请根据提供的上下文回答用户问题。"
    if req.context:
        system_prompt += f"\n\n[检索到的课件上下文]:\n{req.context}"

    try:
        # ✨ 改造点 1：开启 stream=True
        response_stream = client.chat.completions.create(
            model=req.config.modelId,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": req.message}
            ],
            stream=True 
        )
        
        # ✨ 改造点 2：创建一个生成器函数，像水龙头一样一滴滴把文字挤出来
        def generate():
            for chunk in response_stream:
                if chunk.choices[0].delta.content is not None:
                    # 将模型吐出的文字直接 yield 传输给前端
                    yield chunk.choices[0].delta.content

        # ✨ 改造点 3：返回 StreamingResponse 而不是普通的 JSON
        return StreamingResponse(generate(), media_type="text/event-stream")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"模型调用失败: {str(e)}")