"""
query_data.py
Tool + helper สำหรับ "อ่าน" ข้อมูลเจาะจง (query) แยกจาก get_data.py ที่โหลดข้อมูลดิบทั้งตาราง
และแยกจาก mutate_data.py ที่ทำหน้าที่ "เขียน" ข้อมูลเท่านั้น

ไฟล์นี้มี 2 กลุ่ม:
  1. Helper (_find_*) — ใช้ร่วมกันทุกไฟล์ (query_data_people.py, query_data_spaces.py, mutate_data.py)
     เพื่อแปลง "ชื่อ/คำอธิบาย" เป็น id จริง
  2. Tool (get_*) — ให้ Agent เรียกดูว่าอาจารย์/ห้องไม่ว่างช่วงไหนบ้าง (ของเดิม)

ฟังก์ชันใหม่ๆ (นิสิต/อาจารย์/ห้อง/วิชา/ตาราง เพิ่มเติม) แยกไปอยู่ที่
query_data_people.py และ query_data_spaces.py แทน — ไฟล์นี้เก็บแค่ของเดิมไว้
ไม่ให้ยาวเกินไป
"""

from .get_data import supabase, load
import re

# แปลงวันภาษาไทย -> ตัวย่อที่เก็บจริงใน timeslots.day
DAY_MAP = {
    "จันทร์": "MON",
    "อังคาร": "TUE",
    "พุธ": "WED",
    "พฤหัส": "THU",
    "พฤหัสบดี": "THU",
    "ศุกร์": "FRI",
}

# ขอบเขตเวลา เช้า/บ่าย โดยแยกจากพักเที่ยง (12:00-13:00) อย่างชัดเจน
PERIOD_MAP = {
    "เช้า": ("00:00:00", "12:00:00"),   # ก่อนเที่ยง
    "บ่าย": ("13:00:00", "23:59:59"),   # หลังพักเที่ยง
}


# --- helper: แปลงชื่อ/คำอธิบาย -> id จริง (ใช้ร่วมกันทุกไฟล์ query/mutate) -------------

def _find_teacher_id(teacher_name: str) -> str:
    """หา teacher_id จากชื่อ (ค้นหาแบบ substring match กับ teacher_name ที่เก็บในตาราง)"""
    teachers = load("teachers")
    keyword = teacher_name.strip().lower()

    matches = [t for t in teachers if keyword in (t.get("teacher_name") or "").lower()]

    if not matches:
        raise ValueError(f"ไม่พบอาจารย์ชื่อ '{teacher_name}' ในระบบ")
    if len(matches) > 1:
        names = ", ".join(m["teacher_name"] for m in matches)
        raise ValueError(f"พบอาจารย์หลายคนที่ตรงกับ '{teacher_name}': {names} กรุณาระบุชื่อให้ชัดเจนขึ้น")

    return matches[0]["teacher_id"]


def _find_subject_id(subject_name: str) -> str:
    """หา subject_id จากรหัสวิชาหรือชื่อวิชา (ค้นหาแบบ partial match กับ subject_id/name_thai/name_english)"""
    subjects = load("subjects")
    keyword = subject_name.strip().lower()

    matches = [
        s for s in subjects
        if keyword in (s.get("subject_id") or "").lower()
        or keyword in (s.get("name_thai") or "").lower()
        or keyword in (s.get("name_english") or "").lower()
    ]

    if not matches:
        raise ValueError(f"ไม่พบวิชา '{subject_name}' ในระบบ")
    if len(matches) > 1:
        names = ", ".join(f"{s['subject_id']} ({s.get('name_thai')})" for s in matches)
        raise ValueError(f"พบวิชาหลายรายการที่ตรงกับ '{subject_name}': {names} กรุณาระบุให้ชัดเจนขึ้น")

    return matches[0]["subject_id"]


def get_subject_sections(subject_name: str) -> dict:
    """ดูว่าวิชานี้เปิดสอนกี่เซค แต่ละเซคใครสอนบ้าง

    Args:
        subject_name: รหัสวิชาหรือชื่อวิชา (เช่น "01418111" หรือ "โครงสร้างข้อมูล")

    Returns:
        สำเร็จ: dict มี key "sections" เป็น list ของ {subject_selected_id, teachers, academic_year}
        ผิดพลาด: dict ที่มี key "error"
    """
    try:
        subject_id = _find_subject_id(subject_name)
    except ValueError as e:
        return {"error": str(e)}

    rows = (
        supabase.table("subject_selected")
        .select(
            "id, academic_year, "
            "subject_selected_teachers(teacher(teacher_name)), "
            "subject_selected_groups(group_id)"
        )
        .eq("subject_id", subject_id)
        .execute()
        .data
    )

    sections = [
        {
            "subject_selected_id": r["id"],
            "academic_year": r["academic_year"],
            "teachers": [
                t["teacher"]["teacher_name"]
                for t in (r.get("subject_selected_teachers") or [])
                if t.get("teacher")
            ],
            "group_ids": [g["group_id"] for g in (r.get("subject_selected_groups") or [])],
        }
        for r in rows
    ]

    return {"subject_id": subject_id, "sections": sections}


