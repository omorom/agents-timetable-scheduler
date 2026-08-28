"""
generate_service.py
เชื่อม scheduling_pipeline (SequentialAgent, 4 agent จริง) เข้ากับ FastAPI
"""

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
    session_id = "generate-session"
    user_id = "system"

    existing = await generate_session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    if not existing:
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

    return {"message": final_text or "จัดตารางเสร็จแล้ว แต่ไม่มีข้อความสรุปกลับมา"}