"""
test_repair.py — เทสการ "ซ่อมเฉพาะวิชาที่ตก" กับข้อมูลจริงใน Supabase

วางไฟล์นี้ไว้ที่โฟลเดอร์ราก (โฟลเดอร์ที่มี agent_timetable/ อยู่ข้างใน) แล้วรัน:
    python test_repair.py

คำเตือน: สคริปต์นี้เขียนทับตาราง timetable_ai เหมือนกดปุ่ม "สร้างตาราง" บนเว็บ
"""
import time

from agent_timetable.tools import auto_assign
from agent_timetable.tools.load_data import refresh_cache
from agent_timetable.tools.assignment_store import get_current_schedule_raw
from agent_timetable.tools.find_issues import find_issues

# แอบจำผลรอบแรกไว้เทียบ (ก่อนซ่อม)
first: dict = {}
_orig_full_run = auto_assign._full_run


def _spy(*args, **kwargs):
    result = _orig_full_run(*args, **kwargs)
    if not first:
        first["failed"] = result["failed_count"]
        first["rows"] = {a["session_id"]: a["timeslot_id"] for a in get_current_schedule_raw() if a.get("session_id")}
    return result


auto_assign._full_run = _spy

refresh_cache()
started = time.time()
result = auto_assign.auto_assign_all()
elapsed = time.time() - started

final = {a["session_id"]: a["timeslot_id"] for a in get_current_schedule_raw() if a.get("session_id")}
moved = [s for s, t in first["rows"].items() if s in final and final[s] != t]
dropped = [s for s in first["rows"] if s not in final]
hard = [i for i in find_issues() if i.get("severity") == "hard"]

print()
print(f"วิชาที่ตกหลังรอบแรก : {first['failed']}")
print(f"วิชาที่ตกตอนจบ      : {result['failed_count']}")
print(f"ปัญหาชนกัน (hard)    : {len(hard)}")
print(f"วิชาที่จัดได้แล้วแต่ถูกย้ายเวลา : {len(moved)} จาก {len(first['rows'])}")
print(f"วิชาที่จัดได้แล้วแต่หลุดออก     : {len(dropped)}")
print(f"ใช้เวลา                : {elapsed:.0f} วินาที")
for step in result.get("repair_log", []):
    print(f"  ซ่อม {step['session_id']} ได้ (รอบ {step['round']}) ย้ายวิชาอื่น: {', '.join(step['moved']) or '-'}")
for f in result["failed"]:
    print(f"  ยังตก: {f['session_id']} ({f.get('subject_id')} {f.get('session_type')}) — {f.get('reason')}")