def get_teacher_subjects(teacher_name: str) -> dict:
    """ดูว่าอาจารย์คนนี้สอนวิชาอะไรบ้าง

    Args:
        teacher_name: ชื่ออาจารย์ (ค้นหาแบบ partial match ได้)

    Returns:
        สำเร็จ: dict มี key "subjects" เป็น list ของ {subject_id, name_thai, academic_year}
        ผิดพลาด: dict ที่มี key "error"
    """
    try:
        teacher_id = _find_teacher_id(teacher_name)
    except ValueError as e:
        return {"error": str(e)}

    rows = (
        supabase.table("subject_selected_teachers")
        .select("subject_selected(id, academic_year, subjects(subject_id, name_thai))")
        .eq("teacher_id", teacher_id)
        .execute()
        .data
    )

    subjects_taught = [
        {
            "subject_id": r["subject_selected"]["subjects"]["subject_id"],
            "name_thai": r["subject_selected"]["subjects"]["name_thai"],
            "academic_year": r["subject_selected"]["academic_year"],
        }
        for r in rows
        if r.get("subject_selected") and r["subject_selected"].get("subjects")
    ]

    return {"teacher_id": teacher_id, "subjects": subjects_taught}


def _find_room_id(room_name: str):
    """หา room_id จากชื่อห้อง (room_name เช่น 'SC1-304') ไม่ใช่จากคอลัมน์ room_id ที่เป็นแค่เลข index
    ค้นหาแบบ case-insensitive และตัดช่องว่างส่วนเกินทั้ง 2 ฝั่ง"""
    rooms = load("rooms")
    keyword = room_name.strip().lower()

    matches = [r for r in rooms if (r.get("room_name") or "").strip().lower() == keyword]

    if not matches:
        available = ", ".join(r.get("room_name", "") for r in rooms)
        raise ValueError(f"ไม่พบห้องเรียน '{room_name}' ในระบบ (ห้องที่มีในระบบ: {available})")

    return matches[0]["room_id"]


def _find_timeslot_ids(day: str, period: str) -> list[int]:
    """หา timeslot_id ทั้งหมดที่ตรงกับวัน + ช่วงเวลา (เช้า/บ่าย)"""
    day_code = DAY_MAP.get(day.strip())
    if not day_code:
        raise ValueError(f"ไม่รู้จักวัน '{day}' (ต้องเป็น: {', '.join(DAY_MAP.keys())})")

    if period not in PERIOD_MAP:
        raise ValueError(f"ไม่รู้จักช่วงเวลา '{period}' (ต้องเป็น: เช้า หรือ บ่าย)")

    start_bound, end_bound = PERIOD_MAP[period]
    timeslots = load("timeslots")

    matched = [
        t["timeslot_id"] for t in timeslots
        if t["day"] == day_code and start_bound <= t["start_time"] < end_bound
    ]

    if not matched:
        raise ValueError(f"ไม่พบคาบเวลาสำหรับวัน {day} ช่วง {period}")

    return matched


def _find_timeslot_ids_by_range(day: str, start_time: str, end_time: str) -> list[int]:
    """หา timeslot_id ทั้งหมดที่ 'ทับซ้อน' กับช่วงเวลาที่ระบุ (ไม่ใช่แค่ label เช้า/บ่าย)
    ใช้หลัก overlap: timeslot.start_time < end_time AND timeslot.end_time > start_time
    """
    day_code = DAY_MAP.get(day.strip())
    if not day_code:
        raise ValueError(f"ไม่รู้จักวัน '{day}' (ต้องเป็น: {', '.join(DAY_MAP.keys())})")

    start_norm = start_time if len(start_time) > 5 else f"{start_time}:00"
    end_norm = end_time if len(end_time) > 5 else f"{end_time}:00"

    timeslots = load("timeslots")
    matched = [
        t["timeslot_id"] for t in timeslots
        if t["day"] == day_code and t["start_time"] < end_norm and t["end_time"] > start_norm
    ]

    if not matched:
        raise ValueError(f"ไม่พบคาบเวลาที่ทับซ้อนกับช่วง {start_time}-{end_time} ในวัน {day}")

    return matched


