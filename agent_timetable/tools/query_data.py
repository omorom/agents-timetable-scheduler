"""
query_data.py
Tool + helper สำหรับ "อ่าน" ข้อมูลเจาะจง (query) แยกจาก get_data.py ที่โหลดข้อมูลดิบทั้งตาราง
และแยกจาก mutate_data.py ที่ทำหน้าที่ "เขียน" ข้อมูลเท่านั้น

ไฟล์นี้มี 2 กลุ่ม:
  1. Helper (_find_* / _parse_* / day_th / group_label) — ใช้ร่วมกันทุกไฟล์
     (query_data_people.py, query_data_spaces.py, mutate_data.py)
     เพื่อแปลง "ชื่อ/คำอธิบายของผู้ใช้" เป็น id จริง และแปลงผลลัพธ์กลับเป็นข้อความที่คนอ่านได้
  2. Tool (get_* / list_*) — ให้ Agent เรียกดูว่าอาจารย์/ห้องไม่ว่างช่วงไหนบ้าง ฯลฯ

แก้ไขล่าสุด (ย้าย logic จาก prompt มาไว้ในโค้ด — ประหยัด token และแม่นกว่า):
  - วัน: รับ "ทุกวัน", "จันทร์-พุธ", "จันทร์ถึงศุกร์", "จันทร์, พุธ" ได้ในค่าเดียว (_parse_days)
  - ช่วงเวลา: รับ "เช้า", "บ่าย", "ทั้งวัน", "ช่วงเช้า", "08:00-12:00" ได้ (_parse_period_bounds)
  - ผลลัพธ์คืนวันเป็นภาษาไทย และเรียงจันทร์ → ศุกร์ถูกต้อง
    (เดิมคืน MON/TUE แล้ว sort ตามตัวอักษร ทำให้ FRI ขึ้นก่อน MON)
  - กลุ่มนิสิต: รู้จัก CS/IT จากคำที่ผู้ใช้พิมพ์ (คอม, ไอที, CS, IT ...) และ
    _find_group_ids คืน "ทั้ง 2 สาขา" เมื่อไม่ระบุสาขา (ใช้กับ tool อ่าน)
    ส่วน _find_group_id (ใช้กับ tool เขียน) ยังบังคับให้เจอกลุ่มเดียว
    เดิม "ชั้นปีที่ 3" เหลือคำว่า "ที่" ค้างไปกรอง ทำให้หากลุ่มไม่เจอ / เลือกผิดสาขา
  - ผลลัพธ์แสดงชื่อกลุ่มเป็น "วิทยาการคอมพิวเตอร์ (CS) ปี 3" แทน group_id / COMSCI
"""

from .get_data import supabase, load
import re

# ═══════════════════════════════════════════════════════════════
# วัน / ช่วงเวลา
# ═══════════════════════════════════════════════════════════════

DAY_ORDER = ["MON", "TUE", "WED", "THU", "FRI"]

DAY_TH = {
    "MON": "จันทร์",
    "TUE": "อังคาร",
    "WED": "พุธ",
    "THU": "พฤหัสบดี",
    "FRI": "ศุกร์",
}

# แปลงวันภาษาไทย/อังกฤษ -> ตัวย่อที่เก็บจริงใน timeslots.day
DAY_MAP = {
    "จันทร์": "MON",
    "อังคาร": "TUE",
    "พุธ": "WED",
    "พฤหัส": "THU",
    "พฤหัสบดี": "THU",
    "ศุกร์": "FRI",
    "mon": "MON", "monday": "MON",
    "tue": "TUE", "tuesday": "TUE",
    "wed": "WED", "wednesday": "WED",
    "thu": "THU", "thursday": "THU",
    "fri": "FRI", "friday": "FRI",
}

ALL_DAY_WORDS = ("ทุกวัน", "ทั้งสัปดาห์", "ทั้งอาทิตย์", "ทุกวันทำการ", "every day", "everyday")

# ขอบเขตเวลา เช้า/บ่าย โดยแยกจากพักเที่ยง (12:00-13:00) อย่างชัดเจน
PERIOD_MAP = {
    "เช้า": ("00:00:00", "12:00:00"),   # ก่อนเที่ยง
    "บ่าย": ("13:00:00", "23:59:59"),   # หลังพักเที่ยง
}

