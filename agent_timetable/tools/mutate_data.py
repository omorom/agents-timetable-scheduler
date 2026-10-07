"""
mutate_data.py
Tool สำหรับให้ Agent "แก้ไขข้อมูล" (เขียนลง Supabase) เท่านั้น
แยกจาก get_data.py (อ่านข้อมูลดิบทั้งตาราง) และ query_data.py (อ่านข้อมูลเจาะจง)

หลักการสำคัญ: ใช้ "insert แบบ idempotent" ไม่ใช่ "toggle"
เพราะถ้า Agent ตีความประโยคเดิมซ้ำ (เช่นผู้ใช้พิมพ์คำสั่งเดิมอีกรอบ) ไม่ควรพลิกสถานะกลับไปเป็น "ว่าง"
โดยไม่ตั้งใจ — ต่างจาก endpoint /toggle ที่ใช้ตอนกดปุ่มบน UI (ซึ่งผู้ใช้ตั้งใจกดสลับสถานะเอง)

แก้ไขล่าสุด (ย้าย logic จาก prompt มาไว้ในโค้ด):
  - ตั้ง/ยกเลิกไม่ว่าง รับหลายวันได้ใน 1 call: days="ทุกวัน" / "จันทร์-พุธ" / "จันทร์, พุธ"
    และ period="เช้า" / "บ่าย" / "ทั้งวัน" / "08:00-12:00"
    เดิมรับวันเดียว ทำให้ "ไม่ว่างช่วงเช้าทุกวัน" ต้องให้ LLM เรียก tool 5 รอบ (เปลือง token)
    หรือ LLM ปฏิเสธไปเลย
  - อ่าน/เขียนฐานข้อมูลแบบ batch (query 1 ครั้ง + insert 1 ครั้ง) แทนวนทีละคาบ
  - ผลลัพธ์สรุปเป็นวันภาษาไทย + จำนวนคาบ แทน list ของ timeslot_id ที่ LLM ไม่ได้ใช้
  - set_student_count ใช้ _find_group_id แบบเข้มงวด: ถ้าไม่ระบุสาขาจะคืน error ให้ถามกลับ
  - close_subject_section ลบ preferred_timeslots ด้วย (เดิมลบไม่ครบ อาจติด FK)
  - เขียนข้อมูลสำเร็จแล้วเรียก refresh_cache() ทุกครั้ง — เดิม tool เขียนลง Supabase ตรงๆ
    แต่ไม่ล้าง cache ใน backend ทำให้หน้าเว็บ (ที่อ่านผ่าน cache) ไม่เห็นข้อมูลที่แชทเพิ่งแก้
    จนกว่าจะ restart backend (router ฝั่งหน้าเว็บ refresh cache อยู่แล้ว เหลือแต่ฝั่ง Agent)
"""

from .get_data import supabase, load
from .query_data import (
    DAY_ORDER,
    _find_teacher_id,
    _find_room_id,
    _find_group_id,
    _find_subject_id,
    _find_timeslot_ids,
    _find_timeslot_ids_by_range,
    day_th,
    group_label,
)


# ═══════════════════════════════════════════════════════════════
# helper
# ═══════════════════════════════════════════════════════════════

def _refresh_cache() -> None:
    """ล้าง cache ข้อมูลใน backend หลังเขียนสำเร็จ ให้หน้าเว็บ/ตัวจัดตารางเห็นข้อมูลล่าสุด
    ห่อ try ไว้ — ถ้า refresh ไม่ได้ ไม่ควรทำให้การแก้ไขที่สำเร็จไปแล้วกลายเป็น error"""
    try:
        from .load_data import refresh_cache
        refresh_cache()
    except Exception:
        pass


def _days_of(timeslot_ids: list[int]) -> list[str]:
    """สรุปว่า timeslot ชุดนี้ครอบคลุมวันไหนบ้าง (ภาษาไทย เรียงจันทร์ → ศุกร์)"""
    ids = set(timeslot_ids)
    codes = {t["day"] for t in load("timeslots") if t["timeslot_id"] in ids}
    return [day_th(c) for c in DAY_ORDER if c in codes]


def _bulk_set_unavailable(table: str, id_col: str, id_value, timeslot_ids: list[int]) -> tuple[int, int]:
    """insert แบบ idempotent ทีเดียวทั้งชุด คืน (จำนวนที่เพิ่มใหม่, จำนวนที่ไม่ว่างอยู่ก่อนแล้ว)"""
    existing = {
        r["timeslot_id"]
        for r in supabase.table(table)
        .select("timeslot_id")
        .eq(id_col, id_value)
        .in_("timeslot_id", timeslot_ids)
        .execute()
        .data
    }
    to_insert = [tid for tid in timeslot_ids if tid not in existing]
    if to_insert:
        supabase.table(table).insert([{id_col: id_value, "timeslot_id": tid} for tid in to_insert]).execute()
    return len(to_insert), len(existing)


