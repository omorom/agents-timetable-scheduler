"""
ข้อมูลพื้นฐาน: ห้อง / อาจารย์ / คาบเวลา / ชั้นปี
(ย้ายมาจาก main.py หมวด 2 แบบตรงๆ ไม่มีการแก้ logic)
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent_timetable.tools.get_data import load, supabase

router = APIRouter()


class UpdateGroupIn(BaseModel):
    total_students: Optional[int] = None
    group_name: Optional[str] = None


@router.get("/rooms")
def get_rooms():
    try:
        return load("rooms")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/teachers")
def get_teachers():
    try:
        return load("teachers")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/timeslots")
def get_timeslots():
    try:
        return load("timeslots")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/groups")
def get_groups():
    try:
        return load("groups")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/groups/{group_id}")
def update_group(group_id: str, body: UpdateGroupIn):
    if body.total_students is not None and body.total_students < 0:
        raise HTTPException(status_code=400, detail="จำนวนนิสิตต้องไม่ติดลบ")

    if body.group_name is not None and not body.group_name.strip():
        raise HTTPException(status_code=400, detail="ชื่อชั้นปีต้องไม่ว่าง")

    update_data = {}
    if body.total_students is not None:
        update_data["total_students"] = body.total_students
    if body.group_name is not None:
        update_data["group_name"] = body.group_name.strip()

    if not update_data:
        raise HTTPException(status_code=400, detail="ไม่มีข้อมูลให้แก้ไข")

    try:
        result = (
            supabase.table("student_group")
            .update(update_data)
            .eq("group_id", group_id)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not result.data:
        raise HTTPException(status_code=404, detail="ไม่พบชั้นปีนี้")
    return result.data[0]