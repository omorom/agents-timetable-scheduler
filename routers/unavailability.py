"""
ช่วงเวลาที่ไม่ว่าง (อาจารย์ / ห้องเรียน)
(ย้ายมาจาก main.py หมวด 6 แบบตรงๆ ไม่มีการแก้ logic เดิม
 + เพิ่ม endpoint /schedule-grid ใหม่ที่รวม timetable_ai เข้ามาด้วย
 + เพิ่ม subject_name/group_id ใน schedule-grid ให้ frontend โชว์ว่า "สอนอยู่แล้ว" ติดวิชาอะไร ชั้นปีไหน)
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent_timetable.tools.get_data import supabase
from agent_timetable.tools.scheduling.load_data import get_cached_data, refresh_cache

router = APIRouter()


class ToggleUnavailabilityIn(BaseModel):
    timeslot_id: int
    reason: str | None = None


@router.get("/teacher-unavailability/{teacher_id}")
def get_teacher_unavailability(teacher_id: str):
    try:
        return (
            supabase.table("teacher_unavailability")
            .select("*")
            .eq("teacher_id", teacher_id)
            .execute()
            .data
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/teacher-unavailability/{teacher_id}/schedule-grid")
def get_teacher_schedule_grid(teacher_id: str):
    """กริดเต็มสำหรับ modal: แต่ละ timeslot คืนสถานะ 3 แบบ
       - "teaching"     -> สอนอยู่แล้วจาก timetable_ai (คลิก toggle ไม่ได้) พร้อมชื่อวิชา/กลุ่ม
       - "unavailable"  -> ตั้งไว้ล่วงหน้าใน teacher_unavailability (toggle ได้)
       - "free"         -> ว่าง (toggle ได้)
    """
    try:
        data = get_cached_data()
        subjects_by_id = {s["subject_id"]: s for s in data["subjects"]}
        teachers_by_id = {t["teacher_id"]: t["teacher_name"] for t in data["teachers"]}

        unavail_ids = {
            u["timeslot_id"]
            for u in data["teacher_unavailability"]
            if u["teacher_id"] == teacher_id
        }

        # เก็บทั้ง subject_id และ group_id ไว้ด้วย ให้ frontend โชว์ "วิชา + ชั้นปี" ได้เลย
        teaching_map: dict[str, dict] = {}
        for a in data["existing"] + data["assignments"]:
            t_ids = a.get("teacher_ids") or ([a["teacher_id"]] if a.get("teacher_id") else [])
            if teacher_id in t_ids:
                teaching_map[a["timeslot_id"]] = {
                    "session_id": a.get("session_id"),
                    "subject_id": a.get("subject_id"),
                    "group_id": a.get("group_id"),
                    "teacher_id": a.get("teacher_id"),
                }

        grid = []
        for ts in data["timeslots"]:
            tid = ts["timeslot_id"]
            if tid in teaching_map:
                status = "teaching"
                info = teaching_map[tid]
                subject_id = info["subject_id"]
                subject = subjects_by_id.get(subject_id, {})
                subject_name = subject.get("name_thai") or subject.get("name_english") or subject_id
                group_id = info["group_id"]
                teacher_name = teachers_by_id.get(info.get("teacher_id"))
                session_id = info.get("session_id")
            else:
                status = "unavailable" if tid in unavail_ids else "free"
                subject_id = None
                subject_name = None
                group_id = None
                teacher_name = None
                session_id = None

            grid.append({
                "timeslot_id": tid,
                "day": ts["day"],
                "start_time": ts["start_time"],
                "end_time": ts["end_time"],
                "status": status,
                "session_id": session_id,
                "subject_id": subject_id,
                "subject_name": subject_name,
                "group_id": group_id,
                "teacher_name": teacher_name,
            })

        return grid
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/teacher-unavailability/{teacher_id}/toggle")
def toggle_teacher_unavailability(teacher_id: str, body: ToggleUnavailabilityIn):
    try:
        return _toggle_unavailability("teacher_unavailability", "teacher_id", teacher_id, body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/room-unavailability/{room_id}")
def get_room_unavailability(room_id: str):
    try:
        return (
            supabase.table("room_unavailability")
            .select("*")
            .eq("room_id", room_id)
            .execute()
            .data
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/room-unavailability/{room_id}/schedule-grid")
def get_room_schedule_grid(room_id: str):
    """เหมือน teacher/schedule-grid แต่สำหรับห้อง — เช็ค room_unavailability + timetable_ai (room_id)"""
    try:
        data = get_cached_data()
        subjects_by_id = {s["subject_id"]: s for s in data["subjects"]}
        teachers_by_id = {t["teacher_id"]: t["teacher_name"] for t in data["teachers"]}

        unavail_ids = {
            u["timeslot_id"]
            for u in data["room_unavailability"]
            if u["room_id"] == room_id
        }

        teaching_map: dict[str, dict] = {}
        for a in data["existing"] + data["assignments"]:
            if a.get("room_id") == room_id:
                teaching_map[a["timeslot_id"]] = {
                    "session_id": a.get("session_id"),
                    "subject_id": a.get("subject_id"),
                    "group_id": a.get("group_id"),
                    "teacher_id": a.get("teacher_id"),
                }

        grid = []
        for ts in data["timeslots"]:
            tid = ts["timeslot_id"]
            if tid in teaching_map:
                status = "teaching"
                info = teaching_map[tid]
                subject_id = info["subject_id"]
                subject = subjects_by_id.get(subject_id, {})
                subject_name = subject.get("name_thai") or subject.get("name_english") or subject_id
                group_id = info["group_id"]
                teacher_name = teachers_by_id.get(info.get("teacher_id"))
                session_id = info.get("session_id")
            else:
                status = "unavailable" if tid in unavail_ids else "free"
                subject_id = None
                subject_name = None
                group_id = None
                teacher_name = None
                session_id = None

            grid.append({
                "timeslot_id": tid,
                "day": ts["day"],
                "start_time": ts["start_time"],
                "end_time": ts["end_time"],
                "status": status,
                "session_id": session_id,
                "subject_id": subject_id,
                "subject_name": subject_name,
                "group_id": group_id,
                "teacher_name": teacher_name,
            })

        return grid
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/room-unavailability/{room_id}/toggle")
def toggle_room_unavailability(room_id: str, body: ToggleUnavailabilityIn):
    try:
        return _toggle_unavailability("room_unavailability", "room_id", room_id, body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _toggle_unavailability(table: str, entity_column: str, entity_id: str, body: ToggleUnavailabilityIn) -> dict:
    """กดครั้งแรก = เพิ่มเป็น 'ไม่ว่าง', กดซ้ำที่เดิม = เอาออก (กลับมาว่างปกติ)
    ใช้ร่วมกันได้ทั้ง teacher_unavailability และ room_unavailability เพราะโครงสร้างเหมือนกัน
    """
    existing = (
        supabase.table(table)
        .select("id")
        .eq(entity_column, entity_id)
        .eq("timeslot_id", body.timeslot_id)
        .execute()
    )

    if existing.data:
        supabase.table(table).delete().eq("id", existing.data[0]["id"]).execute()
        refresh_cache()
        return {"unavailable": False}

    supabase.table(table).insert(
        {entity_column: entity_id, "timeslot_id": body.timeslot_id}
    ).execute()
    refresh_cache()
    return {"unavailable": True}