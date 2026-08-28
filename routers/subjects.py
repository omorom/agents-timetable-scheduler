"""
วิชา (master data)
(ย้ายมาจาก main.py หมวด 3 แบบตรงๆ ไม่มีการแก้ logic)
"""

from fastapi import APIRouter, HTTPException

from agent_timetable.tools.get_data import supabase

router = APIRouter()


@router.get("/subjects")
def get_subjects(subject_type: str | None = None, search: str | None = None):
    try:
        query = supabase.table("subjects").select("*")
        if subject_type:
            query = query.eq("subject_type", subject_type)
        rows = query.execute().data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if search:
        keyword = search.strip().lower()
        rows = [
            r for r in rows
            if keyword in r.get("subject_id", "").lower()
            or keyword in (r.get("name_thai") or "").lower()
            or keyword in (r.get("name_english") or "").lower()
        ]
    return rows