# index สำหรับเรียงวัน — รับได้ทั้งรหัส (MON) และชื่อไทย (จันทร์)
_DAY_INDEX = {code: i for i, code in enumerate(DAY_ORDER)}
_DAY_INDEX.update({DAY_TH[code]: i for i, code in enumerate(DAY_ORDER)})


def day_th(day_code: str) -> str:
    """MON -> จันทร์ (ถ้าไม่รู้จักคืนค่าเดิม)"""
    return DAY_TH.get(day_code, day_code)


def hhmm(t: str | None) -> str | None:
    """'08:00:00' -> '08:00' ให้ผลลัพธ์อ่านง่ายและสั้นลง (ประหยัด token ตอนส่งกลับให้ LLM)"""
    return t[:5] if t else t


def slot_sort_key(s: dict):
    """เรียง dict ที่มี key day/start_time ตามวันจันทร์ → ศุกร์ แล้วตามเวลา"""
    return (_DAY_INDEX.get(s.get("day"), 9), s.get("start_time") or "")


def slot_of(ts: dict) -> dict:
    """แปลง timeslot ดิบจากตาราง -> {day (ไทย), start_time, end_time} สำหรับส่งกลับให้ Agent"""
    return {"day": day_th(ts["day"]), "start_time": hhmm(ts["start_time"]), "end_time": hhmm(ts["end_time"])}


def _day_code(word: str) -> str | None:
    w = (word or "").strip().lower().replace("วัน", "").strip(" .")
    if not w:
        return None
    if w.upper() in DAY_ORDER:
        return w.upper()
    return DAY_MAP.get(w)


def _parse_days(text: str | None) -> list[str] | None:
    """แปลงข้อความวันของผู้ใช้ -> list รหัสวัน (เรียงจันทร์ → ศุกร์)
    รองรับ: "จันทร์", "ทุกวัน", "จันทร์-พุธ", "จันทร์ถึงศุกร์", "จันทร์, พุธ", "จันทร์ และ พุธ"
    คืน None ถ้าไม่ได้ระบุวันมาเลย (ให้ผู้เรียกตัดสินเองว่าหมายถึงทุกวันหรือ error)
    """
    if text is None:
        return None
    t = str(text).strip()
    if not t:
        return None

    if any(w in t.lower() for w in ALL_DAY_WORDS):
        return list(DAY_ORDER)

    # ช่วงวัน เช่น "จันทร์-พุธ", "จันทร์ ถึง ศุกร์"
    range_parts = re.split(r"\s*(?:-|–|ถึง|to)\s*", t)
    if len(range_parts) == 2:
        a, b = _day_code(range_parts[0]), _day_code(range_parts[1])
        if a and b:
            i, j = DAY_ORDER.index(a), DAY_ORDER.index(b)
            if i <= j:
                return DAY_ORDER[i:j + 1]

    # หลายวันคั่นด้วย , / และ หรือช่องว่าง
    codes = []
    for part in re.split(r"\s*(?:,|/|และ|\s)\s*", t):
        if not part.replace("วัน", "").strip():
            continue  # เช่น "วัน จันทร์" แยกแล้วเหลือคำว่า "วัน" เดี่ยวๆ
        code = _day_code(part)
        if not code:
            valid = ", ".join(DAY_TH[c] for c in DAY_ORDER)
            raise ValueError(f"ไม่รู้จักวัน '{part}' (ใช้ได้: {valid} หรือ 'ทุกวัน')")
        if code not in codes:
            codes.append(code)
    return sorted(codes, key=DAY_ORDER.index) or None


def _to_hms(h: str, m: str | None) -> str:
    return f"{int(h):02d}:{(m or '00'):0>2}:00"


