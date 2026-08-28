import os
from supabase import create_client

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

TABLE_MAP = {
    "rooms": "rooms",
    "timeslots": "timeslots",
    "subjects": "subjects",
    "teachers": "teacher",
    "groups": "student_group",
    "subject_selected": "subject_selected",
    "subject_selected_groups": "subject_selected_groups",
    "subject_selected_teachers": "subject_selected_teachers",
    "subject_selected_preferred_timeslots": "subject_selected_preferred_timeslots",
    "teacher_unavailability": "teacher_unavailability",
    "room_unavailability": "room_unavailability",
    "timetable": "timetable_ai",
}


def load(key: str, filters: dict = None, limit: int = 1000) -> list:
    """ดึงข้อมูลจากตาราง Supabase ตาม key ที่กำหนดไว้

    Args:
        key: ชื่อกลุ่มข้อมูล เช่น 'rooms', 'teachers', 'subject_selected'
        filters: dict เงื่อนไขกรอง เช่น {"teacher_id": "T1"}
        limit: จำนวนแถวสูงสุด

    Returns:
        list ของ dict ข้อมูลจากตารางที่เกี่ยวข้อง
    """
    table_name = TABLE_MAP.get(key)
    if not table_name:
        raise ValueError(f"ไม่รู้จัก key: {key}. ตัวเลือกที่มี: {list(TABLE_MAP.keys())}")

    query = supabase.table(table_name).select("*")
    if filters:
        for col, val in filters.items():
            query = query.eq(col, val)
    return query.limit(limit).execute().data


def load_all() -> dict:
    """ดึงข้อมูลทุกตารางที่กำหนดไว้ใน TABLE_MAP ทีเดียว

    Returns:
        dict ที่ key ตรงกับ TABLE_MAP และ value คือ list ข้อมูลของตารางนั้น
    """
    return {key: load(key) for key in TABLE_MAP}


def load_subject_selected_full(academic_year: int = None) -> list:

    """ดึงข้อมูล subject_selected พร้อมข้อมูลที่เกี่ยวข้อง (subjects, groups, teachers, preferred timeslots)"""

    query = supabase.table("subject_selected").select(
        "*, subjects(*), "
        "subject_selected_groups(group_id, is_lecture_combined), "
        "subject_selected_teachers(teacher(teacher_id, teacher_name)), "
        "subject_selected_preferred_timeslots(timeslot_id)"
    )
    if academic_year is not None:
        query = query.eq("academic_year", academic_year)

    rows = query.execute().data

    for row in rows:
        # แปลง subject_selected_groups ให้เป็น list ของ group_id ตรง ๆ แทน list ของ dict
        groups = row.pop("subject_selected_groups", [])
        row["group_ids"] = [g["group_id"] for g in groups]
        # ทุกแถวของ section เดียวกันมีค่า is_lecture_combined เท่ากันเสมอ (insert ใส่ค่าเดียวกันทุกแถว)
        # เอาแถวแรกพอ ถ้าไม่มี group เลยก็ถือว่าไม่รวม (false)
        row["is_lecture_combined"] = groups[0]["is_lecture_combined"] if groups else False

        # แปลง subject_selected_teachers (list ของ {teacher: {...}}) ให้เป็น list ของอาจารย์ตรง ๆ
        teacher_links = row.pop("subject_selected_teachers", [])
        row["teachers"] = [t["teacher"] for t in teacher_links if t.get("teacher")]

    return rows