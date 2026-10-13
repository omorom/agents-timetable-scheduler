"""
/chat — รับข้อความจาก frontend แล้วส่งต่อให้ ADK agent ผ่าน chat_service.py

context (ไม่บังคับ) = ปัญหาจากการ์ดผลตรวจข้อมูลล่าสุดที่ผู้ใช้เห็นอยู่ในแชท
ถ้ามี จะแนบไว้หน้าคำถาม ให้ agent รู้ว่าผู้ใช้กำลังถามถึงปัญหานั้น
(ไม่งั้นคำถามลอยๆ อย่าง "เปลี่ยนห้องดีไหม" agent ไม่รู้บริบท แล้วตอบว่านอกเรื่อง)
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from chat_service import ask_agent

router = APIRouter()

MAX_CONTEXT_CHARS = 2000   # กันข้อความยาวเกินไป (เปลือง token)


class ChatIn(BaseModel):
    message: str
    user_id: str
    context: str = ""


def _with_context(message: str, context: str) -> str:
    context = (context or "").strip()[:MAX_CONTEXT_CHARS]
    if not context:
        return message
    return (
        "[บริบท: ระบบเพิ่งตรวจข้อมูลก่อนจัดตาราง และผู้ใช้เห็นปัญหาเหล่านี้อยู่ในแชท "
        "คำถามเกี่ยวกับปัญหาเหล่านี้หรือวิธีแก้ ถือเป็นเรื่องตารางเรียน ให้ตอบโดยอิงจากปัญหานี้]\n"
        f"{context}\n\n"
        f"คำถามของผู้ใช้: {message}"
    )


@router.post("/chat")
async def chat(body: ChatIn):
    try:
        reply = await ask_agent(body.user_id, _with_context(body.message, body.context))
        return {"reply": reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))