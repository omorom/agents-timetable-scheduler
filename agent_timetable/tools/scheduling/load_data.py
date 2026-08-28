"""
load_data.py
ดึงข้อมูลสำหรับ pipeline จัดตารางจาก Supabase โดยตรง (แทนที่ของเดิมที่อ่านจากไฟล์ JSON local)

เปลี่ยนหน่วยหลักจาก "subject" (แบบ demo เดิม ที่มี teacher_id/group_id เดี่ยว)
เป็น "section" (= subject_selected 1 แถว) เพื่อรองรับ 1 section มีได้หลายอาจารย์/หลายกลุ่ม
ตามโครงสร้างจริงของระบบ (subject_selected_teachers, subject_selected_groups)

หมายเหตุสำคัญ: วิชา GENERAL ไม่มีอาจารย์ + คาบที่ล็อกไว้ (preferred_timeslots) คือ hard lock
ไม่ต้องเอามาจัดใหม่ — ใส่ไว้ใน "existing" ให้ระบบรู้ว่าคาบนั้นถูกจองแล้ว
"""

from agent_timetable.tools.get_data import supabase, load


def _load_sections() -> list[dict]:
    """ดึง subject_selected ทุกแถวของวิชาสาขา/เสรี (ไม่รวม GENERAL) พร้อม teacher_ids, group_ids
    แต่ละแถว = 1 section ที่ต้องจัดตาราง (มีอาจารย์ผูกไว้แล้ว ผ่านหน้าจัดการรายวิชา)
    """
    rows = (
        supabase.table("subject_selected")
        .select(
            "id, subject_id, academic_year, max_capacity, fixed_room_id, "
            "subjects(subject_id, name_thai, name_english, subject_type, lecture_hours, lab_hours), "
            "subject_selected_teachers(teacher_id), "
            "subject_selected_groups(group_id, is_lecture_combined)"
        )
        .execute()
        .data
    )

    sections = []
    for r in rows:
        subject = r.get("subjects") or {}
        if subject.get("subject_type") == "GENERAL":
            continue  # GENERAL ไม่ต้องจัดใหม่ ถูกล็อกไว้แล้วใน _load_existing()

        groups = r.get("subject_selected_groups") or []
        # ทุกแถวของ section เดียวกันมีค่า is_lecture_combined เท่ากันเสมอ (insert ใส่ค่า
        # เดียวกันทุกแถวตอนบันทึกจากฟอร์ม) เอาแถวแรกพอ ถ้าไม่มี group เลยถือว่า false
        is_lecture_combined = bool(groups[0]["is_lecture_combined"]) if groups else False

        sections.append({
            "subject_selected_id": r["id"],
            "subject_id": r["subject_id"],
            "academic_year": r["academic_year"],
            "max_capacity": r.get("max_capacity"),
            # ห้องที่บังคับใช้ตายตัว (เฉพาะ LAB) — None = ไม่ล็อก ให้ระบบเลือกอัตโนมัติ
            "fixed_room_id": r.get("fixed_room_id"),
            # ตั้งใจให้ LECTURE ของ section นี้รวมห้องเดียวกับ parallel section อื่นไหม
            # (มีผลก็ต่อเมื่อเป็น parallel group เท่านั้น — ดู section_logic.py)
            "is_lecture_combined": is_lecture_combined,
            "name_english": subject.get("name_english") or subject.get("name_thai") or r["subject_id"],
            "lecture_hours": subject.get("lecture_hours") or 0,
            "lab_hours": subject.get("lab_hours") or 0,
            "teacher_ids": [t["teacher_id"] for t in (r.get("subject_selected_teachers") or [])],
            "group_ids": [g["group_id"] for g in groups],
        })

    return sections


