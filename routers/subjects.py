"""
วิชา (master data)
- GET  /subjects : ดึงรายวิชาทั้งหมด (กรองตามประเภท / ค้นหาได้)
- POST /subjects : สร้างรายวิชาใหม่ลงคลังรายวิชา (ใช้จาก modal "เพิ่มรายวิชาที่เปิดสอน")
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent_timetable.tools.get_data import supabase

router = APIRouter()

VALID_SUBJECT_TYPES = ("GENERAL", "CORE", "ELECTIVE")


class SubjectIn(BaseModel):
    subject_id: str
    name_thai: str
    name_english: str | None = None
    description_thai: str | None = None
    description_english: str | None = None
    group_id: str | None = None  # null = ไม่ผูกชั้นปีตายตัว (เลือกชั้นปีตอนเปิดสอน)
    subject_type: str  # GENERAL / CORE / ELECTIVE
    semester: int | None = None
    lecture_hours: int | None = None  # GENERAL เก็บเป็น NULL (กำหนดคาบเองตอนเปิดสอน)
    lab_hours: int | None = None


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


@router.post("/subjects", status_code=201)
def create_subject(body: SubjectIn):
    subject_id = body.subject_id.strip()
    name_thai = body.name_thai.strip()

    # ── validation ──
    if not subject_id or not name_thai:
        raise HTTPException(status_code=400, detail="กรุณากรอกรหัสวิชาและชื่อวิชา")
    if body.subject_type not in VALID_SUBJECT_TYPES:
        raise HTTPException(status_code=400, detail="ประเภทวิชาไม่ถูกต้อง")
    lecture = body.lecture_hours or 0
    lab = body.lab_hours or 0
    if lecture < 0 or lab < 0:
        raise HTTPException(status_code=400, detail="จำนวนชั่วโมงต้องไม่ติดลบ")
    # วิชาศึกษาทั่วไปไม่บังคับชั่วโมง (ข้อมูลเดิมเป็น NULL) ส่วนวิชาอื่นต้องมีอย่างน้อย 1 ชั่วโมง
    if body.subject_type != "GENERAL" and lecture + lab <= 0:
        raise HTTPException(status_code=400, detail="ต้องมีชั่วโมงบรรยายหรือปฏิบัติอย่างน้อย 1 ชั่วโมง")
    if body.semester is not None and body.semester not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="ภาคเรียนไม่ถูกต้อง")

    try:
        # กันรหัสวิชาซ้ำ
        exists = (
            supabase.table("subjects")
            .select("subject_id")
            .eq("subject_id", subject_id)
            .execute()
            .data
        )
        if exists:
            raise HTTPException(status_code=409, detail="รหัสวิชานี้มีอยู่แล้ว")

        # กัน group_id ที่ไม่มีอยู่จริง (ถ้ามีส่งมา)
        if body.group_id:
            group = (
                supabase.table("student_group")
                .select("group_id")
                .eq("group_id", body.group_id)
                .execute()
                .data
            )
            if not group:
                raise HTTPException(status_code=400, detail="ไม่พบชั้นปีที่เลือก")

        data = body.model_dump()
        data["subject_id"] = subject_id
        data["name_thai"] = name_thai
        result = supabase.table("subjects").insert(data).execute()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not result.data:
        raise HTTPException(status_code=500, detail="สร้างรายวิชาไม่สำเร็จ")
    return result.data[0]