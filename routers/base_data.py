"""
ข้อมูลพื้นฐาน: ห้อง / อาจารย์ / คาบเวลา / ชั้นปี
(ย้ายมาจาก main.py หมวด 2 แบบตรงๆ ไม่มีการแก้ logic
 + เพิ่ม: เพิ่มห้องเรียน / แก้ไขความจุ+ประเภทห้อง / เพิ่มอาจารย์)
"""

import re
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent_timetable.tools.get_data import load, supabase, TABLE_MAP
from agent_timetable.tools.scheduling.load_data import refresh_cache

router = APIRouter()

# ใช้ชื่อตารางจาก TABLE_MAP ตัวเดียวกับ load() จะได้ไม่ต้องจำว่าตารางจริงชื่ออะไร
ROOM_TABLE = TABLE_MAP["rooms"]
TEACHER_TABLE = TABLE_MAP["teachers"]


class UpdateGroupIn(BaseModel):
    total_students: Optional[int] = None
    group_name: Optional[str] = None


class CreateRoomIn(BaseModel):
    room_name: str
    room_type: Literal["LECTURE", "LAB"]
    capacity: int


class UpdateRoomIn(BaseModel):
    room_type: Optional[Literal["LECTURE", "LAB"]] = None
    capacity: Optional[int] = None


class CreateTeacherIn(BaseModel):
    teacher_name: str


@router.get("/rooms")
def get_rooms():
    try:
        return load("rooms")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rooms")
def create_room(body: CreateRoomIn):
    name = body.room_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="กรุณากรอกรหัสห้อง")
    if body.capacity <= 0:
        raise HTTPException(status_code=400, detail="ความจุต้องมากกว่า 0")

    try:
        rooms = load("rooms")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # กันห้องซ้ำ (ไม่สนตัวพิมพ์เล็ก/ใหญ่ เช่น sc1-212 กับ SC1-212 ถือว่าห้องเดียวกัน)
    if any((r.get("room_name") or "").strip().lower() == name.lower() for r in rooms):
        raise HTTPException(status_code=409, detail=f"มีห้อง {name} อยู่ในระบบแล้ว")

    row = {"room_name": name, "room_type": body.room_type, "capacity": body.capacity}
    created = _insert_with_id(ROOM_TABLE, "room_id", row, [r.get("room_id") for r in rooms])
    refresh_cache()
    return created


@router.patch("/rooms/{room_id}")
def update_room(room_id: str, body: UpdateRoomIn):
    update_data = {}
    if body.capacity is not None:
        if body.capacity <= 0:
            raise HTTPException(status_code=400, detail="ความจุต้องมากกว่า 0")
        update_data["capacity"] = body.capacity
    if body.room_type is not None:
        update_data["room_type"] = body.room_type

    if not update_data:
        raise HTTPException(status_code=400, detail="ไม่มีข้อมูลให้แก้ไข")

    try:
        result = supabase.table(ROOM_TABLE).update(update_data).eq("room_id", room_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not result.data:
        raise HTTPException(status_code=404, detail="ไม่พบห้องนี้")
    refresh_cache()
    return result.data[0]


@router.get("/teachers")
def get_teachers():
    try:
        return load("teachers")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/teachers")
def create_teacher(body: CreateTeacherIn):
    # ตัดช่องว่างซ้ำกลางชื่อด้วย เช่น "ผศ.  สมชาย" -> "ผศ. สมชาย"
    name = re.sub(r"\s+", " ", body.teacher_name).strip()
    if not name:
        raise HTTPException(status_code=400, detail="กรุณากรอกชื่ออาจารย์")

    try:
        teachers = load("teachers")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if any(re.sub(r"\s+", " ", t.get("teacher_name") or "").strip() == name for t in teachers):
        raise HTTPException(status_code=409, detail=f"มีอาจารย์ชื่อ {name} อยู่ในระบบแล้ว")

    created = _insert_with_id(
        TEACHER_TABLE, "teacher_id", {"teacher_name": name}, [t.get("teacher_id") for t in teachers]
    )
    refresh_cache()
    return created


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


# --- helper ---------------------------------------------------------------

def _next_id(existing_ids: list) -> str | int:
    """สร้าง id ถัดไปจาก id ที่มีอยู่ รองรับ 2 แบบ
    - ตัวเลขล้วน (1, 2, 3) -> max + 1
    - ตัวอักษรนำหน้า + เลข (T001, T002) -> เลขถัดไป ความยาวเท่าเดิม
    """
    ids = [i for i in existing_ids if i is not None]
    if not ids:
        return 1

    if all(isinstance(i, int) or str(i).isdigit() for i in ids):
        return max(int(i) for i in ids) + 1

    best_prefix, best_num, width = "", 0, 0
    for i in ids:
        m = re.match(r"^(.*?)(\d+)$", str(i))
        if m and int(m.group(2)) >= best_num:
            best_prefix, best_num, width = m.group(1), int(m.group(2)), len(m.group(2))
    if width == 0:
        raise HTTPException(status_code=500, detail="สร้างรหัสใหม่อัตโนมัติไม่ได้ รูปแบบรหัสเดิมไม่รองรับ")
    return f"{best_prefix}{str(best_num + 1).zfill(width)}"


def _insert_with_id(table: str, id_column: str, row: dict, existing_ids: list) -> dict:
    """เพิ่มแถวใหม่ ลองให้ฐานข้อมูลสร้าง id เองก่อน (กรณีคอลัมน์เป็น auto/serial)
    ถ้าไม่ได้ (คอลัมน์ id ไม่มีค่าเริ่มต้น) ค่อยสร้าง id ต่อจากของเดิมแล้วใส่เอง
    """
    try:
        result = supabase.table(table).insert(row).execute()
    except Exception:
        try:
            result = (
                supabase.table(table)
                .insert({id_column: _next_id(existing_ids), **row})
                .execute()
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    if not result.data:
        raise HTTPException(status_code=500, detail="บันทึกไม่สำเร็จ")
    return result.data[0]