# --- tool: อ่านข้อมูลเจาะจง (ให้ Agent เรียกโดยตรง) -------------

def _extract_year_number(text: str) -> str | None:
    """ดึงตัวเลขปีออกจากข้อความ เช่น 'ปี 1' หรือ 'year 1' -> '1'"""
    match = re.search(r"\d+", text or "")
    return match.group() if match else None


def _find_group_id(group_name: str) -> str:
    """หา group_id จากชื่อกลุ่ม/ชั้นปี โดยเทียบ 'เลขปี' เป็นหลัก (เช่น 'ปี 1' กับ 'year 1'
    ถือว่าตรงกัน) แล้วถ้ายังเจอมากกว่า 1 กลุ่ม ให้กรองซ้ำด้วย 'คำที่เหลือ' หลังตัดตัวเลข/
    คำว่า ปี/year ออก (เช่น 'IT ปี 1' เหลือ 'IT' เอาไปกรองแยก IT-YEAR-1 ออกจาก
    COMSCI-YEAR-1 ได้) — เดิมเทียบแค่เลขปีอย่างเดียว ทำให้ 'IT ปี 1' กับ 'ปี 1' ผลเหมือนกัน
    """
    groups = load("groups")
    keyword_year = _extract_year_number(group_name)

    residual = re.sub(r"\d+", "", group_name)
    residual = re.sub(r"(ปี|year|ชั้นปี|ชั้น)", "", residual, flags=re.IGNORECASE).strip().lower()

    if keyword_year:
        matches = [g for g in groups if _extract_year_number(g.get("group_name")) == keyword_year]
        if residual and len(matches) > 1:
            narrowed = [g for g in matches if residual in (g.get("group_name") or "").lower()]
            if narrowed:
                matches = narrowed
    else:
        matches = [g for g in groups if group_name.strip().lower() in (g.get("group_name") or "").lower()]

    if not matches:
        available = ", ".join(g.get("group_name", "") for g in groups)
        raise ValueError(f"ไม่พบกลุ่มนิสิต '{group_name}' ในระบบ (กลุ่มที่มีในระบบ: {available})")
    if len(matches) > 1:
        names = ", ".join(g["group_name"] for g in matches)
        raise ValueError(f"พบกลุ่มนิสิตหลายกลุ่มที่ตรงกับ '{group_name}': {names} กรุณาระบุให้ชัดเจนขึ้น")

    return matches[0]["group_id"]


def get_teacher_unavailability(teacher_name: str) -> dict:
    """ดูว่าอาจารย์คนนี้ไม่ว่างช่วงไหนบ้าง (คืนเป็นวัน+เวลาที่อ่านง่าย)

    Args:
        teacher_name: ชื่ออาจารย์ (ค้นหาแบบ partial match ได้ เช่น "ธนะธร")

    Returns:
        สำเร็จ: dict มี key "unavailable_slots" เป็น list ของ {day, start_time, end_time}
        ผิดพลาด: dict ที่มี key "error"
    """
    try:
        teacher_id = _find_teacher_id(teacher_name)
    except ValueError as e:
        return {"error": str(e)}

    rows = supabase.table("teacher_unavailability").select("timeslot_id").eq("teacher_id", teacher_id).execute().data
    timeslot_ids = {r["timeslot_id"] for r in rows}

    timeslots = load("timeslots")
    slots = [
        {"day": t["day"], "start_time": t["start_time"], "end_time": t["end_time"]}
        for t in timeslots
        if t["timeslot_id"] in timeslot_ids
    ]
    slots.sort(key=lambda s: (s["day"], s["start_time"]))

    return {"teacher_id": teacher_id, "unavailable_slots": slots}


def get_room_unavailability(room_name: str) -> dict:
    """ดูว่าห้องเรียนนี้ไม่ว่างช่วงไหนบ้าง (คืนเป็นวัน+เวลาที่อ่านง่าย)

    Args:
        room_name: รหัสห้อง เช่น "SC1-311"

    Returns:
        สำเร็จ: dict มี key "unavailable_slots" เป็น list ของ {day, start_time, end_time}
        ผิดพลาด: dict ที่มี key "error"
    """
    try:
        room_id = _find_room_id(room_name)
    except ValueError as e:
        return {"error": str(e)}

    rows = supabase.table("room_unavailability").select("timeslot_id").eq("room_id", room_id).execute().data
    timeslot_ids = {r["timeslot_id"] for r in rows}

    timeslots = load("timeslots")
    slots = [
        {"day": t["day"], "start_time": t["start_time"], "end_time": t["end_time"]}
        for t in timeslots
        if t["timeslot_id"] in timeslot_ids
    ]
    slots.sort(key=lambda s: (s["day"], s["start_time"]))

    return {"room_id": room_id, "unavailable_slots": slots}