def _load_existing() -> list[dict]:
    """คาบที่ถูกล็อกไว้แล้ว (วิชา GENERAL ที่ล็อก preferred_timeslots) — ห้ามจัดทับ
    คืนรูปแบบเดียวกับ assignment ปกติ (ไม่มี session_id เพราะไม่ใช่ session ที่ AI จัด)
    """
    rows = (
        supabase.table("subject_selected_preferred_timeslots")
        .select(
            "timeslot_id, "
            "subject_selected(subject_id, subjects(subject_type), "
            "subject_selected_groups(group_id))"
        )
        .execute()
        .data
    )

    existing = []
    for r in rows:
        section = r.get("subject_selected") or {}
        subject = section.get("subjects") or {}
        if subject.get("subject_type") != "GENERAL":
            continue  # กันเผื่อ ป้องกันดึงคาบของวิชาอื่นที่ไม่ใช่ GENERAL มาปนโดยไม่ตั้งใจ

        groups = section.get("subject_selected_groups") or []
        for g in groups:
            existing.append({
                "subject_id": section.get("subject_id"),
                "teacher_id": None,  # GENERAL ไม่มีอาจารย์
                "room_id": None,     # ไม่ผูกห้องตายตัว (ถ้าต้องผูกห้อง ต้องเพิ่ม logic เพิ่ม)
                "timeslot_id": str(r["timeslot_id"]),
                "group_id": g["group_id"],
            })

    return existing


def _load_ai_schedule() -> list[dict]:
    """ตารางที่ AI จัดไว้แล้ว (ผลลัพธ์ล่าสุด) จากตาราง timetable_ai"""
    return load("timetable")


def _load_unavailability() -> tuple[list[dict], list[dict]]:
    """คืน (teacher_unavailability, room_unavailability) ตรงๆ จาก Supabase"""
    teacher_unavail = load("teacher_unavailability")
    room_unavail = load("room_unavailability")
    return teacher_unavail, room_unavail


def load_all() -> dict:
    """รวมข้อมูลทุกอย่างที่ pipeline จัดตารางต้องใช้ ดึงจาก Supabase สดทุกครั้งที่เรียก"""
    teacher_unavail, room_unavail = _load_unavailability()

    return {
        "rooms": load("rooms"),
        "timeslots": load("timeslots"),
        "subjects": load("subjects"),
        "teachers": load("teachers"),
        "groups": load("groups"),
        "sections": _load_sections(),
        "existing": _load_existing(),
        "assignments": _load_ai_schedule(),
        "teacher_unavailability": teacher_unavail,
        "room_unavailability": room_unavail,
    }


# ═════════════════════════════════════════════════════════════════════════
# Cache แบบ "รีเฟรชตอนเริ่มรอบจัดตารางทุกครั้ง" (ไม่ใช่โหลดครั้งเดียวตอน import)
#
# ปัญหาที่ต้องป้องกัน: ถ้าไฟล์อื่น (section_logic.py, candidate_scorer.py, ...)
# เขียน `data = load_all()` ที่ module-level เหมือน demo เดิม ข้อมูลจะถูกดึงจาก
# Supabase แค่ "ครั้งเดียว" ตอน Python import ไฟล์นั้นครั้งแรก แล้วค้างอยู่แบบนั้น
# ตลอดอายุของ server process — ถ้ามีคนแก้ไขข้อมูล (เช่น ตั้ง teacher_unavailability
# ใหม่ผ่านแชท) หลัง server เปิดมาแล้ว การจัดตารางรอบถัดไปจะไม่เห็นข้อมูลใหม่เลย
#
# วิธีแก้: ทุกไฟล์เรียก get_cached_data() แทน load_all() ตรงๆ — ค่าจะถูก cache ไว้
# ใน process เดียวกัน แต่ "รีเฟรชใหม่ทุกครั้ง" ที่เริ่มรอบจัดตาราง (เรียก refresh_cache()
# ที่จุดเริ่มต้นของ gather_context()/assign_schedule() ใน agent.py)
# ═════════════════════════════════════════════════════════════════════════

_cache: dict | None = None


def get_cached_data() -> dict:
    """คืนข้อมูล cache ปัจจุบัน ถ้ายังไม่เคยโหลดเลยจะโหลดให้ครั้งแรกอัตโนมัติ"""
    global _cache
    if _cache is None:
        _cache = load_all()
    return _cache


def refresh_cache() -> dict:
    """บังคับดึงข้อมูลใหม่จาก Supabase ทันที — เรียกทุกครั้งตอนเริ่มรอบจัดตาราง"""
    global _cache
    _cache = load_all()
    return _cache