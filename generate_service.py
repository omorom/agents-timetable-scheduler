"""
generate_service.py
เชื่อม scheduling_pipeline (SequentialAgent, 4 agent จริง) เข้ากับ FastAPI
"""

import uuid

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agent_timetable.scheduling_agent import scheduling_pipeline

APP_NAME = "schedule_generator"

generate_session_service = InMemorySessionService()

generate_runner = Runner(
    agent=scheduling_pipeline,
    app_name=APP_NAME,
    session_service=generate_session_service,
)


async def run_generate() -> dict:
    session_id = f"generate-{uuid.uuid4()}"   # ← สุ่มใหม่ทุกครั้ง ไม่ผูกประวัติเก่า
    user_id = "system"

    await generate_session_service.create_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )

    content = types.Content(role="user", parts=[types.Part(text="จัดตารางเรียน")])

    final_text = ""
    async for event in generate_runner.run_async(
        user_id=user_id, session_id=session_id, new_message=content
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = event.content.parts[0].text

    # แก้ไข (สำคัญ): เดิมส่งกลับแค่ final_text (ข้อความสรุปให้คนอ่าน จาก reporter
    # agent) ทำให้ frontend เอาไปทำ badge/รายการวิชาที่จัดไม่ได้ไม่ได้เลย เพราะเป็น
    # string ยาวๆ ไม่ใช่ structured data — จริงๆ audit_and_report() ใน
    # scheduling_agent.py เก็บ "final_report" (มี failed_sessions, hard_issues
    # แบบ list พร้อม session_id/เหตุผล) ไว้ใน session state อยู่แล้ว แค่ไม่เคยถูก
    # ดึงออกมาใช้ ตอนนี้ดึง session กลับมาหลัง loop จบ แล้วส่ง final_report
    # ส่วนที่ frontend ต้องใช้กลับไปด้วย
    session = await generate_session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    final_report = (session.state.get("final_report") if session else None) or {}

    return {
        "message": final_text or "จัดตารางเสร็จแล้ว แต่ไม่มีข้อความสรุปกลับมา",
        "status": final_report.get("status"),
        "fully_complete": final_report.get("fully_complete", False),
        # รายชื่อ session/วิชาที่จัดไม่ได้เลยตั้งแต่ต้น (ไม่มีที่ว่างให้จัด)
        "failed_sessions": final_report.get("failed_sessions", []),
        # รายการ "ชนกัน" ที่เหลืออยู่ (ถ้ามี) พร้อม session_id ที่ frontend
        # เอาไปเรียก /move ต่อได้ ถ้าจะให้ user แก้เฉพาะจุดเอง
        "hard_issues": final_report.get("hard_issues", []),
    }