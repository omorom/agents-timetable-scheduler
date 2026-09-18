"""
schedule_status_service.py
เช็คสถานะตารางปัจจุบัน "โดยไม่จัดใหม่" — ต่างจาก auto_assign_all() ที่ reset
แล้วจัดใหม่ทั้งหมดทุกครั้ง ตัวนี้แค่เทียบ "ควรมีอะไรบ้าง" (build_session_list())
กับ "มีอะไรอยู่จริงตอนนี้" (get_current_schedule_raw()) ว่าขาดตัวไหนไปบ้าง
พร้อมเช็ค hard issues ที่เหลือค้างอยู่ (find_issues()) — ใช้ตอนเปิดหน้าเว็บ/รีเฟรช
เพื่อโชว์แบนเนอร์สถานะได้ทันทีโดยไม่ต้องรอกด "สร้างตาราง" ก่อน

รูปแบบผลลัพธ์ตั้งใจให้ "หน้าตาเดียวกัน" กับ final_report ที่ audit_and_report()
ส่งกลับตอน generate (fully_complete, failed_sessions, hard_issues) เพื่อให้
frontend ใช้ type/шейп เดียวกันได้ทั้ง 2 endpoint ไม่ต้องแยก handling
"""

from .load_data import get_cached_data, refresh_cache
from .section_logic import build_session_list
from .assignment_store import get_current_schedule_raw
from .find_issues import find_issues


def get_schedule_status() -> dict:
    # รีเฟรช cache ก่อนเสมอ กัน state ค้างจากรอบก่อน (เผื่อมีคนแก้ข้อมูลใน
    # Supabase มาจากที่อื่น เช่น หน้า subject-selected)
    refresh_cache()
    data = get_cached_data()

    if not data.get("sections"):
        return {
            "status": "no_sections",
            "fully_complete": True,  # ไม่มีอะไรให้จัด ถือว่า "ครบ" ไม่ต้องขึ้นแจ้งเตือน
            "failed_sessions": [],
            "hard_issues": [],
        }

    expected_sessions = build_session_list()
    expected_by_id = {s["session_id"]: s for s in expected_sessions}

    current = get_current_schedule_raw()
    scheduled_ids = {item["session_id"] for item in current if item.get("session_id")}

    # session ที่ "ควรมี" แต่ไม่อยู่ในตารางปัจจุบันเลย = ยังไม่เคยถูกจัด
    missing_sessions = [
        {
            "session_id": sid,
            "subject_id": s.get("subject_id"),
            "session_type": s.get("session_type"),
            "section": s.get("section"),
            "group_ids": s.get("group_ids"),
            "reason": "ยังไม่ถูกจัดเข้าตาราง",
        }
        for sid, s in expected_by_id.items()
        if sid not in scheduled_ids
    ]

    issues = find_issues()
    hard_issues = [i for i in issues if i.get("severity") == "hard"]
    hard_issues_summary = [
        {
            "type": i.get("type"),
            "fix_session_id": i.get("fix_session_id"),
            "detail": i.get("detail"),
        }
        for i in hard_issues
    ]

    fully_complete = len(missing_sessions) == 0 and len(hard_issues) == 0

    return {
        "status": "ok" if fully_complete else "incomplete",
        "fully_complete": fully_complete,
        "failed_sessions": missing_sessions,
        "hard_issues": hard_issues_summary,
    }