def _teacher_name(teacher_id) -> str:
    return next((t["teacher_name"] for t in load("teachers") if t["teacher_id"] == teacher_id), str(teacher_id))


# ═══════════════════════════════════════════════════════════════
# วิชาที่เปิดสอน
# ═══════════════════════════════════════════════════════════════

def open_subject_section(subject_name: str, teacher_names: list[str], academic_year: int, group_names: list[str] = None) -> dict:
    """เปิดสอนวิชาใหม่ (สร้าง section ใน subject_selected) พร้อมผูกอาจารย์และชั้นปีที่เรียน

    หมายเหตุ: tool นี้ไม่ได้เช็ค conflict ละเอียดเท่าหน้าเว็บ ถ้าต้องการตั้งค่าขั้นสูง
    (หลาย section, บรรยายรวม, ล็อกห้อง) แนะนำให้ใช้หน้าเว็บแทน

    Args:
        subject_name: รหัสวิชาหรือชื่อวิชา
        teacher_names: รายชื่ออาจารย์ผู้สอน (1 คนขึ้นไป)
        academic_year: ปีการศึกษา เช่น 2569
        group_names: ชั้นปีที่เรียน ต้องระบุสาขา เช่น ["CS ปี 1", "IT ปี 1"]
                     (ถ้าวิชานี้ผูกชั้นปีตายตัวอยู่แล้ว ไม่ต้องระบุ)

    Returns:
        สำเร็จ: dict ของ section ที่สร้างเสร็จ
        ผิดพลาด: dict ที่มี key "error"
    """
    try:
        subject_id = _find_subject_id(subject_name)
        teacher_ids = [_find_teacher_id(name) for name in teacher_names]
        group_ids = [_find_group_id(name) for name in (group_names or [])]
    except ValueError as e:
        return {"error": str(e)}

    # ถ้าวิชาผูก group_id ตายตัวอยู่แล้ว (ไม่ null) ใช้ค่านั้นแทนที่ผู้ใช้ระบุมา
    subject = next((s for s in load("subjects") if s["subject_id"] == subject_id), None)
    if subject and subject.get("group_id"):
        group_ids = [subject["group_id"]]
    elif not group_ids:
        return {"error": "วิชานี้ไม่มีชั้นปีกำหนดไว้ตายตัว ต้องระบุชั้นปีพร้อมสาขามาด้วย เช่น 'CS ปี 3'"}

    section = (
        supabase.table("subject_selected")
        .insert({"subject_id": subject_id, "academic_year": academic_year, "status": "active"})
        .execute()
        .data[0]
    )
    section_id = section["id"]

    supabase.table("subject_selected_groups").insert(
        [{"subject_selected_id": section_id, "group_id": g} for g in group_ids]
    ).execute()
    supabase.table("subject_selected_teachers").insert(
        [{"subject_selected_id": section_id, "teacher_id": t} for t in teacher_ids]
    ).execute()

    return {
        "section_id": section_id,
        "subject_id": subject_id,
        "academic_year": academic_year,
        "teachers": [_teacher_name(t) for t in teacher_ids],
        "groups": [group_label(g) for g in group_ids],
    }


def close_subject_section(subject_selected_id: int) -> dict:
    """ลบ section ที่เปิดสอนไว้ (ลบ subject_selected พร้อมข้อมูลที่ผูกไว้)

    Args:
        subject_selected_id: id ของ section ที่จะลบ (ดู section_id ได้จาก get_subject_sections)

    Returns:
        สำเร็จ: {"deleted": True, "subject_selected_id": ...}
        ผิดพลาด: dict ที่มี key "error"
    """
    for child in ("subject_selected_groups", "subject_selected_teachers", "subject_selected_preferred_timeslots"):
        supabase.table(child).delete().eq("subject_selected_id", subject_selected_id).execute()

    result = supabase.table("subject_selected").delete().eq("id", subject_selected_id).execute()

    if not result.data:
        return {"error": f"ไม่พบ section id {subject_selected_id} ในระบบ"}

    return {"deleted": True, "subject_selected_id": subject_selected_id}


# ═══════════════════════════════════════════════════════════════
# นิสิต
# ═══════════════════════════════════════════════════════════════

def set_student_count(group_name: str, total_students: int) -> dict:
    """แก้ไขจำนวนนิสิตของกลุ่ม/ชั้นปีที่ระบุ (ต้องระบุสาขาให้ชัด)

    Args:
        group_name: ชั้นปีพร้อมสาขา เช่น "IT ปี 2", "คอม ปี 1"
                    ถ้าไม่ระบุสาขา tool จะคืน error ให้ถามผู้ใช้กลับว่า CS หรือ IT
        total_students: จำนวนนิสิตใหม่ (ต้องไม่ติดลบ)

    Returns:
        สำเร็จ: {"group", "total_students"}
        ผิดพลาด: dict ที่มี key "error"
    """
    if total_students < 0:
        return {"error": "จำนวนนิสิตต้องไม่ติดลบ"}

    try:
        group_id = _find_group_id(group_name)
    except ValueError as e:
        return {"error": str(e)}

    result = (
        supabase.table("student_group")
        .update({"total_students": total_students})
        .eq("group_id", group_id)
        .execute()
    )

    if not result.data:
        return {"error": f"ไม่พบกลุ่มนิสิต '{group_name}' ในระบบ"}

    return {"group": group_label(result.data[0]), "total_students": result.data[0]["total_students"]}


