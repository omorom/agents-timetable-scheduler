"""
Chat Service — เชื่อม ADK root_agent เข้ากับ FastAPI
จัดการ session ต่อ user_id เพื่อให้แชทมี context ต่อเนื่อง

หมายเหตุ: ไฟล์นี้ยังไม่ได้ทดสอบกับ agent.py และเวอร์ชัน ADK จริงของโปรเจกต์
ต้องเช็ค method ของ Runner / SessionService ให้ตรงกับเวอร์ชันที่ติดตั้งอยู่ก่อนใช้งานจริง
"""

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agent_timetable.agent import root_agent

APP_NAME = "schedule_assistant"

# เก็บ session ไว้ใน memory (ข้อมูลหายถ้า restart server — พอสำหรับเริ่มต้น)
session_service = InMemorySessionService()

runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=session_service,
)


async def get_or_create_session(user_id: str):
    """เช็คว่า user นี้เคยมี session ไหม ถ้าไม่มีสร้างใหม่ ถ้ามีแล้วใช้ต่อ (เพื่อให้จำบทสนทนาได้)"""
    existing = await session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=user_id
    )
    if existing:
        return existing
    return await session_service.create_session(
        app_name=APP_NAME, user_id=user_id, session_id=user_id
    )


async def ask_agent(user_id: str, message: str) -> str:
    """ส่งข้อความเข้า agent แล้วรอ final response กลับมาเป็น string เดียว"""
    await get_or_create_session(user_id)

    content = types.Content(role="user", parts=[types.Part(text=message)])

    final_reply = ""
    async for event in runner.run_async(
        user_id=user_id, session_id=user_id, new_message=content
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_reply = event.content.parts[0].text

    return final_reply or "ขออภัย ไม่สามารถตอบได้ในขณะนี้"