def _parse_period_bounds(text: str | None) -> list[tuple[str, str]] | None:
    """แปลงข้อความช่วงเวลาของผู้ใช้ -> list ของขอบเขต (start, end) ที่ใช้กรองคาบ
    รองรับ: "เช้า", "บ่าย", "ช่วงเช้า", "ทั้งวัน", "08:00-12:00", "8.00-12.00", "13:00 ถึง 17:00"
    คืน None ถ้าไม่ได้ระบุ (= ทุกช่วง)
    """
    if text is None:
        return None
    t = str(text).strip()
    if not t:
        return None

    if any(w in t for w in ("ทั้งวัน", "ทุกช่วง", "ตลอดวัน")):
        return [PERIOD_MAP["เช้า"], PERIOD_MAP["บ่าย"]]

    m = re.search(r"(\d{1,2})(?:[:.](\d{2}))?\s*(?:-|–|ถึง|to)\s*(\d{1,2})(?:[:.](\d{2}))?", t)
    if m:
        return [(_to_hms(m.group(1), m.group(2)), _to_hms(m.group(3), m.group(4)))]

    bounds = []
    if "เช้า" in t or "morning" in t.lower():
        bounds.append(PERIOD_MAP["เช้า"])
    if "บ่าย" in t or "afternoon" in t.lower():
        bounds.append(PERIOD_MAP["บ่าย"])
    if bounds:
        return bounds

    raise ValueError(f"ไม่รู้จักช่วงเวลา '{text}' (ใช้ได้: เช้า, บ่าย, ทั้งวัน หรือช่วงเวลาเช่น 08:00-12:00)")


def _in_bounds(start_time: str, bounds: list[tuple[str, str]] | None) -> bool:
    if not bounds:
        return True
    return any(lo <= start_time < hi for lo, hi in bounds)


def _filter_timeslots(day: str = None, period: str = None) -> list[dict]:
    """คืน timeslot ที่ตรงกับวัน/ช่วงเวลา (ไม่ระบุ = ทุกวัน/ทุกช่วง)"""
    day_codes = _parse_days(day)
    bounds = _parse_period_bounds(period)
    return [
        t for t in load("timeslots")
        if (not day_codes or t["day"] in day_codes) and _in_bounds(t["start_time"], bounds)
    ]


def _find_timeslot_ids(days: str, period: str = None) -> list[int]:
    """หา timeslot_id ทั้งหมดของวัน + ช่วงเวลา (ใช้กับการตั้ง/ยกเลิกไม่ว่าง)
    days บังคับต้องระบุ (รับ "ทุกวัน" / ช่วงวัน / หลายวันได้)
    period ไม่ระบุ = ทั้งวัน
    """
    if _parse_days(days) is None:
        raise ValueError("กรุณาระบุวัน (เช่น 'จันทร์', 'จันทร์-พุธ' หรือ 'ทุกวัน')")
    matched = [t["timeslot_id"] for t in _filter_timeslots(days, period)]
    if not matched:
        raise ValueError(f"ไม่พบคาบเวลาสำหรับวัน {days} ช่วง {period or 'ทั้งวัน'}")
    return matched


def _find_timeslot_ids_by_range(day: str, start_time: str, end_time: str) -> list[int]:
    """หา timeslot_id ทั้งหมดที่ 'ทับซ้อน' กับช่วงเวลาที่ระบุ (ไม่ใช่แค่ label เช้า/บ่าย)
    ใช้หลัก overlap: timeslot.start_time < end_time AND timeslot.end_time > start_time
    day รับได้หลายวัน/ทุกวันเหมือน _parse_days
    """
    day_codes = _parse_days(day)
    if not day_codes:
        raise ValueError("กรุณาระบุวัน")

    start_norm = start_time if len(start_time) > 5 else f"{start_time}:00"
    end_norm = end_time if len(end_time) > 5 else f"{end_time}:00"

    matched = [
        t["timeslot_id"] for t in load("timeslots")
        if t["day"] in day_codes and t["start_time"] < end_norm and t["end_time"] > start_norm
    ]

    if not matched:
        raise ValueError(f"ไม่พบคาบเวลาที่ทับซ้อนกับช่วง {start_time}-{end_time} ในวัน {day}")

    return matched


# ═══════════════════════════════════════════════════════════════
# กลุ่มนิสิต (CS: Y1-Y4, IT: IT-Y1-IT-Y4)
# ═══════════════════════════════════════════════════════════════

MAJOR_LABEL = {
    "CS": "วิทยาการคอมพิวเตอร์ (CS)",
    "IT": "เทคโนโลยีสารสนเทศ (IT)",
}

