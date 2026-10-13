"""
data_check_service.py — ตรวจความพร้อมของข้อมูล "ก่อน" จัดตาราง ให้หน้าเว็บเรียกผ่าน GET /check-data

รัน DataGatherAgent (agent ตัวเดียวกับขั้นแรกของ SchedulingPipeline):
  1. ดึงข้อมูลล่าสุด + ตรวจด้วย Python (ตัวเลข/ทางแก้ทั้งหมดมาจากตรงนี้)
  2. ถ้ามีเรื่องที่จัดไม่ได้แน่ -> DataReviewAgent (LLM) ประเมินผลกระทบ (รวมวิชาที่หลุดตามกัน)
     แล้วตัดสิน "fix_first" (ควรแก้ก่อน) / "ok_to_continue" (จัดต่อได้) พร้อมข้อความถึงผู้ใช้
     และทางเลือก 2-3 ทางให้ผู้ใช้เลือกเอง
ผลเก็บใน session -> ส่ง session_id ให้หน้าเว็บ พอกด "จัดต่อเลย" /generate รันต่อใน session เดิม ไม่ตรวจซ้ำ

  - ok = True  (ไม่มีเรื่อง "จัดไม่ได้แน่")  -> หน้าเว็บเรียก /generate ต่อได้เลย
  - ok = False -> เปิดแชทแสดงการ์ดปัญหา ให้ผู้ใช้เลือก "ไปแก้ข้อมูลก่อน" หรือ "จัดต่อเลย"

LLM ล่ม/ช้าเกิน CHECK_TIMEOUT -> ยังตอบได้ ใช้ผลจาก Python อย่างเดียว (ไม่มีบรรทัดสรุป)

วางไฟล์นี้ไว้ที่เดียวกับ generate_service.py
"""

import asyncio

from google.genai import types

from generate_service import APP_NAME, USER_ID, generate_session_service, check_runner, _session_or_new
from agent_timetable.tools.scheduling.load_data import refresh_cache
from agent_timetable.tools.scheduling.data_check import check_data_readiness

CHECK_TIMEOUT = 40   # วินาที — รอ LLM สรุปได้นานสุดเท่านี้

# หมวดของปัญหา ใช้บอกหน้าเว็บว่าปุ่ม "ไปแก้ข้อมูล" ควรพาไปหน้าไหน
FIX_PAGE = {
    "no_teacher": "subjects", "no_group": "subjects", "team_no_common_time": "teachers",
    "teacher_overbooked": "teachers", "teacher_tight": "teachers",
    "no_room_big_enough": "rooms", "locked_room_missing": "subjects", "room_shortage": "rooms",
    "room_tight": "rooms", "locked_room_overload": "subjects",
    "group_overbooked": "subjects", "group_tight": "subjects", "group_day_limit": "subjects",
    "sync_partner_blocked": "teachers", "sync_no_common_time": "teachers", "sync_window": "teachers",
}


async def _run_agent(session_id: str) -> None:
    content = types.Content(role="user", parts=[types.Part(text="ตรวจความพร้อมของข้อมูลก่อนจัดตาราง")])
    async for _ in check_runner.run_async(user_id=USER_ID, session_id=session_id, new_message=content):
        pass


async def run_check_data() -> dict:
    session_id = await _session_or_new(None, "check")
    try:
        await asyncio.wait_for(_run_agent(session_id), timeout=CHECK_TIMEOUT)
    except Exception as e:  # noqa: BLE001 — LLM พัง/ช้า ไม่ให้ผู้ใช้กดสร้างตารางไม่ได้
        print(f"[check-data] agent ทำงานไม่จบ ใช้ผลจาก Python อย่างเดียว: {e!r}")

    session = await generate_session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
    )
    state = session.state if session else {}

    if "data_issues" in state:
        # DataGatherAgent บันทึกผลตรวจไว้แล้ว (บันทึกก่อนเรียก LLM เสมอ)
        has_sections = (state.get("context_summary") or {}).get("has_sections", True)
        raw_issues = state["data_issues"]
        summary = (state.get("data_review") or "").strip()
        decision = state.get("data_decision")
        options = list(state.get("data_options") or [])
    else:
        # agent พังตั้งแต่ก่อนตรวจเสร็จ -> ตรวจเองด้วย Python และไม่ส่ง session ต่อ (/generate จะดึง + ตรวจใหม่)
        data = refresh_cache()
        has_sections = bool(data["sections"])
        raw_issues = check_data_readiness() if has_sections else []
        summary, decision, options, session_id = "", None, [], None

    if not has_sections:
        return {"ok": True, "blocking": [], "warning": [], "summary": "", "decision": None, "options": [],
                "message": "ยังไม่มีวิชาที่เปิดสอน", "session_id": session_id}

    issues = [{**i, "fix_page": FIX_PAGE.get(i["kind"], "subjects")} for i in raw_issues]
    blocking = [i for i in issues if i["severity"] == "blocking"]
    warning = [i for i in issues if i["severity"] == "warning"]

    if blocking:
        affected = sorted({s for i in blocking for s in i["subjects"]})
        message = f"พบปัญหาข้อมูล {len(blocking)} เรื่อง · {len(affected)} วิชาจะจัดไม่ได้"
    elif warning:
        message = f"ข้อมูลพร้อมจัดตาราง มีเรื่องที่ควรระวัง {len(warning)} เรื่อง"
    else:
        message = "ข้อมูลพร้อมจัดตาราง"

    return {
        "ok": not blocking,
        "blocking": blocking,
        "warning": warning,
        "message": message,
        "summary": summary,          # DataReviewAgent: ข้อความถึงผู้ใช้ (ว่าง = LLM ไม่ได้ตอบ -> ใช้ message แทน)
        "decision": decision,        # "fix_first" | "ok_to_continue" | None (LLM ไม่ได้ตัดสิน)
        "options": options,          # ทางเลือก 2-3 ทาง เรียงจากที่แนะนำที่สุด (ว่าง = LLM ไม่ได้ตอบ)
        "session_id": session_id,    # ส่งกลับมาตอนเรียก /generate เพื่อใช้ผลตรวจนี้ต่อ
    }