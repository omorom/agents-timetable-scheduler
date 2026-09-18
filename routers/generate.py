"""
/generate — สั่งให้ Schedule Planner Agent จัดตารางใหม่ทั้งหมด
/schedule-status — เช็คสถานะตารางปัจจุบัน (ครบ/ไม่ครบ) โดยไม่จัดใหม่
"""

from fastapi import APIRouter, HTTPException

from generate_service import run_generate
from agent_timetable.tools.scheduling.schedule_status_service import get_schedule_status

router = APIRouter()


@router.post("/generate")
async def generate_schedule():
    try:
        result = await run_generate()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/schedule-status")
def schedule_status():
    """เช็คสถานะตารางปัจจุบัน (ครบ/ไม่ครบ) โดยไม่จัดใหม่ — frontend เรียกตอนเปิด
    หน้าเว็บ/รีเฟรช เพื่อโชว์แบนเนอร์สถานะได้ทันที ไม่ต้องรอกด "สร้างตาราง" ก่อน
    """
    try:
        return get_schedule_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))