# คำที่ผู้ใช้อาจพิมพ์แทนสาขา — เช็ค IT ก่อน CS
_MAJOR_PATTERNS = [
    ("IT", re.compile(r"(?<![a-z])it(?![a-z])|ไอที|เทคโนโลยีสารสนเทศ|เทคโนฯ|สารสนเทศ|information", re.IGNORECASE)),
    ("CS", re.compile(r"(?<![a-z])cs(?![a-z])|comsci|com sci|คอม|วิทยาการคอมพิวเตอร์|วิทย์คอม|computer science", re.IGNORECASE)),
]


def _major_of(group: dict) -> str:
    major = (group.get("major") or "").upper()
    if major in MAJOR_LABEL:
        return major
    return "IT" if str(group.get("group_id", "")).upper().startswith("IT-") else "CS"


def _year_of(group: dict) -> str | None:
    m = re.search(r"Y(\d+)$", str(group.get("group_id", "")), re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"\d+", group.get("group_name") or "")
    return m.group() if m else None


def group_label(group_or_id) -> str:
    """แปลงกลุ่ม (dict หรือ group_id) -> 'วิทยาการคอมพิวเตอร์ (CS) ปี 3'
    ใช้ตอนส่งผลลัพธ์กลับให้ Agent แทน group_id / ชื่อดิบอย่าง COMSCI-YEAR-3"""
    group = group_or_id
    if not isinstance(group_or_id, dict):
        group = next((g for g in load("groups") if g["group_id"] == group_or_id), {"group_id": group_or_id})
    return f"{MAJOR_LABEL[_major_of(group)]} ปี {_year_of(group) or '?'}"


def _detect_major(text: str) -> str | None:
    for major, pattern in _MAJOR_PATTERNS:
        if pattern.search(text or ""):
            return major
    return None


def _find_group_ids(group_name: str | None) -> list[dict]:
    """หากลุ่มนิสิตจากข้อความของผู้ใช้ คืน list ของ group dict (อาจหลายกลุ่ม)
      - "IT ปี 3", "ไอที ปี 3", "IT-Y3"   -> [IT ปี 3]
      - "CS ปี 3", "คอม ปี 3", "Y3"       -> [CS ปี 3]
      - "ปี 3", "ชั้นปีที่ 3"              -> [CS ปี 3, IT ปี 3]   (ไม่ระบุสาขา = ทั้งสองสาขา)
      - "IT", "สาขาไอที"                  -> IT ทุกชั้นปี
      - "" / None / "ทุกชั้นปี"             -> ทุกกลุ่ม
    """
    groups = load("groups")
    text = (group_name or "").strip()

    if not text or any(w in text for w in ("ทุกชั้นปี", "ทุกกลุ่ม", "ทั้งหมด")):
        return sorted(groups, key=lambda g: (_major_of(g), _year_of(g) or ""))

    # ตรงกับ group_id เป๊ะ (เช่น Agent ส่ง "IT-Y3" หรือ "Y3" มาตรงๆ)
    exact = [g for g in groups if str(g["group_id"]).lower() == text.lower()]
    if exact:
        return exact

    year_match = re.search(r"\d+", text)
    year = year_match.group() if year_match else None
    major = _detect_major(text)

    matches = groups
    if year:
        matches = [g for g in matches if _year_of(g) == year]
    if major:
        matches = [g for g in matches if _major_of(g) == major]
    if not year and not major:
        keyword = text.lower()
        matches = [g for g in groups if keyword in (g.get("group_name") or "").lower()]

    if not matches:
        available = ", ".join(group_label(g) for g in groups)
        raise ValueError(f"ไม่พบกลุ่มนิสิต '{group_name}' ในระบบ (กลุ่มที่มี: {available})")

    return sorted(matches, key=lambda g: (_major_of(g), _year_of(g) or ""))


def _find_group_id(group_name: str) -> str:
    """เหมือน _find_group_ids แต่ต้องเจอ "กลุ่มเดียว" เท่านั้น — ใช้กับการเขียนข้อมูล
    (เช่น แก้จำนวนนิสิต) ที่ห้ามเดาสาขาเอง"""
    matches = _find_group_ids(group_name)
    if len(matches) > 1:
        names = ", ".join(group_label(g) for g in matches)
        raise ValueError(f"'{group_name}' ตรงกับหลายกลุ่ม: {names} กรุณาระบุสาขา (CS หรือ IT)")
    return matches[0]["group_id"]


