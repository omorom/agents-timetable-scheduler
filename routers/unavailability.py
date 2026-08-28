"""
ช่วงเวลาที่ไม่ว่าง (อาจารย์ / ห้องเรียน)
(ย้ายมาจาก main.py หมวด 6 แบบตรงๆ ไม่มีการแก้ logic เดิม
 + เพิ่ม endpoint /schedule-grid ใหม่ที่รวม timetable_ai เข้ามาด้วย)
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
       - "teaching"     -> สอนอยู่แล้วจาก timetable_ai (คลิก toggle ไม่ได้)
       - "unavailable"  -> ตั้งไว้ล่วงหน้าใน teacher_unavailability (toggle ได้)
       - "free"         -> ว่าง (toggle ได้)
    """
    try:
        data = get_cached_data()

        unavail_ids = {
            u["timeslot_id"]
            for u in data["teacher_unavailability"]
            if u["teacher_id"] == teacher_id
        }

        # ต้องรวมทั้ง existing (ล็อกไว้แล้ว/GENERAL) และ assignments (AI จัดไว้รอบนี้)
        teaching_map: dict[str, str | None] = {}
        for a in data["existing"] + data["assignments"]:
            t_ids = a.get("teacher_ids") or ([a["teacher_id"]] if a.get("teacher_id") else [])
            if teacher_id in t_ids:
                teaching_map[a["timeslot_id"]] = a.get("subject_id")

        grid = []
        for ts in data["timeslots"]:
            tid = ts["timeslot_id"]
            if tid in teaching_map:
                status = "teaching"
                subject_id = teaching_map[tid]
            elif tid in unavail_ids:
                status = "unavailable"
                subject_id = None
            else:
                status = "free"
                subject_id = None

            grid.append({
                "timeslot_id": tid,
                "day": ts["day"],
                "start_time": ts["start_time"],
                "end_time": ts["end_time"],
                "status": status,
                "subject_id": subject_id,
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

        unavail_ids = {
            u["timeslot_id"]
            for u in data["room_unavailability"]
            if u["room_id"] == room_id
        }

        teaching_map: dict[str, str | None] = {}
        for a in data["existing"] + data["assignments"]:
            if a.get("room_id") == room_id:
                teaching_map[a["timeslot_id"]] = a.get("subject_id")

        grid = []
        for ts in data["timeslots"]:
            tid = ts["timeslot_id"]
            if tid in teaching_map:
                status = "teaching"
                subject_id = teaching_map[tid]
            elif tid in unavail_ids:
                status = "unavailable"
                subject_id = None
            else:
                status = "free"
                subject_id = None

            grid.append({
                "timeslot_id": tid,
                "day": ts["day"],
                "start_time": ts["start_time"],
                "end_time": ts["end_time"],
                "status": status,
                "subject_id": subject_id,
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

    หมายเหตุ: ควรเช็คก่อน insert ว่า timeslot นี้ "สอนอยู่แล้ว" ใน timetable_ai หรือไม่
    ถ้าใช่ ควรบล็อกไม่ให้ตั้งเป็น unavailable ซ้อน (กันข้อมูลขัดแย้งกันเอง) —
    ดู TODO ด้านล่างถ้าต้องการเพิ่ม guard นี้
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
        refresh_cache()  # บังคับให้ schedule-grid เห็นข้อมูลล่าสุดทันที ไม่ใช้ cache เก่า
        return {"unavailable": False}

    supabase.table(table).insert(
        {entity_column: entity_id, "timeslot_id": body.timeslot_id}
    ).execute()
    refresh_cache()  # บังคับให้ schedule-grid เห็นข้อมูลล่าสุดทันที ไม่ใช้ cache เก่า
    return {"unavailable": True}