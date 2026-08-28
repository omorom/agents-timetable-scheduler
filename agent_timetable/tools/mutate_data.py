"""
mutate_data.py
Tool สำหรับให้ Agent "แก้ไขข้อมูล" (เขียนลง Supabase) เท่านั้น
แยกจาก get_data.py (อ่านข้อมูลดิบทั้งตาราง) และ query_data.py (อ่านข้อมูลเจาะจง)

หลักการสำคัญ: ใช้ "insert แบบ idempotent" ไม่ใช่ "toggle"
เพราะถ้า Agent ตีความประโยคเดิมซ้ำ (เช่นผู้ใช้พิมพ์คำสั่งเดิมอีกรอบ) ไม่ควรพลิกสถานะกลับไปเป็น "ว่าง"
โดยไม่ตั้งใจ — ต่างจาก endpoint /toggle ที่ใช้ตอนกดปุ่มบน UI (ซึ่งผู้ใช้ตั้งใจกดสลับสถานะเอง)
"""

from .get_data import supabase, load
from .query_data import (
    _find_teacher_id,
    _find_room_id,
    _find_group_id,
    _find_subject_id,
    _find_timeslot_ids,
    _find_timeslot_ids_by_range,
)


def open_subject_section(subject_name: str, teacher_names: list[str], academic_year: int, group_names: list[str] = None) -> dict:
    """เปิดสอนวิชาใหม่ (สร้าง section ใน subject_selected) พร้อมผูกอาจารย์และชั้นปีที่เรียน

    หมายเหตุ: tool นี้ไม่ได้เช็ค duplicate/conflict ละเอียดเท่า endpoint REST (/subject-selected)
    ใช้สำหรับเปิดเซคใหม่แบบพื้นฐาน ถ้าต้องการเช็คขั้นสูง แนะนำให้ใช้หน้าเว็บฟอร์มแทน

    Args:
        subject_name: รหัสวิชาหรือชื่อวิชา
        teacher_names: รายชื่ออาจารย์ผู้สอน (1 คนขึ้นไป)
        academic_year: ปีการศึกษา เช่น 2568
        group_names: ชั้นปีที่เรียน เช่น ["ปี 1"] (ถ้าวิชานี้ผูกปีตายตัวอยู่แล้วในระบบ ไม่ต้องระบุก็ได้)

    Returns:
        สำเร็จ: dict ของ section ที่สร้างเสร็จ (subject_selected_id, subject_id, teachers, group_ids)
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
        return {"error": "วิชานี้ไม่มีชั้นปีกำหนดไว้ตายตัว ต้องระบุชั้นปี (group_names) มาด้วย"}

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
        "subject_selected_id": section_id,
        "subject_id": subject_id,
        "academic_year": academic_year,
        "teacher_names": teacher_names,
        "group_ids": group_ids,
    }


def close_subject_section(subject_selected_id: int) -> dict:
    """ลบ section ที่เปิดสอนไว้ (ลบ subject_selected พร้อมข้อมูลที่ผูกไว้)

    Args:
        subject_selected_id: id ของ section ที่จะลบ (ดูได้จาก get_subject_sections)

    Returns:
        สำเร็จ: {"deleted": True, "subject_selected_id": ...}
        ผิดพลาด: dict ที่มี key "error"
    """
    supabase.table("subject_selected_groups").delete().eq("subject_selected_id", subject_selected_id).execute()
    supabase.table("subject_selected_teachers").delete().eq("subject_selected_id", subject_selected_id).execute()

    result = supabase.table("subject_selected").delete().eq("id", subject_selected_id).execute()

    if not result.data:
        return {"error": f"ไม่พบ section id {subject_selected_id} ในระบบ"}

    return {"deleted": True, "subject_selected_id": subject_selected_id}


def set_student_count(group_name: str, total_students: int) -> dict:
    """แก้ไขจำนวนนิสิตของกลุ่ม/ชั้นปีที่ระบุ

    Args:
        group_name: ชื่อกลุ่ม/ชั้นปี (ค้นหาแบบ partial match ได้ เช่น "ปี 1")
        total_students: จำนวนนิสิตใหม่ (ต้องไม่ติดลบ)

    Returns:
        สำเร็จ: dict ของแถวที่อัปเดตแล้ว (group_id, group_name, total_students)
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

    return result.data[0]