def list_unavailable_rooms(day: str = None, period: str = None) -> dict:
    """ดูว่ามีห้องไหนไม่ว่างบ้าง กรองตามวัน/ช่วงเวลาได้ (ไม่ระบุ = คืนทั้งหมดทุกวันทุกช่วง)
    ใช้เมื่อผู้ใช้ถามแบบ 'ทิศทางกลับ' คือรู้วัน/ช่วงเวลา แต่ไม่รู้ชื่อห้อง
    เช่น "มีห้องไหนไม่ว่างช่วงบ่ายบ้าง" หรือ "วันจันทร์ห้องไหนไม่ว่างบ้าง"

    Args:
        day: วันภาษาไทย เช่น "จันทร์" (ไม่ระบุ = ทุกวัน)
        period: "เช้า" หรือ "บ่าย" (ไม่ระบุ = ทุกช่วง)

    Returns:
        dict มี key "unavailable" เป็น list ของ {room_name, day, start_time, end_time}
        หรือ {"error": ...} ถ้า day/period ที่ระบุไม่ถูกต้อง
    """
    day_code = None
    if day:
        day_code = DAY_MAP.get(day.strip())
        if not day_code:
            return {"error": f"ไม่รู้จักวัน '{day}' (ต้องเป็น: {', '.join(DAY_MAP.keys())})"}

    period_bounds = None
    if period:
        if period not in PERIOD_MAP:
            return {"error": f"ไม่รู้จักช่วงเวลา '{period}' (ต้องเป็น: เช้า หรือ บ่าย)"}
        period_bounds = PERIOD_MAP[period]

    rows = supabase.table("room_unavailability").select("room_id, timeslot_id").execute().data
    room_name_by_id = {r["room_id"]: r.get("room_name") for r in load("rooms")}
    timeslot_by_id = {t["timeslot_id"]: t for t in load("timeslots")}

    result = []
    for row in rows:
        ts = timeslot_by_id.get(row["timeslot_id"])
        if not ts:
            continue
        if day_code and ts["day"] != day_code:
            continue
        if period_bounds and not (period_bounds[0] <= ts["start_time"] < period_bounds[1]):
            continue
        result.append({
            "room_name": room_name_by_id.get(row["room_id"], row["room_id"]),
            "day": ts["day"],
            "start_time": ts["start_time"],
            "end_time": ts["end_time"],
        })

    result.sort(key=lambda x: (x["room_name"], x["day"], x["start_time"]))
    return {"unavailable": result}


def list_unavailable_teachers(day: str = None, period: str = None) -> dict:
    """ดูว่ามีอาจารย์คนไหนไม่ว่างบ้าง กรองตามวัน/ช่วงเวลาได้ (ไม่ระบุ = คืนทั้งหมดทุกวันทุกช่วง)
    ใช้เมื่อผู้ใช้ถามแบบ 'ทิศทางกลับ' คือรู้วัน/ช่วงเวลา แต่ไม่รู้ชื่ออาจารย์
    เช่น "วันอังคารช่วงเช้า อาจารย์คนไหนไม่ว่างบ้าง"

    Args:
        day: วันภาษาไทย เช่น "อังคาร" (ไม่ระบุ = ทุกวัน)
        period: "เช้า" หรือ "บ่าย" (ไม่ระบุ = ทุกช่วง)

    Returns:
        dict มี key "unavailable" เป็น list ของ {teacher_name, day, start_time, end_time}
        หรือ {"error": ...} ถ้า day/period ที่ระบุไม่ถูกต้อง
    """
    day_code = None
    if day:
        day_code = DAY_MAP.get(day.strip())
        if not day_code:
            return {"error": f"ไม่รู้จักวัน '{day}' (ต้องเป็น: {', '.join(DAY_MAP.keys())})"}

    period_bounds = None
    if period:
        if period not in PERIOD_MAP:
            return {"error": f"ไม่รู้จักช่วงเวลา '{period}' (ต้องเป็น: เช้า หรือ บ่าย)"}
        period_bounds = PERIOD_MAP[period]

    rows = supabase.table("teacher_unavailability").select("teacher_id, timeslot_id").execute().data
    teacher_name_by_id = {t["teacher_id"]: t.get("teacher_name") for t in load("teachers")}
    timeslot_by_id = {t["timeslot_id"]: t for t in load("timeslots")}

    result = []
    for row in rows:
        ts = timeslot_by_id.get(row["timeslot_id"])
        if not ts:
            continue
        if day_code and ts["day"] != day_code:
            continue
        if period_bounds and not (period_bounds[0] <= ts["start_time"] < period_bounds[1]):
            continue
        result.append({
            "teacher_name": teacher_name_by_id.get(row["teacher_id"], row["teacher_id"]),
            "day": ts["day"],
            "start_time": ts["start_time"],
            "end_time": ts["end_time"],
        })

    result.sort(key=lambda x: (x["teacher_name"], x["day"], x["start_time"]))
    return {"unavailable": result}


