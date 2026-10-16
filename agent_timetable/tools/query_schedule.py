"""
query_schedule.py
Tool ตารางเรียน/ตารางสอนแบบ "ตัวเดียวกรองได้ทุกเงื่อนไข" — get_schedule()

ใช้แทน tool ตาราง 4 ตัวเดิม (get_teacher_schedule / get_group_schedule / get_room_schedule /
get_subject_current_schedule) ตัวเดียวตอบได้ทั้ง
  - "ตารางสอนอาจารย์ X"                         -> teacher="X"
  - "IT ปี 2 เรียนวันพุธอะไรบ้าง"                  -> group="IT ปี 2", day="พุธ"
  - "ห้อง SC1-212 ช่วงบ่ายมีใครใช้บ้าง"              -> room="SC1-212", period="บ่าย"
  - "วิชาเลือกของ CS ปี 3 อยู่วันไหน"               -> group="CS ปี 3", subject_type="วิชาเลือก"
  - "อาจารย์ X สอนปฏิบัติห้องไหนบ้าง"               -> teacher="X", session_type="ปฏิบัติ"
  - "254251 เรียนวันไหน ห้องไหน"                  -> subject="254251"

ทำไมรวมเป็นตัวเดียว: คำอธิบาย tool ทุกตัวถูกส่งไปกับทุกข้อความแชท ยิ่ง tool น้อยยิ่งประหยัด token
และตัวที่รับเงื่อนไขผสมได้ ตอบคำถามที่ไม่ได้คาดไว้ล่วงหน้าได้มากกว่า tool เฉพาะทางหลายตัว
การกรอง/รวมคาบทำใน Python ทั้งหมด AI ได้แค่ผลที่สรุปแล้ว
"""

from .get_data import supabase, load
from .query_data import (
    _find_group_ids,
    _find_room_id,
    _find_subject_id,
    _find_teacher_id,
    _in_bounds,
    _major_of,
    _parse_days,
    _parse_period_bounds,
    _year_of,
    day_th,
    merge_slots,
    slot_sort_key,
)
from .query_data_subjects import SUBJECT_TYPE_LABEL, _parse_subject_type

SESSION_TYPE_TH = {"LECTURE": "บรรยาย", "LAB": "ปฏิบัติ"}

# ผลลัพธ์ยาวเกินนี้ตัดท้าย (กัน token บาน ถ้าผู้ใช้ถามกว้างมาก เช่น "ตารางทั้งหมดวันจันทร์")
MAX_ITEMS = 60


def _parse_session_type(text: str | None) -> str | None:
    """'บรรยาย' / 'lecture' -> LECTURE, 'ปฏิบัติ' / 'แล็บ' / 'lab' -> LAB (None = ทั้งสองแบบ)"""
    if not text:
        return None
    t = str(text).strip().lower()
    if any(w in t for w in ("ปฏิบัติ", "แล็บ", "แลป", "lab")):
        return "LAB"
    if any(w in t for w in ("บรรยาย", "lecture", "lec", "ทฤษฎี")):
        return "LECTURE"
    if any(w in t for w in ("ทั้งหมด", "ทุกแบบ", "all")):
        return None
    raise ValueError(f"ไม่รู้จักประเภทคาบ '{text}' (ใช้ได้: บรรยาย, ปฏิบัติ หรือไม่ระบุ = ทั้งสองแบบ)")


def _row_session_type(row: dict) -> str | None:
    """LECTURE / LAB ของแถวในตาราง — ใช้คอลัมน์ session_type ถ้ามี ไม่งั้นดูจาก session_id"""
    raw = str(row.get("session_type") or "").upper()
    if raw in SESSION_TYPE_TH:
        return raw
    sid = str(row.get("session_id") or "").upper()
    if "-LAB" in sid:
        return "LAB"
    if "-LEC" in sid:
        return "LECTURE"
    return None