def remove_teacher_unavailability(teacher_name: str, day: str, period: str) -> dict:
    """ยกเลิกการตั้งค่า 'ไม่ว่าง' ของอาจารย์ในวัน+ช่วงเวลาที่ระบุ (กลับไปว่างปกติ)

    Args:
        teacher_name: ชื่ออาจารย์ (ค้นหาแบบ partial match ได้)
        day: วันภาษาไทย เช่น "จันทร์", "อังคาร"
        period: ช่วงเวลา "เช้า" หรือ "บ่าย"

    Returns:
        สำเร็จ: dict สรุปว่ายกเลิกคาบไหนไปบ้าง (removed_timeslot_ids)
        ผิดพลาด: dict ที่มี key "error"
    """
    try:
        teacher_id = _find_teacher_id(teacher_name)
        timeslot_ids = _find_timeslot_ids(day, period)
    except ValueError as e:
        return {"error": str(e)}

    removed = []
    for timeslot_id in timeslot_ids:
        result = (
            supabase.table("teacher_unavailability")
            .delete()
            .eq("teacher_id", teacher_id)
            .eq("timeslot_id", timeslot_id)
            .execute()
        )
        if result.data:
            removed.append(timeslot_id)

    return {"teacher_id": teacher_id, "day": day, "period": period, "removed_timeslot_ids": removed}


def set_teacher_unavailability(teacher_name: str, day: str, period: str) -> dict:
    """ตั้งค่าให้อาจารย์ไม่ว่างในวัน+ช่วงเวลาที่ระบุ (ครอบคลุมทุกคาบในช่วงนั้น)

    Args:
        teacher_name: ชื่ออาจารย์ (ค้นหาแบบ partial match ได้ เช่น "ธนะธร")
        day: วันภาษาไทย เช่น "จันทร์", "อังคาร"
        period: ช่วงเวลา "เช้า" หรือ "บ่าย"

    Returns:
        สำเร็จ: dict สรุปว่าตั้งค่าคาบไหนใหม่ (newly_added_timeslot_ids)
                และคาบไหนไม่ว่างอยู่ก่อนแล้ว (already_unavailable_timeslot_ids)
        ผิดพลาด: dict ที่มี key "error" อธิบายสาเหตุ (ห้ามให้ tool ล้มทั้ง request)
    """
    try:
        teacher_id = _find_teacher_id(teacher_name)
        timeslot_ids = _find_timeslot_ids(day, period)
    except ValueError as e:
        return {"error": str(e)}

    newly_added = []
    already_existed = []

    for timeslot_id in timeslot_ids:
        existing = (
            supabase.table("teacher_unavailability")
            .select("id")
            .eq("teacher_id", teacher_id)
            .eq("timeslot_id", timeslot_id)
            .execute()
        )
        if existing.data:
            already_existed.append(timeslot_id)
            continue

        supabase.table("teacher_unavailability").insert(
            {"teacher_id": teacher_id, "timeslot_id": timeslot_id}
        ).execute()
        newly_added.append(timeslot_id)

    return {
        "teacher_id": teacher_id,
        "day": day,
        "period": period,
        "newly_added_timeslot_ids": newly_added,
        "already_unavailable_timeslot_ids": already_existed,
    }


def set_room_unavailability(room_name: str, day: str, start_time: str, end_time: str) -> dict:
    """ตั้งค่าให้ห้องเรียนไม่ว่างในวัน+ช่วงเวลาที่ระบุ (ครอบคลุมทุกคาบที่ทับซ้อนกับช่วงนั้น)

    Args:
        room_name: รหัสห้อง เช่น "SC1-311" (ไม่สนตัวพิมพ์เล็ก/ใหญ่)
        day: วันภาษาไทย เช่น "จันทร์", "อังคาร"
        start_time: เวลาเริ่ม เช่น "10:00"
        end_time: เวลาสิ้นสุด เช่น "11:50"

    Returns:
        สำเร็จ: dict สรุปว่าตั้งค่าคาบไหนใหม่ (newly_added_timeslot_ids)
                และคาบไหนไม่ว่างอยู่ก่อนแล้ว (already_unavailable_timeslot_ids)
        ผิดพลาด: dict ที่มี key "error" อธิบายสาเหตุ (ห้ามให้ tool ล้มทั้ง request)
    """
    try:
        room_id = _find_room_id(room_name)
        timeslot_ids = _find_timeslot_ids_by_range(day, start_time, end_time)
    except ValueError as e:
        return {"error": str(e)}

    newly_added = []
    already_existed = []

    for timeslot_id in timeslot_ids:
        existing = (
            supabase.table("room_unavailability")
            .select("id")
            .eq("room_id", room_id)
            .eq("timeslot_id", timeslot_id)
            .execute()
        )
        if existing.data:
            already_existed.append(timeslot_id)
            continue

        supabase.table("room_unavailability").insert(
            {"room_id": room_id, "timeslot_id": timeslot_id}
        ).execute()
        newly_added.append(timeslot_id)

    return {
        "room_id": room_id,
        "day": day,
        "start_time": start_time,
        "end_time": end_time,
        "newly_added_timeslot_ids": newly_added,
        "already_unavailable_timeslot_ids": already_existed,
    }