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

# คำใบ้ให้ AI เวลากรองด้วยคอลัมน์ที่ไม่มีอยู่จริง (ข้อมูลที่เก็บแยกไว้อีกตาราง)
TABLE_HINTS = {
    "subject_selected": "กลุ่มนิสิตอยู่ในตาราง subject_selected_groups, อาจารย์อยู่ใน subject_selected_teachers "
                        "(ถ้าถามว่ากลุ่มไหนเรียนวิชาอะไร ใช้ get_group_subjects แทน)",
    "subjects": "ประเภทวิชาอยู่ในคอลัมน์ subject_type (CORE / ELECTIVE / GENERAL)",
}


def load(key: str, filters: dict = None, limit: int = 1000) -> list:
    """ดึงข้อมูลจากตาราง Supabase ตาม key ที่กำหนดไว้ (ใช้ภายในโค้ด — error จะ raise ออกไป)

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
    """ดึงข้อมูลทุกตารางที่กำหนดไว้ใน TABLE_MAP ทีเดียว (ใช้ภายในโค้ด)

    Returns:
        dict ที่ key ตรงกับ TABLE_MAP และ value คือ list ข้อมูลของตารางนั้น
    """
    return {key: load(key) for key in TABLE_MAP}


def _columns_of(table_name: str) -> list[str]:
    """ชื่อคอลัมน์ของตาราง (อ่านจากแถวแรก) — ใช้บอก AI ตอนกรองด้วยคอลัมน์ผิด"""
    try:
        rows = supabase.table(table_name).select("*").limit(1).execute().data
        return sorted(rows[0].keys()) if rows else []
    except Exception:
        return []


def query_table(key: str, filters: dict = None, limit: int = 1000) -> dict:
    """ดูข้อมูลดิบจากตารางในระบบ (ใช้เมื่อไม่มี tool เฉพาะทางตรงกับคำถาม)

    Args:
        key: ชื่อตาราง เช่น 'rooms', 'teachers', 'subjects', 'groups', 'subject_selected',
            'subject_selected_groups', 'subject_selected_teachers', 'timeslots', 'timetable'
        filters: เงื่อนไขกรองแบบเท่ากับ เช่น {"teacher_id": "T1"} ใช้ได้เฉพาะคอลัมน์ที่มีจริงในตารางนั้น
        limit: จำนวนแถวสูงสุด (ค่าเริ่มต้น 1000)

    Returns:
        สำเร็จ: {"table": key, "count": จำนวนแถว, "rows": [...]}
        ผิดพลาด: {"error": ข้อความ, "columns": คอลัมน์ที่มีจริง, "hint": คำแนะนำ (ถ้ามี)}
    """
    table_name = TABLE_MAP.get(key)
    if not table_name:
        return {"error": f"ไม่รู้จักตาราง '{key}'", "available_tables": list(TABLE_MAP.keys())}

    try:
        rows = load(key, filters, limit)
    except Exception as e:
        result = {
            "error": f"อ่านตาราง '{key}' ไม่ได้: {getattr(e, 'message', None) or e}",
            "columns": _columns_of(table_name),
        }
        if key in TABLE_HINTS:
            result["hint"] = TABLE_HINTS[key]
        return result

    return {"table": key, "count": len(rows), "rows": rows}


def query_all_tables() -> dict:
    """ดูข้อมูลดิบทุกตารางในระบบทีเดียว (ข้อมูลเยอะ ใช้เมื่อจำเป็นจริงๆ เท่านั้น)

    Returns:
        dict ที่ key เป็นชื่อตาราง และ value เป็น list ข้อมูล หรือ {"error": ...} ถ้าตารางนั้นอ่านไม่ได้
    """
    result = {}
    for key in TABLE_MAP:
        try:
            result[key] = load(key)
        except Exception as e:
            result[key] = {"error": f"อ่านตาราง '{key}' ไม่ได้: {getattr(e, 'message', None) or e}"}
    return result


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
        groups = row.pop("subject_selected_groups", [])
        row["group_ids"] = [g["group_id"] for g in groups]
        row["is_lecture_combined"] = groups[0]["is_lecture_combined"] if groups else False

        teacher_links = row.pop("subject_selected_teachers", [])
        row["teachers"] = [t["teacher"] for t in teacher_links if t.get("teacher")]

    return rows