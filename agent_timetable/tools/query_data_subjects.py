"""
query_data_subjects.py
Tool อ่านข้อมูล "รายวิชาที่กลุ่มนิสิตเรียน" แยกตามประเภทวิชา (subjects.subject_type)
  ELECTIVE = วิชาเลือก, CORE = วิชาแกน (บังคับ), GENERAL = ศึกษาทั่วไป

ใช้ helper กลุ่มนิสิตจาก query_data.py (_find_group_ids / group_label) เหมือน tool อื่น
"""

from .get_data import supabase
from .query_data import _find_group_ids, group_label

SUBJECT_TYPE_LABEL = {
    "CORE": "วิชาแกน (บังคับ)",
    "ELECTIVE": "วิชาเลือก",
    "GENERAL": "วิชาศึกษาทั่วไป",
}

# คำที่ผู้ใช้อาจพิมพ์แทนประเภทวิชา — เช็ควิชาเลือกก่อน (คำว่า "วิชาเลือก" มีคำว่า "วิชา" ปนอยู่)
_SUBJECT_TYPE_WORDS = [
    ("ELECTIVE", ("elective", "วิชาเลือก", "เลือก", "เสรี")),
    ("GENERAL", ("general", "ศึกษาทั่วไป", "ทั่วไป", "gen ed", "gened")),
    ("CORE", ("core", "บังคับ", "แกน", "วิชาเอก")),
]


def _parse_subject_type(text: str | None) -> str | None:
    """แปลงคำของผู้ใช้ -> ELECTIVE / CORE / GENERAL (None = ทุกประเภท)"""
    if text is None:
        return None
    t = str(text).strip().lower()
    if not t or any(w in t for w in ("ทั้งหมด", "ทุกประเภท", "all")):
        return None
    if t.upper() in SUBJECT_TYPE_LABEL:
        return t.upper()
    if t == "ge":
        return "GENERAL"
    for code, words in _SUBJECT_TYPE_WORDS:
        if any(w in t for w in words):
            return code
    raise ValueError(f"ไม่รู้จักประเภทวิชา '{text}' (ใช้ได้: วิชาเลือก, วิชาบังคับ/แกน, ศึกษาทั่วไป หรือไม่ระบุ = ทุกประเภท)")


def get_group_subjects(group_name: str, subject_type: str = None) -> dict:
    """ดูว่ากลุ่มนิสิต (ชั้นปี/สาขา) เรียนวิชาอะไรบ้างในภาคเรียนนี้ กรองตามประเภทวิชาได้
    ใช้กับคำถามเช่น "CS ปี 3 เรียนวิชาเลือกกี่วิชา อะไรบ้าง", "ปี 2 มีวิชาบังคับอะไรบ้าง"

    Args:
        group_name: ชั้นปี/สาขาตามที่ผู้ใช้พิมพ์ เช่น "CS ปี 3", "คอม ปี 3", "IT ปี 1", "ปี 3"
            (ไม่ระบุสาขา = คืนทั้ง CS และ IT)
        subject_type: "วิชาเลือก", "วิชาบังคับ", "ศึกษาทั่วไป" หรือ "elective" / "core" / "general"
            (ไม่ระบุ = ทุกประเภท)

    Returns:
        สำเร็จ: dict มี "groups" เป็น list ของ {group, subject_count, subjects}
            แต่ละวิชาเป็น {subject_id, name_thai, type}
        ผิดพลาด: dict ที่มี key "error"
    """
    try:
        groups = _find_group_ids(group_name)
        type_code = _parse_subject_type(subject_type)
    except ValueError as e:
        return {"error": str(e)}

    try:
        rows = (
            supabase.table("subject_selected")
            .select("subject_id, subjects(subject_id, name_thai, subject_type), subject_selected_groups(group_id)")
            .execute()
            .data
        )
    except Exception as e:
        return {"error": f"อ่านข้อมูลรายวิชาที่เปิดสอนไม่ได้: {e}"}

    result = []
    for g in groups:
        seen = set()
        subjects = []
        for r in rows:
            group_ids = {x.get("group_id") for x in (r.get("subject_selected_groups") or [])}
            if g["group_id"] not in group_ids:
                continue
            subj = r.get("subjects") or {}
            sid = subj.get("subject_id") or r.get("subject_id")
            if not sid or sid in seen:
                continue  # วิชาเดียวกันหลาย section นับครั้งเดียว
            code = str(subj.get("subject_type") or "").upper()
            if type_code and code != type_code:
                continue
            seen.add(sid)
            subjects.append({
                "subject_id": sid,
                "name_thai": subj.get("name_thai"),
                "type": SUBJECT_TYPE_LABEL.get(code, code or "ไม่ระบุประเภท"),
            })
        subjects.sort(key=lambda s: s["subject_id"])
        result.append({"group": group_label(g), "subject_count": len(subjects), "subjects": subjects})

    return {
        "subject_type": SUBJECT_TYPE_LABEL.get(type_code, "ทุกประเภท"),
        "groups": result,
    }