def get_schedule(
    teacher: str = None,
    group: str = None,
    room: str = None,
    subject: str = None,
    day: str = None,
    period: str = None,
    subject_type: str = None,
    session_type: str = None,
) -> dict:
    """ดูตารางเรียน/ตารางสอนที่จัดแล้ว กรองได้หลายเงื่อนไขพร้อมกัน (ใส่อย่างน้อย 1 เงื่อนไข)
    ใช้กับทุกคำถามเรื่อง "ใคร/กลุ่มไหน/ห้องไหน/วิชาไหน เรียน-สอน วันไหน เวลาไหน"
    คาบติดกันของวิชาเดียวกันรวมเป็นช่วงเดียว เวลาจบแสดงแบบหน้าเว็บ (:50)

    Args:
        teacher: ชื่ออาจารย์ (บางส่วนก็ได้) เช่น "ลิมปพัทธ์"
        group: ชั้นปี/สาขา เช่น "IT ปี 2", "คอม ปี 1", "ปี 3" (ไม่ระบุสาขา = ทั้ง CS และ IT)
        room: รหัสห้อง เช่น "SC1-212"
        subject: รหัสวิชาหรือชื่อวิชา เช่น "254251"
        day: วัน เช่น "จันทร์", "จันทร์-พุธ", "ทุกวัน"
        period: "เช้า", "บ่าย" หรือช่วงเวลา เช่น "13:00-15:00"
        subject_type: "วิชาเลือก", "วิชาบังคับ", "ศึกษาทั่วไป"
        session_type: "บรรยาย" หรือ "ปฏิบัติ"

    Returns:
        สำเร็จ: {"filters", "count", "schedule"} schedule เป็น list ของ
            {day, start_time, end_time, subject_id, name_thai, session_type, room_name, groups, teachers}
            (field ที่ตรงกับเงื่อนไขที่ถามอยู่แล้วจะถูกตัดออก เช่น ถามตามห้องจะไม่มี room_name)
            ถ้ายาวเกิน จะมี "truncated": true และ "total"
        ผิดพลาด: dict ที่มี key "error"
    """
    if not any([teacher, group, room, subject, day, period, subject_type, session_type]):
        return {"error": "กรุณาระบุอย่างน้อย 1 เงื่อนไข เช่น อาจารย์ ชั้นปี ห้อง วิชา หรือวัน"}

    # ── แปลงคำของผู้ใช้เป็นค่าจริง ──
    try:
        teacher_id = _find_teacher_id(teacher) if teacher else None
        groups = _find_group_ids(group) if group else None
        room_id = _find_room_id(room) if room else None
        subject_id = _find_subject_id(subject) if subject else None
        day_codes = _parse_days(day) if day else None
        bounds = _parse_period_bounds(period) if period else None
        type_code = _parse_subject_type(subject_type) if subject_type else None
        sess_code = _parse_session_type(session_type) if session_type else None
    except ValueError as e:
        return {"error": str(e)}

    # ── ดึงเฉพาะแถวที่เกี่ยว (กรองที่ฐานข้อมูลก่อน ลดข้อมูลที่ต้องโหลด) ──
    query = supabase.table("timetable_ai").select("*")
    if teacher_id:
        query = query.eq("teacher_id", teacher_id)
    if room_id is not None:
        query = query.eq("room_id", room_id)
    if subject_id:
        query = query.eq("subject_id", subject_id)
    if groups:
        query = query.in_("group_id", [g["group_id"] for g in groups])
    try:
        rows = query.execute().data
    except Exception as e:
        return {"error": f"อ่านตารางไม่ได้: {e}"}

    timeslots_by_id = {t["timeslot_id"]: t for t in load("timeslots")}
    subjects_by_id = {s["subject_id"]: s for s in load("subjects")}
    rooms_by_id = {r["room_id"]: r.get("room_name") for r in load("rooms")}
    teacher_name_by_id = {t["teacher_id"]: t.get("teacher_name") for t in load("teachers")}
    groups_by_id = {g["group_id"]: g for g in load("groups")}

    def short_group(gid) -> str:
        g = groups_by_id.get(gid, {"group_id": gid})
        return f"{_major_of(g)} ปี {_year_of(g) or '?'}"

    # ── รวมแถวของ session เดียวกัน (1 session ที่มีหลายอาจารย์/กลุ่มถูก insert หลายแถว) ──
    sessions: dict = {}
    for r in rows:
        ts = timeslots_by_id.get(r.get("timeslot_id"))
        if not ts:
            continue
        if day_codes and ts["day"] not in day_codes:
            continue
        if bounds and not _in_bounds(ts["start_time"], bounds):
            continue
        sess = _row_session_type(r)
        if sess_code and sess != sess_code:
            continue
        subj = subjects_by_id.get(r.get("subject_id"), {})
        if type_code and str(subj.get("subject_type") or "").upper() != type_code:
            continue

        key = (r.get("session_id"), r.get("room_id"))
        s = sessions.setdefault(key, {
            "subject_id": r.get("subject_id"),
            "session_type": sess,
            "room_id": r.get("room_id"),
            "timeslots": {},
            "groups": set(),
            "teachers": set(),
        })
        s["timeslots"][r["timeslot_id"]] = ts
        if r.get("group_id"):
            s["groups"].add(r["group_id"])
        if r.get("teacher_id"):
            s["teachers"].add(r["teacher_id"])

    # field ที่ไม่ต้องส่งซ้ำ เพราะผู้ใช้ระบุมาแล้ว (ประหยัด token)
    single_group = groups is not None and len(groups) == 1
    asked_teacher_name = teacher_name_by_id.get(teacher_id) if teacher_id else None

    schedule = []
    for s in sessions.values():
        subj = subjects_by_id.get(s["subject_id"], {})
        for slot in merge_slots(list(s["timeslots"].values())):
            item = {
                **slot,
                "subject_id": s["subject_id"],
                "name_thai": subj.get("name_thai"),
                "session_type": SESSION_TYPE_TH.get(s["session_type"]),
            }
            if room_id is None:
                item["room_name"] = rooms_by_id.get(s["room_id"], s["room_id"])
            if not single_group:
                item["groups"] = sorted(short_group(g) for g in s["groups"])
            names = sorted(teacher_name_by_id.get(t) or str(t) for t in s["teachers"])
            if asked_teacher_name:
                co = [n for n in names if n != asked_teacher_name]
                if co:
                    item["co_teachers"] = co
            else:
                item["teachers"] = names
            if subject_type is None and subj.get("subject_type"):
                item["subject_type"] = SUBJECT_TYPE_LABEL.get(str(subj["subject_type"]).upper())
            schedule.append(item)

    schedule.sort(key=slot_sort_key)

    # สรุปเงื่อนไขที่ใช้จริงเป็นภาษาคน (ให้ AI ทวนกับผู้ใช้ได้ถูก)
    filters = {}
    if asked_teacher_name:
        filters["อาจารย์"] = asked_teacher_name
    if groups:
        filters["กลุ่ม"] = ", ".join(short_group(g["group_id"]) for g in groups)
    if room_id is not None:
        filters["ห้อง"] = rooms_by_id.get(room_id, room)
    if subject_id:
        filters["วิชา"] = f"{subject_id} {subjects_by_id.get(subject_id, {}).get('name_thai') or ''}".strip()
    if day_codes:
        filters["วัน"] = ", ".join(day_th(d) for d in day_codes)
    if period:
        filters["ช่วงเวลา"] = period
    if type_code:
        filters["ประเภทวิชา"] = SUBJECT_TYPE_LABEL.get(type_code)
    if sess_code:
        filters["ประเภทคาบ"] = SESSION_TYPE_TH[sess_code]

    result = {"filters": filters, "count": len(schedule), "schedule": schedule[:MAX_ITEMS]}
    if len(schedule) > MAX_ITEMS:
        result["truncated"] = True
        result["total"] = len(schedule)
    return result