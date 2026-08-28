"""
/generate — สั่งให้ Schedule Planner Agent จัดตารางใหม่ทั้งหมด
"""

from fastapi import APIRouter, HTTPException

from generate_service import run_generate

router = APIRouter()


@router.post("/generate")
async def generate_schedule():
    try:
        result = await run_generate()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))