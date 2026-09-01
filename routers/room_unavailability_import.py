"""
นำเข้าข้อมูลห้องไม่ว่างจากภาคเรียนก่อนหน้า (switch ใน DataPage tab ห้องเรียน)
เขียนตามแพทเทิร์นเดียวกับ unavailability.py: supabase client ตรงๆ, sync function,
refresh_cache() หลัง insert/delete ทุกครั้ง

ไม่มี min_count/recent_years แล้ว เพราะ filter_rooms.py กรองข้อมูลสะอาดมาให้ตั้งแต่ต้นทาง
(old_room_unavailable_1/2 มีแต่ pattern ที่ผ่านเกณฑ์ครบทุกอย่างอยู่แล้ว)

4 endpoint ที่ ImportUnavailabilityRow.tsx เรียกใช้:
- GET    /room-unavailability/import-status?semester=1
- GET    /room-unavailability/import-preview?semester=1
- POST   /room-unavailability/import      body: { "semester": "1" }
- DELETE /room-unavailability/import      body: { "semester": "1" }

logic insert/delete/preview จริง ๆ อยู่ใน Postgres function (RPC) เพราะ supabase query builder
ทำ INSERT...JOIN...ON CONFLICT ตรงๆ ไม่ได้ — ดู rpc_functions.sql คู่กัน
สำคัญ: ต้องรัน rpc_functions.sql เวอร์ชันล่าสุด (มี DROP FUNCTION ก่อน CREATE) เพื่อล้าง
function เก่าที่ signature ต่างกันซึ่งค้างอยู่ในระบบทิ้งก่อน ไม่งั้นผลลัพธ์จะเพี้ยน
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Literal

from agent_timetable.tools.get_data import supabase
from agent_timetable.tools.scheduling.load_data import refresh_cache

router = APIRouter()

Semester = Literal["1", "2"]


class ImportUnavailabilityIn(BaseModel):
    semester: Semester


@router.get("/room-unavailability/import-status")
def get_import_status(semester: Semester = Query(...)):
    """เช็คว่าภาคเรียนนี้เคย 'ใช้ข้อมูลเดิม' ไปแล้วหรือยัง (มีแถว imported_from ตรงกันอยู่ไหม)
    ไม่พึ่ง count="exact" อย่างเดียว (บาง client version คืนค่า count ไม่ตรง) ดึงข้อมูลจริงมาเช็คด้วย"""
    try:
        result = (
            supabase.table("room_unavailability")
            .select("id", count="exact")
            .eq("imported_from", semester)
            .execute()
        )
        count = result.count if result.count is not None else len(result.data)
        return {"imported": count > 0, "count": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/room-unavailability/import-preview")
def preview_import(semester: Semester = Query(...)):
    """ไม่ insert จริง แค่บอกว่าจะได้กี่แถว ไว้โชว์ก่อน user กด confirm"""
    try:
        result = supabase.rpc(
            "preview_import_room_unavailability", {"p_semester": semester}
        ).execute()
        count = result.data if isinstance(result.data, int) else 0
        return {"would_insert": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/room-unavailability/import")
def import_unavailability(body: ImportUnavailabilityIn):
    """เรียก Postgres function import_room_unavailability(semester)
    insert เฉพาะแถวที่ยังไม่มี พร้อม tag imported_from"""
    try:
        result = supabase.rpc(
            "import_room_unavailability", {"p_semester": body.semester}
        ).execute()
        inserted = result.data if isinstance(result.data, int) else 0
        refresh_cache()
        return {"inserted": inserted}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/room-unavailability/import")
def delete_imported_unavailability(body: ImportUnavailabilityIn):
    """เรียก Postgres function delete_imported_room_unavailability(semester)
    ลบเฉพาะแถวที่ imported_from ตรงกับเทอมที่ระบุ ไม่แตะของ user เอง"""
    try:
        result = supabase.rpc(
            "delete_imported_room_unavailability", {"p_semester": body.semester}
        ).execute()
        deleted = result.data if isinstance(result.data, int) else 0
        refresh_cache()
        return {"deleted": deleted}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))