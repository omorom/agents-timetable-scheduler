"""
/check-data      — ตรวจความพร้อมของข้อมูลก่อนจัด (DataGatherAgent + DataReviewAgent)
/generate        — สั่ง agent จัดตารางใหม่ทั้งหมด (ส่ง check_session_id มาได้ เพื่อใช้ผลตรวจจาก /check-data ต่อ)
/schedule-status — เช็คสถานะตารางปัจจุบัน (ครบ/ไม่ครบ) โดยไม่จัดใหม่
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from generate_service import run_generate
from data_check_service import run_check_data
from agent_timetable.tools.scheduling.schedule_status_service import get_schedule_status

router = APIRouter()


class GenerateBody(BaseModel):
    check_session_id: str | None = None


@router.get("/check-data")
async def check_data():
    try:
        return await run_check_data()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate")
async def generate_schedule(body: GenerateBody | None = None):
    try:
        return await run_generate(body.check_session_id if body else None)
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