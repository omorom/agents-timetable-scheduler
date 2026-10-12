"""
generate_service.py
เชื่อม agent จัดตารางเข้ากับ FastAPI

  /check-data  -> data_check_agent    (DataGatherAgent + DataReviewAgent) ตรวจข้อมูลก่อนจัด
  /generate    -> scheduling_pipeline (DataGatherAgent -> QualityLoop)    จัดตาราง

สองตัวใช้ session service เดียวกัน: ถ้า /generate ได้ check_session_id มา จะรันต่อใน session เดิม
DataGatherAgent เห็นผลตรวจใน state แล้วใช้ต่อเลย ไม่ดึงข้อมูล/ไม่ตรวจซ้ำ
"""

import uuid

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agent_timetable.scheduling_agent import scheduling_pipeline, data_check_agent

APP_NAME = "schedule_generator"
USER_ID = "system"

generate_session_service = InMemorySessionService()

generate_runner = Runner(
    agent=scheduling_pipeline,
    app_name=APP_NAME,
    session_service=generate_session_service,
)

check_runner = Runner(
    agent=data_check_agent,
    app_name=APP_NAME,
    session_service=generate_session_service,
)


async def _session_or_new(session_id: str | None, prefix: str) -> str:
    """ใช้ session เดิมถ้ายังอยู่ ไม่งั้นสร้างใหม่ (สุ่ม id ใหม่ ไม่ผูกประวัติเก่า)"""
    if session_id:
        old = await generate_session_service.get_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=session_id
        )
        if old:
            return session_id
    session_id = f"{prefix}-{uuid.uuid4()}"
    await generate_session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
    )
    return session_id


async def run_generate(check_session_id: str | None = None) -> dict:
    # check_session_id = session ที่ /check-data ตรวจข้อมูลไว้ (ผู้ใช้กด "จัดต่อเลย")
    # ไม่มี / หมดอายุ / server เพิ่งรีสตาร์ต -> สร้าง session ใหม่ แล้ว DataGatherAgent ดึง + ตรวจเอง
    session_id = await _session_or_new(check_session_id, "generate")

    content = types.Content(role="user", parts=[types.Part(text="จัดตารางเรียน")])

    final_text = ""
    async for event in generate_runner.run_async(
        user_id=USER_ID, session_id=session_id, new_message=content
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = event.content.parts[0].text

    # final_report (structured) อยู่ใน session state — ดึงออกมาให้ frontend ใช้ทำรายการวิชาที่จัดไม่ได้
    session = await generate_session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
    )
    final_report = (session.state.get("final_report") if session else None) or {}

    return {
        "message": final_text or "จัดตารางเสร็จแล้ว แต่ไม่มีข้อความสรุปกลับมา",
        "status": final_report.get("status"),
        "fully_complete": final_report.get("fully_complete", False),
        # รายชื่อ session/วิชาที่จัดไม่ได้
        "failed_sessions": final_report.get("failed_sessions", []),
        # รายการ "ชนกัน" ที่เหลืออยู่ (ถ้ามี) พร้อม session_id ที่ frontend เอาไปเรียก /move ต่อได้
        "hard_issues": final_report.get("hard_issues", []),
    }