# ═══════════════════════════════════════════════════════════════
# อาจารย์ / วิชา / ห้อง
# ═══════════════════════════════════════════════════════════════

def _find_teacher_id(teacher_name: str) -> str:
    """หา teacher_id จากชื่อ (ค้นหาแบบ substring match กับ teacher_name ที่เก็บในตาราง)"""
    teachers = load("teachers")
    keyword = teacher_name.strip().lower()
    # ตัดคำนำหน้าที่ผู้ใช้มักพิมพ์ติดมา (อาจารย์ / อ. / ดร.) ออก ให้เหลือแค่ชื่อ
    keyword = re.sub(r"^((อาจารย์|อ\.|ดร\.|ผศ\.|รศ\.|ศ\.)\s*)+", "", keyword).strip() or keyword

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

    exact = [s for s in subjects if (s.get("subject_id") or "").lower() == keyword]
    if exact:
        return exact[0]["subject_id"]

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


# ═══════════════════════════════════════════════════════════════
# Tool: อ่านข้อมูลเจาะจง (ให้ Agent เรียกโดยตรง)
# ═══════════════════════════════════════════════════════════════

def get_subject_sections(subject_name: str) -> dict:
    """ดูว่าวิชานี้เปิดสอนกี่เซค แต่ละเซคใครสอนบ้าง กลุ่มไหนเรียน

    Args:
        subject_name: รหัสวิชาหรือชื่อวิชา (เช่น "254251" หรือ "โครงสร้างข้อมูล")

    Returns:
        สำเร็จ: dict มี key "sections" เป็น list ของ {section_id, teachers, groups}
        ผิดพลาด: dict ที่มี key "error"
    """
    try:
        subject_id = _find_subject_id(subject_name)
    except ValueError as e:
        return {"error": str(e)}

    rows = (
        supabase.table("subject_selected")
        .select(
            "id, "
            "subject_selected_teachers(teacher(teacher_name)), "
            "subject_selected_groups(group_id)"
        )
        .eq("subject_id", subject_id)
        .execute()
        .data
    )

    sections = [
        {
            "section_id": r["id"],
            "teachers": [
                t["teacher"]["teacher_name"]
                for t in (r.get("subject_selected_teachers") or [])
                if t.get("teacher")
            ],
            "groups": [group_label(g["group_id"]) for g in (r.get("subject_selected_groups") or [])],
        }
        for r in rows
    ]

    return {"subject_id": subject_id, "section_count": len(sections), "sections": sections}


def get_teacher_subjects(teacher_name: str) -> dict:
    """ดูว่าอาจารย์คนนี้สอนวิชาอะไรบ้าง

    Args:
        teacher_name: ชื่ออาจารย์ (ค้นหาแบบ partial match ได้)

    Returns:
        สำเร็จ: dict มี key "subjects" เป็น list ของ {subject_id, name_thai}
        ผิดพลาด: dict ที่มี key "error"
    """
    try:
        teacher_id = _find_teacher_id(teacher_name)
    except ValueError as e:
        return {"error": str(e)}

    rows = (
        supabase.table("subject_selected_teachers")
        .select("subject_selected(id, subjects(subject_id, name_thai))")
        .eq("teacher_id", teacher_id)
        .execute()
        .data
    )

    # dedupe — อาจารย์สอนวิชาเดียวกันหลาย section ไม่ต้องแสดงชื่อวิชาซ้ำ
    seen = set()
    subjects_taught = []
    for r in rows:
        subj = (r.get("subject_selected") or {}).get("subjects")
        if not subj or subj["subject_id"] in seen:
            continue
        seen.add(subj["subject_id"])
        subjects_taught.append({"subject_id": subj["subject_id"], "name_thai": subj["name_thai"]})

    return {"teacher_id": teacher_id, "subjects": subjects_taught}


def _slots_from_ids(timeslot_ids: set) -> list[dict]:
    slots = [slot_of(t) for t in load("timeslots") if t["timeslot_id"] in timeslot_ids]
    slots.sort(key=slot_sort_key)
    return slots


