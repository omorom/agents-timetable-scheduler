"""
/chat — รับข้อความจาก frontend แล้วส่งต่อให้ ADK agent ผ่าน chat_service.py
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from chat_service import ask_agent

router = APIRouter()


class ChatIn(BaseModel):
    message: str
    user_id: str


@router.post("/chat")
async def chat(body: ChatIn):
    try:
        reply = await ask_agent(body.user_id, body.message)
        return {"reply": reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))