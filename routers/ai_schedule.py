"""
routers/schedule.py (ใหม่ — เกี่ยวกับผลลัพธ์ AI จัดตาราง แยกจาก routers/schedule.py เดิม
ถ้ามีชื่อชนกัน ให้ตั้งชื่อไฟล์นี้เป็น ai_schedule.py แทน)

GET /ai-schedule — คืนตารางที่ AI จัดล่าสุด แบบมีโครงสร้างครบ (ชื่อวิชา/ห้อง/เวลา/อาจารย์)
ให้ frontend เอาไปวาดเป็นกริดได้ตรงๆ ไม่ต้อง parse ข้อความ
"""

from fastapi import APIRouter, HTTPException

from agent_timetable.tools.scheduling.load_data import get_cached_data, refresh_cache
from agent_timetable.tools.scheduling.assignment_store import get_current_schedule

router = APIRouter()


@router.get("/ai-schedule")
def get_ai_schedule():
    """คืนตารางที่ AI จัดล่าสุด แยกเป็น list ต่อกลุ่มนิสิต (group_id) พร้อมรายละเอียดครบ"""
    try:
        refresh_cache()  # ดึงสดเสมอ กันข้อมูลค้าง
        data = get_cached_data()
        schedule = get_current_schedule()

        subjects_by_id = {s["subject_id"]: s for s in data["subjects"]}
        rooms_by_id = {r["room_id"]: r["room_name"] for r in data["rooms"]}
        timeslots_by_id = {str(t["timeslot_id"]): t for t in data["timeslots"]}
        teachers_by_id = {t["teacher_id"]: t["teacher_name"] for t in data["teachers"]}

        result: dict[str, list] = {}
        for item in schedule:
            subject = subjects_by_id.get(item["subject_id"], {})
            ts = timeslots_by_id.get(str(item["timeslot_id"]), {})

            entry = {
                "session_id": item["session_id"],
                "subject_id": item["subject_id"],
                "subject_name_thai": subject.get("name_thai"),
                "subject_name_english": subject.get("name_english"),
                "session_type": item["session_type"],
                "section": item.get("section"),
                "room_id": item["room_id"],
                "room_name": rooms_by_id.get(item["room_id"], item["room_id"]),
                "day": ts.get("day"),
                "start_time": ts.get("start_time"),
                "end_time": ts.get("end_time"),
                "teacher_names": [teachers_by_id.get(tid, tid) for tid in item.get("teacher_ids", [])],
            }

            for group_id in item.get("group_ids", []):
                result.setdefault(group_id, []).append(entry)

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))