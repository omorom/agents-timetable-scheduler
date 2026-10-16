"""
Chat Service — เชื่อม ADK root_agent เข้ากับ FastAPI
จัดการ session ต่อ user_id เพื่อให้แชทมี context ต่อเนื่อง

[ใหม่] ask_agent_full() คืนคำตอบ + "data_changed" = ตารางในฐานข้อมูลที่แชทแก้สำเร็จในรอบนี้
  หน้าเว็บใช้ค่านี้ตัดสินว่าต้องโหลดข้อมูลใหม่ไหม (ดู Chatbot.tsx: event "chatbot:data-changed")
  [] = ไม่ได้แก้อะไร (หน้าเว็บไม่ต้องโหลดใหม่)
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

# [ใหม่] tool ที่เขียนข้อมูล -> ตารางที่เปลี่ยน (ชื่อเดียวกับที่หน้าเว็บเช็ค)
MUTATION_TABLES: dict[str, list[str]] = {
    "set_teacher_unavailability": ["teacher_unavailability"],
    "remove_teacher_unavailability": ["teacher_unavailability"],
    "set_room_unavailability": ["room_unavailability"],
    "set_student_count": ["student_group"],
    "open_subject_section": ["subject_selected"],
    "close_subject_section": ["subject_selected"],
}


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


def _succeeded(response) -> bool:
    """ผลของ tool แก้ข้อมูลถือว่าสำเร็จ ถ้าไม่มี key "error" (tool ในโปรเจกต์คืน {"error": ...} เมื่อพลาด)"""
    if isinstance(response, dict):
        if "error" in response:
            return False
        # ADK บางเวอร์ชันห่อผลไว้ใน {"result": ...}
        inner = response.get("result")
        if isinstance(inner, dict) and "error" in inner:
            return False
    return True


async def ask_agent_full(user_id: str, message: str) -> dict:
    """ส่งข้อความเข้า agent แล้วคืน {"reply": คำตอบ, "data_changed": [ตารางที่แก้สำเร็จ]}"""
    await get_or_create_session(user_id)

    content = types.Content(role="user", parts=[types.Part(text=message)])

    final_reply = ""
    changed: list[str] = []
    async for event in runner.run_async(
        user_id=user_id, session_id=user_id, new_message=content
    ):
        # [ใหม่] เก็บว่ารอบนี้ tool แก้ข้อมูลตัวไหนทำงานสำเร็จบ้าง
        for fr in event.get_function_responses() or []:
            tables = MUTATION_TABLES.get(fr.name)
            if tables and _succeeded(fr.response):
                changed.extend(t for t in tables if t not in changed)

        if event.is_final_response() and event.content and event.content.parts:
            final_reply = event.content.parts[0].text or final_reply

    return {
        "reply": final_reply or "ขออภัย ไม่สามารถตอบได้ในขณะนี้",
        "data_changed": changed,
    }


async def ask_agent(user_id: str, message: str) -> str:
    """แบบเดิม — คืนแค่ข้อความคำตอบ (คงไว้ให้โค้ดที่เรียกอยู่แล้วใช้ได้เหมือนเดิม)"""
    return (await ask_agent_full(user_id, message))["reply"]