# ═══════════════════════════════════════════════════════════════
# ช่วงเวลาไม่ว่าง
# ═══════════════════════════════════════════════════════════════

def set_teacher_unavailability(teacher_name: str, days: str, period: str = "ทั้งวัน") -> dict:
    """ตั้งค่าให้อาจารย์ไม่ว่าง ได้หลายวันในการเรียกครั้งเดียว

    Args:
        teacher_name: ชื่ออาจารย์ (ค้นหาแบบ partial match ได้ เช่น "ธนะธร")
        days: วัน เช่น "จันทร์", "ทุกวัน", "จันทร์-พุธ", "จันทร์, พฤหัสบดี"
        period: "เช้า", "บ่าย", "ทั้งวัน" หรือช่วงเวลาเช่น "08:00-12:00" (ไม่ระบุ = ทั้งวัน)

    Returns:
        สำเร็จ: {teacher, days, period, newly_added_slots, already_unavailable_slots}
        ผิดพลาด: dict ที่มี key "error"
    """
    try:
        teacher_id = _find_teacher_id(teacher_name)
        timeslot_ids = _find_timeslot_ids(days, period)
    except ValueError as e:
        return {"error": str(e)}

    added, existed = _bulk_set_unavailable("teacher_unavailability", "teacher_id", teacher_id, timeslot_ids)

    return {
        "teacher": _teacher_name(teacher_id),
        "days": _days_of(timeslot_ids),
        "period": period or "ทั้งวัน",
        "newly_added_slots": added,
        "already_unavailable_slots": existed,
    }


def remove_teacher_unavailability(teacher_name: str, days: str, period: str = "ทั้งวัน") -> dict:
    """ยกเลิกการตั้งค่า 'ไม่ว่าง' ของอาจารย์ (กลับไปว่างปกติ) ได้หลายวันในการเรียกครั้งเดียว

    Args:
        teacher_name: ชื่ออาจารย์ (ค้นหาแบบ partial match ได้)
        days: วัน เช่น "จันทร์", "ทุกวัน", "จันทร์-พุธ"
        period: "เช้า", "บ่าย", "ทั้งวัน" หรือ "08:00-12:00" (ไม่ระบุ = ทั้งวัน)

    Returns:
        สำเร็จ: {teacher, days, period, removed_slots}
        ผิดพลาด: dict ที่มี key "error"
    """
    try:
        teacher_id = _find_teacher_id(teacher_name)
        timeslot_ids = _find_timeslot_ids(days, period)
    except ValueError as e:
        return {"error": str(e)}

    result = (
        supabase.table("teacher_unavailability")
        .delete()
        .eq("teacher_id", teacher_id)
        .in_("timeslot_id", timeslot_ids)
        .execute()
    )

    return {
        "teacher": _teacher_name(teacher_id),
        "days": _days_of(timeslot_ids),
        "period": period or "ทั้งวัน",
        "removed_slots": len(result.data or []),
    }


def set_room_unavailability(room_name: str, days: str, start_time: str, end_time: str) -> dict:
    """ตั้งค่าให้ห้องเรียนไม่ว่าง (ครอบคลุมทุกคาบที่ทับซ้อนกับช่วงเวลา) ได้หลายวันในครั้งเดียว

    Args:
        room_name: รหัสห้อง เช่น "SC1-311" (ไม่สนตัวพิมพ์เล็ก/ใหญ่)
        days: วัน เช่น "จันทร์", "ทุกวัน", "จันทร์-พุธ"
        start_time: เวลาเริ่ม เช่น "10:00"
        end_time: เวลาสิ้นสุด เช่น "11:50"

    Returns:
        สำเร็จ: {room, days, start_time, end_time, newly_added_slots, already_unavailable_slots}
        ผิดพลาด: dict ที่มี key "error"
    """
    try:
        room_id = _find_room_id(room_name)
        timeslot_ids = _find_timeslot_ids_by_range(days, start_time, end_time)
    except ValueError as e:
        return {"error": str(e)}

    added, existed = _bulk_set_unavailable("room_unavailability", "room_id", room_id, timeslot_ids)

    return {
        "room": room_name.strip().upper(),
        "days": _days_of(timeslot_ids),
        "start_time": start_time,
        "end_time": end_time,
        "newly_added_slots": added,
        "already_unavailable_slots": existed,
    }