def _filter_timeslots(day: str = None, period: str = None):
    day_code = DAY_MAP.get(day.strip()) if day else None
    if day and not day_code:
        raise ValueError(f"ไม่รู้จักวัน '{day}' (ต้องเป็น: {', '.join(DAY_MAP.keys())})")

    period_bounds = PERIOD_MAP.get(period) if period else None
    if period and not period_bounds:
        raise ValueError(f"ไม่รู้จักช่วงเวลา '{period}' (ต้องเป็น: เช้า หรือ บ่าย)")

    timeslots = load("timeslots")
    return [
        t for t in timeslots
        if (not day_code or t["day"] == day_code)
        and (not period_bounds or period_bounds[0] <= t["start_time"] < period_bounds[1])
    ]


def list_available_rooms(day: str, period: str = None) -> dict:
    try:
        target_timeslots = _filter_timeslots(day, period)
    except ValueError as e:
        return {"error": str(e)}

    target_ids = {t["timeslot_id"] for t in target_timeslots}
    rooms = load("rooms")

    unavailable_rows = supabase.table("room_unavailability").select("room_id, timeslot_id").execute().data
    unavailable_by_room = {}
    for row in unavailable_rows:
        if row["timeslot_id"] in target_ids:
            unavailable_by_room.setdefault(row["room_id"], set()).add(row["timeslot_id"])

    # ห้องถือว่า "ว่าง" เฉพาะถ้าไม่ถูกตั้งไม่ว่างในคาบใดๆ ของช่วงที่ถามเลย
    available = [
        r["room_name"] for r in rooms
        if not unavailable_by_room.get(r["room_id"])
    ]

    return {"day": day, "period": period, "available_rooms": sorted(available)}


def list_available_teachers(day: str, period: str = None) -> dict:
    try:
        target_timeslots = _filter_timeslots(day, period)
    except ValueError as e:
        return {"error": str(e)}

    target_ids = {t["timeslot_id"] for t in target_timeslots}
    teachers = load("teachers")

    unavailable_rows = supabase.table("teacher_unavailability").select("teacher_id, timeslot_id").execute().data
    unavailable_by_teacher = {}
    for row in unavailable_rows:
        if row["timeslot_id"] in target_ids:
            unavailable_by_teacher.setdefault(row["teacher_id"], set()).add(row["timeslot_id"])

    available = [
        t["teacher_name"] for t in teachers
        if not unavailable_by_teacher.get(t["teacher_id"])
    ]

    return {"day": day, "period": period, "available_teachers": sorted(available)}


def get_subject_preferred_timeslots(subject_name: str) -> dict:
    """ดูว่าวิชา GENERAL นี้ล็อกคาบเวลาไว้ตรงไหนบ้าง (จาก subject_selected_preferred_timeslots)

    Args:
        subject_name: รหัสวิชาหรือชื่อวิชา

    Returns:
        dict มี key "locked_slots" เป็น list ของ {day, start_time, end_time}
        หรือ {"error": ...} ถ้าหาวิชาไม่เจอ
    """
    try:
        subject_id = _find_subject_id(subject_name)
    except ValueError as e:
        return {"error": str(e)}

    rows = (
        supabase.table("subject_selected")
        .select("subject_selected_preferred_timeslots(timeslot_id)")
        .eq("subject_id", subject_id)
        .execute()
        .data
    )

    timeslot_ids = {
        ts["timeslot_id"]
        for r in rows
        for ts in (r.get("subject_selected_preferred_timeslots") or [])
    }
    timeslot_by_id = {t["timeslot_id"]: t for t in load("timeslots")}

    slots = [
        {"day": timeslot_by_id[tid]["day"], "start_time": timeslot_by_id[tid]["start_time"], "end_time": timeslot_by_id[tid]["end_time"]}
        for tid in timeslot_ids
        if tid in timeslot_by_id
    ]
    slots.sort(key=lambda s: (s["day"], s["start_time"]))

    return {"subject_id": subject_id, "locked_slots": slots}