def get_teacher_unavailability(teacher_name: str) -> dict:
    """ดูว่าอาจารย์คนนี้ตั้งค่าไม่ว่างไว้ช่วงไหนบ้าง (คืนเป็นวัน+เวลาที่อ่านง่าย)

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
    return {"teacher_id": teacher_id, "unavailable_slots": _slots_from_ids({r["timeslot_id"] for r in rows})}


def get_room_unavailability(room_name: str) -> dict:
    """ดูว่าห้องเรียนนี้ตั้งค่าไม่ว่างไว้ช่วงไหนบ้าง (คืนเป็นวัน+เวลาที่อ่านง่าย)

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
    return {"room_id": room_id, "unavailable_slots": _slots_from_ids({r["timeslot_id"] for r in rows})}


def _list_unavailable(table: str, id_col: str, name_by_id: dict, name_key: str, day, period) -> dict:
    try:
        target = {t["timeslot_id"]: t for t in _filter_timeslots(day, period)}
    except ValueError as e:
        return {"error": str(e)}

    rows = supabase.table(table).select(f"{id_col}, timeslot_id").execute().data
    result = []
    for row in rows:
        ts = target.get(row["timeslot_id"])
        if not ts:
            continue
        result.append({name_key: name_by_id.get(row[id_col], row[id_col]), **slot_of(ts)})

    result.sort(key=lambda x: (x[name_key] or "", *slot_sort_key(x)))
    return {"unavailable": result}


def list_unavailable_rooms(day: str = None, period: str = None) -> dict:
    """ดูว่ามีห้องไหนตั้งค่าไม่ว่างไว้บ้าง กรองตามวัน/ช่วงเวลาได้ (ไม่ระบุ = ทุกวันทุกช่วง)
    ใช้เมื่อผู้ใช้รู้วัน/ช่วงเวลา แต่ไม่รู้ชื่อห้อง เช่น "มีห้องไหนไม่ว่างช่วงบ่ายบ้าง"

    Args:
        day: วัน เช่น "จันทร์", "จันทร์-พุธ", "ทุกวัน" (ไม่ระบุ = ทุกวัน)
        period: "เช้า", "บ่าย", "ทั้งวัน" หรือ "08:00-12:00" (ไม่ระบุ = ทุกช่วง)

    Returns:
        dict มี key "unavailable" เป็น list ของ {room_name, day, start_time, end_time}
        หรือ {"error": ...} ถ้า day/period ที่ระบุไม่ถูกต้อง
    """
    room_name_by_id = {r["room_id"]: r.get("room_name") for r in load("rooms")}
    return _list_unavailable("room_unavailability", "room_id", room_name_by_id, "room_name", day, period)


def list_unavailable_teachers(day: str = None, period: str = None) -> dict:
    """ดูว่ามีอาจารย์คนไหนตั้งค่าไม่ว่างไว้บ้าง กรองตามวัน/ช่วงเวลาได้ (ไม่ระบุ = ทุกวันทุกช่วง)
    ใช้เมื่อผู้ใช้รู้วัน/ช่วงเวลา แต่ไม่รู้ชื่ออาจารย์ เช่น "วันอังคารช่วงเช้า อาจารย์คนไหนไม่ว่างบ้าง"

    Args:
        day: วัน เช่น "อังคาร", "ทุกวัน" (ไม่ระบุ = ทุกวัน)
        period: "เช้า", "บ่าย", "ทั้งวัน" หรือ "08:00-12:00" (ไม่ระบุ = ทุกช่วง)

    Returns:
        dict มี key "unavailable" เป็น list ของ {teacher_name, day, start_time, end_time}
        หรือ {"error": ...} ถ้า day/period ที่ระบุไม่ถูกต้อง
    """
    teacher_name_by_id = {t["teacher_id"]: t.get("teacher_name") for t in load("teachers")}
    return _list_unavailable("teacher_unavailability", "teacher_id", teacher_name_by_id, "teacher_name", day, period)


