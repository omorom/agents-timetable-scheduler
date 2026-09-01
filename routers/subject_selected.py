"""
การเปิดสอนวิชา (subject_selected) + validation helpers
(ย้ายมาจาก main.py หมวด 4 แบบตรงๆ ไม่มีการแก้ logic)

หมายเหตุ (สำคัญ): 1 section (`subject_selected`) ผูกกับอาจารย์ได้ "หลายคน" ผ่านตารางเชื่อม
`subject_selected_teachers` แทนที่จะใช้คอลัมน์ `subject_selected.teacher_id` แบบเดิม (เดี่ยว)
เก็บกรณี "อาจารย์สอนพร้อมกันในเซคเดียวกัน" ได้แล้ว ส่วนกรณี "แยกเซคคนละอาจารย์" ยังคงใช้
`subject_selected` คนละแถวเหมือนเดิม

เพิ่มเติม: `is_lecture_combined` — บอกว่า section นี้ "เรียน LECTURE รวมกับ section อื่นของวิชา/
ชั้นปี/ปีการศึกษาเดียวกัน" หรือไม่ (true ทุก section ที่ตั้งใจรวมกัน) เก็บไว้ที่
`subject_selected_groups.is_lecture_combined` เพราะเป็นคุณสมบัติของ "การเปิดสอนให้กลุ่มนี้"
ไม่ใช่ของตัววิชาเอง ค่า default คือ false (ไม่รวม)

แก้ไขล่าสุด (สำคัญ): เพิ่ม `lecture_combine_group` — เดิมมีแค่ is_lecture_combined (true/false
เดี่ยวๆ) ซึ่งไม่พอบอกว่า "รวมกับ section ไหนกันแน่" พอวิชาหนึ่งมีหลายกลุ่มของการรวมพร้อมกัน
(เช่น section CS-Y1×2 อยากรวมกันเอง และ section IT-Y1×2 อยากรวมกันเองแยกต่างหาก ไม่ใช่รวม
ข้าม CS/IT) ระบบ scheduling (section_logic.py) แยกไม่ออกว่า is_lecture_combined=true ของ
ทุก section หมายถึง "รวมเป็นก้อนเดียวกันหมด" หรือ "รวมกันเป็นกลุ่มย่อยๆ คนละกลุ่ม"

lecture_combine_group เป็น text ที่ผู้ใช้ตั้งเอง (หรือ frontend generate ให้) — section
ไหนก็ตามที่มีค่า lecture_combine_group "เดียวกัน" (ไม่ใช่ null) ถือว่าตั้งใจรวม LECTURE
เข้าด้วยกันจริง ไม่ว่า group_ids จะต่างกันแค่ไหนก็ตาม ส่วน section ที่ไม่ได้ตั้งใจรวมกับใคร
ปล่อยเป็น null ไว้ (ค่า default) — แนะนำให้ frontend ใช้ subject_selected_id ของ section
แรกสุดในกลุ่มเป็นค่านี้ไปเลย ง่ายสุด ไม่ต้อง generate UUID ใหม่ (ดู field ด้านล่าง)
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent_timetable.tools.get_data import load_subject_selected_full, supabase

router = APIRouter()


class SubjectSelectedIn(BaseModel):
    subject_id: str
    teacher_ids: list[str] | None = None  # รองรับหลายคนต่อ section
    max_capacity: int | None = None
    academic_year: int

    # ใช้เฉพาะเมื่อ subjects.group_id เป็น null (วิชาไม่ผูกชั้นปีตายตัว)
    group_ids: list[str] | None = None

    # ใช้เฉพาะวิชา subject_type = GENERAL เท่านั้น
    # หมายเหตุ: คาบที่ต้องการของ GENERAL คือ "การล็อกจริง" ไม่ใช่แค่ความชอบให้ AI พิจารณา
    study_date: str | None = None
    preferred_timeslot_ids: list[int] | None = None

    # section นี้เรียน LECTURE รวมกับ section อื่นของวิชา/ชั้นปี/ปีการศึกษาเดียวกันไหม
    # มีความหมายก็ต่อเมื่อวิชานั้นถูกเปิดมากกว่า 1 section เท่านั้น (frontend เป็นคนคุม default = false)
    # เก็บไว้เพื่อ backward-compat กับโค้ดเก่า — ตัวชี้ขาดจริงตอนนี้คือ lecture_combine_group
    # ด้านล่าง (ดูว่าทำไม is_lecture_combined เดี่ยวๆ ไม่พอ ในหัวไฟล์ด้านบน)
    is_lecture_combined: bool = False

    # ระบุว่า section นี้รวม LECTURE กับ section ไหนบ้าง — section ที่มีค่านี้ "เหมือนกัน"
    # (ไม่ใช่ None) ทั้งหมดจะถูกมองว่าเป็นกลุ่มเดียวกันตอนจัดตาราง แนะนำให้ frontend ส่ง
    # ค่าเป็น subject_selected_id ของ section แรกสุดในกลุ่มที่กำลังแก้ไข (string) ให้ทุก
    # section ในฟอร์มเดียวกันใช้ค่าเดียวกันหมด — None = ไม่รวมกับใคร (ค่า default ปกติ)
    lecture_combine_group: str | None = None

    # ห้อง LAB ที่บังคับใช้ตายตัว (เช่น ห้องที่มีอุปกรณ์เฉพาะ) — None = ไม่ล็อก
    # ให้ระบบเลือกอัตโนมัติตามปกติ ใช้ได้เฉพาะวิชาที่มี LAB เท่านั้น
    fixed_room_id: str | None = None


@router.get("/subject-selected")
def get_subject_selected(academic_year: int | None = None):
    try:
        return load_subject_selected_full(academic_year=academic_year)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/subject-selected")
def create_subject_selected(body: SubjectSelectedIn):
    try:
        subject = _get_subject_or_404(body.subject_id)
        group_ids = _resolve_group_ids(subject, body.group_ids)
        teacher_ids = _clean_teacher_ids(body.teacher_ids)

        _validate_general_only_fields(subject, body)
        _check_no_duplicate(body.subject_id, group_ids, body.academic_year, teacher_ids)
        _check_no_timeslot_conflict(group_ids, body.academic_year, body.preferred_timeslot_ids)

        subject_selected_id = _insert_subject_selected(body)
        _insert_subject_selected_groups(subject_selected_id, group_ids, body.is_lecture_combined)
        _insert_subject_selected_teachers(subject_selected_id, teacher_ids)
        _insert_preferred_timeslots(subject_selected_id, body.preferred_timeslot_ids)

        return _fetch_subject_selected_full(subject_selected_id)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/subject-selected/{subject_selected_id}")
def update_subject_selected(subject_selected_id: int, body: SubjectSelectedIn):
    try:
        _get_subject_selected_or_404(subject_selected_id)

        subject = _get_subject_or_404(body.subject_id)
        group_ids = _resolve_group_ids(subject, body.group_ids)
        teacher_ids = _clean_teacher_ids(body.teacher_ids)

        _validate_general_only_fields(subject, body)
        _check_no_duplicate(
            body.subject_id, group_ids, body.academic_year, teacher_ids, exclude_id=subject_selected_id
        )
        _check_no_timeslot_conflict(
            group_ids, body.academic_year, body.preferred_timeslot_ids, exclude_id=subject_selected_id
        )

        _update_subject_selected_core(subject_selected_id, body)
        _replace_subject_selected_groups(subject_selected_id, group_ids, body.is_lecture_combined)
        _replace_subject_selected_teachers(subject_selected_id, teacher_ids)
        _replace_preferred_timeslots(subject_selected_id, body.preferred_timeslot_ids)

        return _fetch_subject_selected_full(subject_selected_id)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/subject-selected/{subject_selected_id}")
def delete_subject_selected(subject_selected_id: int):
    try:
        # ลบตารางลูกก่อน กัน FK constraint (เผื่อไม่มี on delete cascade)
        supabase.table("subject_selected_groups").delete().eq(
            "subject_selected_id", subject_selected_id
        ).execute()
        supabase.table("subject_selected_teachers").delete().eq(
            "subject_selected_id", subject_selected_id
        ).execute()

        result = (
            supabase.table("subject_selected")
            .delete()
            .eq("id", subject_selected_id)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not result.data:
        raise HTTPException(status_code=404, detail="ไม่พบรายการนี้")
    return {"deleted": True}


# --- helper functions สำหรับ subject_selected (create / update ใช้ร่วมกัน) -------------

def _get_subject_or_404(subject_id: str) -> dict:
    result = supabase.table("subjects").select("*").eq("subject_id", subject_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="ไม่พบวิชานี้")
    return result.data[0]


def _get_subject_selected_or_404(subject_selected_id: int) -> dict:
    result = supabase.table("subject_selected").select("*").eq("id", subject_selected_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="ไม่พบรายการนี้")
    return result.data[0]


def _clean_teacher_ids(teacher_ids: list[str] | None) -> list[str]:
    """ตัดค่าว่าง/ซ้ำออก เผื่อ frontend ส่ง [''] หรือใส่อาจารย์คนเดียวกันซ้ำมาใน section เดียวกัน"""
    if not teacher_ids:
        return []
    seen: list[str] = []
    for t in teacher_ids:
        if t and t not in seen:
            seen.append(t)
    return seen


def _resolve_group_ids(subject: dict, group_ids_from_request: list[str] | None) -> list[str]:
    """ถ้าวิชาผูก group_id ตายตัวอยู่แล้ว ใช้ค่านั้นเท่านั้น (ไม่ยอมให้ override)
    ถ้าวิชาไม่ผูกปี (group_id เป็น null) ต้องให้ผู้เรียกส่ง group_ids มาเอง
    """
    if subject.get("group_id") is not None:
        return [subject["group_id"]]

    if not group_ids_from_request:
        raise HTTPException(
            status_code=400,
            detail="วิชานี้ไม่มีชั้นปีกำหนดไว้ตายตัว ต้องระบุ group_ids เอง",
        )
    return group_ids_from_request


def _validate_general_only_fields(subject: dict, body: SubjectSelectedIn) -> None:
    is_general = subject["subject_type"] == "GENERAL"
    if not is_general and (body.study_date or body.preferred_timeslot_ids):
        raise HTTPException(
            status_code=400,
            detail="study_date และ preferred_timeslot_ids ใช้ได้เฉพาะวิชา GENERAL เท่านั้น",
        )


def _check_no_duplicate(
    subject_id: str,
    group_ids: list[str],
    academic_year: int,
    teacher_ids: list[str],
    exclude_id: int | None = None,
) -> None:
    """กันไม่ให้ section ซ้ำเป๊ะ (วิชาเดียวกัน + ชั้นปีเดียวกัน + ชุดอาจารย์เดียวกัน + ปีการศึกษาเดียวกัน)
    แต่ยอมให้เปิดหลาย section ได้ ถ้าอาจารย์คนละคน/ชุดคนละชุด (เช่น section 1 อ.A, section 2 อ.B)
    เทียบแบบ "ชุดอาจารย์เดียวกันเป๊ะ" (set เท่ากัน) ไม่ใช่แค่มีคนซ้ำกันบางส่วน
    """
    rows = (
        supabase.table("subject_selected")
        .select("id, subject_selected_groups(group_id), subject_selected_teachers(teacher_id)")
        .eq("subject_id", subject_id)
        .eq("academic_year", academic_year)
        .execute()
        .data
    )

    requested_teacher_set = set(teacher_ids)

    for row in rows:
        if exclude_id is not None and row["id"] == exclude_id:
            continue
        existing_groups = {g["group_id"] for g in (row.get("subject_selected_groups") or [])}
        overlap = existing_groups & set(group_ids)
        if not overlap:
            continue
        existing_teacher_set = {t["teacher_id"] for t in (row.get("subject_selected_teachers") or [])}
        if existing_teacher_set == requested_teacher_set:
            raise HTTPException(
                status_code=400,
                detail=f"วิชานี้เปิดสอนให้ชั้นปี {', '.join(sorted(overlap))} โดยอาจารย์ชุดเดียวกันไปแล้วในปีการศึกษา {academic_year}",
            )


def _check_no_timeslot_conflict(
    group_ids: list[str],
    academic_year: int,
    timeslot_ids: list[int] | None,
    exclude_id: int | None = None,
) -> None:
    """กันไม่ให้วิชา GENERAL 2 วิชา ล็อกคาบเดียวกันซ้ำให้ชั้นปีเดียวกัน ในปีการศึกษาเดียวกัน"""
    if not timeslot_ids:
        return

    rows = (
        supabase.table("subject_selected")
        .select(
            "id, subjects(name_thai), "
            "subject_selected_groups(group_id), "
            "subject_selected_preferred_timeslots(timeslot_id)"
        )
        .eq("academic_year", academic_year)
        .execute()
        .data
    )

    for row in rows:
        if exclude_id is not None and row["id"] == exclude_id:
            continue

        other_groups = {g["group_id"] for g in (row.get("subject_selected_groups") or [])}
        if not (other_groups & set(group_ids)):
            continue

        other_timeslots = {t["timeslot_id"] for t in (row.get("subject_selected_preferred_timeslots") or [])}
        overlap = other_timeslots & set(timeslot_ids)
        if overlap:
            subject_name = (row.get("subjects") or {}).get("name_thai", "วิชาอื่น")
            raise HTTPException(
                status_code=400,
                detail=f"คาบนี้ถูกล็อกไว้แล้วโดยวิชา '{subject_name}' สำหรับชั้นปีเดียวกันในปีการศึกษานี้",
            )


def _insert_subject_selected(body: SubjectSelectedIn) -> int:
    result = (
        supabase.table("subject_selected")
        .insert(
            {
                "subject_id": body.subject_id,
                "study_date": body.study_date,
                "max_capacity": body.max_capacity,
                "academic_year": body.academic_year,
                "status": "active",
                "fixed_room_id": body.fixed_room_id,
                "lecture_combine_group": body.lecture_combine_group,
            }
        )
        .execute()
    )
    return result.data[0]["id"]


def _update_subject_selected_core(subject_selected_id: int, body: SubjectSelectedIn) -> None:
    supabase.table("subject_selected").update(
        {
            "study_date": body.study_date,
            "max_capacity": body.max_capacity,
            "academic_year": body.academic_year,
            "fixed_room_id": body.fixed_room_id,
            "lecture_combine_group": body.lecture_combine_group,
        }
    ).eq("id", subject_selected_id).execute()


def _insert_subject_selected_groups(
    subject_selected_id: int, group_ids: list[str], is_lecture_combined: bool = False
) -> None:
    supabase.table("subject_selected_groups").insert(
        [
            {
                "subject_selected_id": subject_selected_id,
                "group_id": g,
                "is_lecture_combined": is_lecture_combined,
            }
            for g in group_ids
        ]
    ).execute()


def _replace_subject_selected_groups(
    subject_selected_id: int, group_ids: list[str], is_lecture_combined: bool = False
) -> None:
    """ลบของเดิมทิ้งแล้วใส่ใหม่ทั้งชุด — ง่ายกว่า diff ทีละรายการตอนแก้ไข"""
    supabase.table("subject_selected_groups").delete().eq(
        "subject_selected_id", subject_selected_id
    ).execute()
    _insert_subject_selected_groups(subject_selected_id, group_ids, is_lecture_combined)


def _insert_subject_selected_teachers(subject_selected_id: int, teacher_ids: list[str]) -> None:
    """1 section อาจมีอาจารย์ได้หลายคน (สอนพร้อมกันในเซคเดียวกัน) — insert ทีละคนลงตารางเชื่อม"""
    if not teacher_ids:
        return
    supabase.table("subject_selected_teachers").insert(
        [{"subject_selected_id": subject_selected_id, "teacher_id": t} for t in teacher_ids]
    ).execute()


def _replace_subject_selected_teachers(subject_selected_id: int, teacher_ids: list[str]) -> None:
    """ลบของเดิมทิ้งแล้วใส่ใหม่ทั้งชุด — ง่ายกว่า diff ทีละรายการตอนแก้ไข"""
    supabase.table("subject_selected_teachers").delete().eq(
        "subject_selected_id", subject_selected_id
    ).execute()
    _insert_subject_selected_teachers(subject_selected_id, teacher_ids)


def _insert_preferred_timeslots(subject_selected_id: int, timeslot_ids: list[int] | None) -> None:
    if not timeslot_ids:
        return
    supabase.table("subject_selected_preferred_timeslots").insert(
        [{"subject_selected_id": subject_selected_id, "timeslot_id": ts} for ts in timeslot_ids]
    ).execute()


def _replace_preferred_timeslots(subject_selected_id: int, timeslot_ids: list[int] | None) -> None:
    """ลบของเดิมทิ้งแล้วใส่ใหม่ทั้งชุด — ง่ายกว่า diff ทีละรายการตอนแก้ไข"""
    supabase.table("subject_selected_preferred_timeslots").delete().eq(
        "subject_selected_id", subject_selected_id
    ).execute()
    _insert_preferred_timeslots(subject_selected_id, timeslot_ids)


def _fetch_subject_selected_full(subject_selected_id: int) -> dict:
    """ดึงข้อมูลกลับมาแบบ join ครบ ให้ frontend ใช้ต่อได้เลยหลังสร้าง/แก้ไขเสร็จ
    teachers ถูก join ผ่าน subject_selected_teachers -> teacher แล้วแปลงเป็น list เดียวให้ frontend ใช้ตรง ๆ
    is_lecture_combined ดึงมาจาก subject_selected_groups แถวแรก (ทุกแถวของ section เดียวกันมีค่าเดียวกันอยู่แล้ว
    เพราะ insert/replace ใส่ค่าเดียวกันทุกแถวเสมอ)
    lecture_combine_group ดึงตรงๆ จาก subject_selected เอง (ไม่ต้อง join เพราะ column อยู่แถวเดียวกัน)
    """
    result = (
        supabase.table("subject_selected")
        .select(
            "*, subjects(*), subject_selected_groups(group_id, is_lecture_combined), "
            "subject_selected_preferred_timeslots(timeslot_id), "
            "subject_selected_teachers(teacher(teacher_id, teacher_name))"
        )
        .eq("id", subject_selected_id)
        .execute()
    )
    row = result.data[0]
    row["teachers"] = [
        st["teacher"] for st in (row.pop("subject_selected_teachers", None) or []) if st.get("teacher")
    ]
    groups = row.get("subject_selected_groups") or []
    row["is_lecture_combined"] = groups[0]["is_lecture_combined"] if groups else False
    return row