def list_available_rooms(
    day: str,
    period: str = None,
    start_time: str = None,
    end_time: str = None,
    room_type: str = None,
) -> dict:
    """ดูว่ามีห้องไหนว่างจริงในวัน/ช่วงเวลาที่ถาม (ไม่ถูกตั้งไม่ว่าง และไม่มีวิชาที่จัดไว้ในช่วงนั้น)
    กรองตามประเภทห้องได้ เช่น ห้อง LAB

    Args:
        day: วัน เช่น "ศุกร์" หรือ "จันทร์-พุธ"
        period: "เช้า", "บ่าย", "ทั้งวัน" หรือ "15:00-17:00" (ไม่ระบุ = ทั้งวัน)
        start_time: เวลาเริ่ม "HH:MM" (ใช้คู่กับ end_time แทน period ได้)
        end_time: เวลาจบ "HH:MM"
        room_type: ประเภทห้อง เช่น "LAB" (ไม่ระบุ = ทุกประเภท)

    Returns:
        dict มี "available_rooms" (รายชื่อห้องที่ว่าง) และ "room_types" (ชื่อห้อง -> ประเภท)
        หรือ {"error": ...}
    """
    try:
        if start_time and end_time:
            target_ids = {str(i) for i in _find_timeslot_ids_by_range(day, start_time, end_time)}
        else:
            target_ids = {str(t["timeslot_id"]) for t in _filter_timeslots(day, period)}
    except ValueError as e:
        return {"error": str(e)}

    rooms = load("rooms")

    if room_type:
        wanted = room_type.strip().lower()
        known_types = sorted({str(r["room_type"]) for r in rooms if r.get("room_type")})
        rooms = [r for r in rooms if wanted in str(r.get("room_type") or "").lower()]
        if not rooms:
            return {
                "error": f"ไม่พบห้องประเภท '{room_type}' "
                        f"(ประเภทที่มีในระบบ: {', '.join(known_types) or 'ไม่พบข้อมูลประเภทห้อง'})"
            }

    try:
        unavailable_rows = supabase.table("room_unavailability").select("room_id, timeslot_id").execute().data
        scheduled_rows = supabase.table("timetable_ai").select("room_id, timeslot_id").execute().data
    except Exception as e:
        return {"error": f"อ่านข้อมูลห้องที่ไม่ว่าง/ตารางที่จัดไว้ไม่ได้: {e}"}

    # ห้องถือว่า "ไม่ว่าง" ถ้าถูกตั้งไม่ว่าง หรือมีวิชาจัดลงในคาบใดคาบหนึ่งของช่วงที่ถาม
    taken = {
        str(row["room_id"])
        for row in unavailable_rows + scheduled_rows
        if row.get("room_id") is not None and str(row.get("timeslot_id")) in target_ids
    }

    available = sorted(r["room_name"] for r in rooms if str(r["room_id"]) not in taken)
    available_set = set(available)
    return {
        "day": day, "period": period, "start_time": start_time, "end_time": end_time,
        "room_type": room_type,
        "available_rooms": available,
        "room_types": {r["room_name"]: r.get("room_type") for r in rooms if r["room_name"] in available_set},
    }


def list_available_teachers(day: str, period: str = None) -> dict:
    """ดูว่ามีอาจารย์คนไหนไม่ได้ตั้งค่าไม่ว่างไว้ในวัน/ช่วงเวลาที่ถาม

    Args:
        day: วัน เช่น "จันทร์" หรือ "จันทร์-พุธ"
        period: "เช้า", "บ่าย", "ทั้งวัน" หรือ "08:00-12:00" (ไม่ระบุ = ทั้งวัน)

    Returns:
        dict มี key "available_teachers" (รายชื่ออาจารย์) หรือ {"error": ...}
    """
    try:
        target_ids = {t["timeslot_id"] for t in _filter_timeslots(day, period)}
    except ValueError as e:
        return {"error": str(e)}

    unavailable_rows = supabase.table("teacher_unavailability").select("teacher_id, timeslot_id").execute().data
    busy_teachers = {row["teacher_id"] for row in unavailable_rows if row["timeslot_id"] in target_ids}

    available = [t["teacher_name"] for t in load("teachers") if t["teacher_id"] not in busy_teachers]
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

    return {"subject_id": subject_id, "locked_slots": _slots_from_ids(timeslot_ids)}