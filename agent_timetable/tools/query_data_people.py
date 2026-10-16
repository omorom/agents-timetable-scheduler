"""
query_data_people.py
Tool สำหรับ "อ่าน" ข้อมูลเจาะจงเกี่ยวกับคน — 🎓 นิสิต (group) และ 👨‍🏫 อาจารย์ (teacher)
แยกออกมาจาก query_data.py เพื่อไม่ให้ไฟล์นั้นยาวเกินไป
ใช้ helper (_find_* / slot_of / merge_slots / group_label) และ supabase/load ร่วมกับ query_data.py

แก้ไขล่าสุด:
  - tool ฝั่งนิสิตรับชื่อกลุ่มแบบไม่ระบุสาขาได้ ("ปี 3") แล้วคืนผลแยกทั้ง CS และ IT ให้เอง
    Agent ไม่ต้องเดารหัสกลุ่ม (Y3 / IT-Y3) อีกต่อไป
  - เพิ่ม get_group_student_count — ตอบ "ปี X มีนิสิตกี่คน" ได้ใน 1 call พร้อมผลรวม
  - ชั่วโมงเรียน/สอน คิดจากความยาวคาบจริง (ปัดเป็นชั่วโมง) — เดิมใช้ ชั่วโมงจบ − ชั่วโมงเริ่ม
    ทำให้คาบ 08:00-08:50 ถูกนับเป็น 0 ชั่วโมง
  - วันในผลลัพธ์เป็นภาษาไทย และเรียงจันทร์ → ศุกร์
  - [ใหม่] ตารางเรียน/ตารางสอน: คาบที่ติดกันของวิชาเดียวกันรวมเป็นช่วงเดียว
    (15:00-15:50 + 16:00-16:50 -> 15:00-16:50) และเวลาจบแสดงแบบหน้าเว็บ (:50)
  - [ใหม่] ตารางเรียน/ตารางสอนบอกประเภทคาบ (บรรยาย/ปฏิบัติ) ตารางสอนบอกกลุ่มนิสิต
    ตารางเรียนบอกอาจารย์ผู้สอน
  - [ใหม่] เวลาว่างของกลุ่ม/อาจารย์ รวมคาบติดกันเป็นช่วงเดียว
"""

from .get_data import supabase, load
from .query_data import (
    _find_group_ids,
    _find_teacher_id,
    _major_of,
    _year_of,
    group_label,
    merge_slots,
    slot_sort_key,
)

SESSION_TYPE_TH = {"LECTURE": "บรรยาย", "LAB": "ปฏิบัติ"}


def _short_group_label(group_id) -> str:
    """[ใหม่] ชื่อกลุ่มแบบสั้นสำหรับรายการในตาราง: 'IT ปี 2' (ชื่อเต็มยาวเกินเมื่อซ้ำทุกบรรทัด)"""
    group = next((g for g in load("groups") if g["group_id"] == group_id), {"group_id": group_id})
    return f"{_major_of(group)} ปี {_year_of(group) or '?'}"


def _slot_hours(ts: dict) -> int:
    """ความยาวคาบเป็นชั่วโมง (ปัดเศษ) เช่น 08:00-08:50 = 1 ชม."""
    def minutes(t: str) -> int:
        h, m = t[:5].split(":")
        return int(h) * 60 + int(m)
    return max(1, round((minutes(ts["end_time"]) - minutes(ts["start_time"])) / 60))


def _session_type(row: dict) -> str | None:
    """ประเภทคาบ (บรรยาย/ปฏิบัติ) — ใช้คอลัมน์ session_type ถ้ามี ไม่งั้นดูจาก session_id
    (session_id รูปแบบ SS12-LEC / SS12-LAB / SS12-LAB-1)"""
    raw = str(row.get("session_type") or "").upper()
    if raw in SESSION_TYPE_TH:
        return SESSION_TYPE_TH[raw]
    sid = str(row.get("session_id") or "").upper()
    if "-LAB" in sid:
        return SESSION_TYPE_TH["LAB"]
    if "-LEC" in sid:
        return SESSION_TYPE_TH["LECTURE"]
    return None


def _schedule_rows(column: str, value) -> list[dict]:
    """ดึงตารางที่จัดแล้ว (timetable_ai) ตามคอลัมน์ที่กำหนด แล้วแปลงเป็นรายการอ่านง่าย

    - 1 session ที่มีหลายอาจารย์/หลายกลุ่มถูก insert ไว้หลายแถว -> รวมเป็นรายการเดียว
      แล้วเก็บรายชื่ออาจารย์/กลุ่มทั้งหมดไว้แทน (เดิม dedupe ทิ้ง)
    - [ใหม่] คาบที่ติดกันในวันเดียวกันของ session เดียวกันรวมเป็นช่วงเดียว
      เช่น 15:00-15:50 + 16:00-16:50 -> 15:00-16:50
    """
    rows = supabase.table("timetable_ai").select("*").eq(column, value).execute().data
    subjects_by_id = {s["subject_id"]: s for s in load("subjects")}
    rooms_by_id = {r["room_id"]: r["room_name"] for r in load("rooms")}
    timeslots_by_id = {t["timeslot_id"]: t for t in load("timeslots")}
    teacher_name_by_id = {t["teacher_id"]: t.get("teacher_name") for t in load("teachers")}

    sessions: dict = {}
    for r in rows:
        ts = timeslots_by_id.get(r["timeslot_id"])
        if not ts:
            continue
        # คีย์รวมห้องด้วย กันกรณี session เดียวกันลงคนละห้องคนละวัน
        key = (r.get("session_id"), r.get("room_id"))
        s = sessions.setdefault(key, {
            "subject_id": r.get("subject_id"),
            "session_type": _session_type(r),
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

    schedule = []
    for s in sessions.values():
        subject = subjects_by_id.get(s["subject_id"], {})
        for slot in merge_slots(list(s["timeslots"].values())):
            schedule.append({
                "subject_id": s["subject_id"],
                "name_thai": subject.get("name_thai"),
                "session_type": s["session_type"],
                **slot,
                "room_name": rooms_by_id.get(s["room_id"], s["room_id"]),
                "groups": sorted(_short_group_label(g) for g in s["groups"]),
                "teachers": sorted(teacher_name_by_id.get(t) or str(t) for t in s["teachers"]),
            })
    schedule.sort(key=slot_sort_key)
    return schedule


# ═══════════════════════════════════════════════════════════════
# 🎓 นิสิต (group)
# ═══════════════════════════════════════════════════════════════

def get_group_student_count(group_name: str = "") -> dict:
    """ดูจำนวนนิสิตของกลุ่ม/ชั้นปี

    Args:
        group_name: เช่น "ปี 3" (ไม่ระบุสาขา = ทั้ง CS และ IT), "IT ปี 3", "คอม ปี 1",
                    "IT" (ทุกชั้นปีของ IT) หรือเว้นว่าง = ทุกกลุ่ม

    Returns:
        dict มี "groups" เป็น list ของ {group, total_students} และ "total" (ผลรวม)
        หรือ {"error": ...}
    """
    try:
        groups = _find_group_ids(group_name)
    except ValueError as e:
        return {"error": str(e)}

    items = [{"group": group_label(g), "total_students": g.get("total_students") or 0} for g in groups]
    return {"groups": items, "total": sum(i["total_students"] for i in items)}


def get_group_schedule(group_name: str) -> dict:
    """ดูตารางเรียนเต็มทั้งสัปดาห์ของกลุ่มนิสิต/ชั้นปีที่ระบุ (คาบติดกันของวิชาเดียวกันรวมเป็นช่วงเดียว)

    Args:
        group_name: เช่น "IT ปี 1", "คอม ปี 2" หรือ "ปี 3" (ไม่ระบุสาขา = คืนทั้ง CS และ IT แยกกัน)

    Returns:
        สำเร็จ: dict มี "groups" เป็น list ของ {group, schedule}
                schedule เป็น list ของ {subject_id, name_thai, session_type (บรรยาย/ปฏิบัติ),
                day, start_time, end_time, room_name, teachers}
        ผิดพลาด: dict ที่มี key "error"
    """
    try:
        groups = _find_group_ids(group_name)
    except ValueError as e:
        return {"error": str(e)}

    result = []
    for g in groups:
        schedule = _schedule_rows("group_id", g["group_id"])
        for item in schedule:
            item.pop("groups", None)   # ถามตารางของกลุ่มนี้อยู่แล้ว ไม่ต้องบอกกลุ่มซ้ำ
        result.append({"group": group_label(g), "schedule": schedule})
    return {"groups": result}


def get_group_free_slots(group_name: str) -> dict:
    """ดูว่ากลุ่มนิสิต/ชั้นปีนี้ว่างช่วงไหนบ้าง (ไม่มีวิชาเรียนเลย คาบติดกันรวมเป็นช่วงเดียว)

    Args:
        group_name: เช่น "IT ปี 1" หรือ "ปี 3" (ไม่ระบุสาขา = คืนทั้ง CS และ IT แยกกัน)

    Returns:
        สำเร็จ: dict มี "groups" เป็น list ของ {group, free_slots}
                free_slots เป็น list ของ {day, start_time, end_time}
        ผิดพลาด: dict ที่มี key "error"
    """
    try:
        groups = _find_group_ids(group_name)
    except ValueError as e:
        return {"error": str(e)}

    group_ids = [g["group_id"] for g in groups]
    rows = supabase.table("timetable_ai").select("group_id, timeslot_id").in_("group_id", group_ids).execute().data
    timeslots = load("timeslots")

    result = []
    for g in groups:
        busy_ids = {r["timeslot_id"] for r in rows if r["group_id"] == g["group_id"]}
        free = merge_slots([t for t in timeslots if t["timeslot_id"] not in busy_ids])
        result.append({"group": group_label(g), "free_slots": free})

    return {"groups": result}


def get_group_workload(group_name: str = "") -> dict:
    """ดูว่ากลุ่มนิสิต/ชั้นปีเรียนกี่ชั่วโมงต่อสัปดาห์ พร้อมเทียบกับทุกกลุ่ม

    Args:
        group_name: เช่น "IT ปี 1" หรือ "ปี 3" (ไม่ระบุสาขา = ทั้ง CS และ IT)
                    เว้นว่างได้ถ้าถามว่า "กลุ่มไหนเรียนหนักสุด"

    Returns:
        dict มี "groups" (ชั่วโมงของกลุ่มที่ถาม) และ "all_groups_hours"
        (ทุกกลุ่ม เรียงจากมากไปน้อย) หรือ {"error": ...}
    """
    try:
        groups = _find_group_ids(group_name)
    except ValueError as e:
        return {"error": str(e)}

    rows = supabase.table("timetable_ai").select("group_id, timeslot_id").execute().data
    timeslots_by_id = {t["timeslot_id"]: t for t in load("timeslots")}

    # dedupe ด้วย (group_id, timeslot_id) — section คู่ขนานที่เรียนพร้อมกันคนละห้อง
    # นิสิตกลุ่มเดียวกันไม่ได้เรียน 2 ห้องพร้อมกันจริง นับ 1 ครั้งต่อคาบ
    seen = set()
    hours_by_group: dict[str, int] = {}
    for r in rows:
        gid = r.get("group_id")
        ts = timeslots_by_id.get(r["timeslot_id"])
        if not gid or not ts or (gid, r["timeslot_id"]) in seen:
            continue
        seen.add((gid, r["timeslot_id"]))
        hours_by_group[gid] = hours_by_group.get(gid, 0) + _slot_hours(ts)

    all_groups = load("groups")
    return {
        "groups": [
            {"group": group_label(g), "hours_per_week": hours_by_group.get(g["group_id"], 0)}
            for g in groups
        ],
        "all_groups_hours": sorted(
            [{"group": group_label(g), "hours_per_week": hours_by_group.get(g["group_id"], 0)} for g in all_groups],
            key=lambda x: -x["hours_per_week"],
        ),
    }


# ═══════════════════════════════════════════════════════════════
# 👨‍🏫 อาจารย์ — ตารางสอนเต็ม / ว่างจริง (รวมคาบสอน) / โหลดงานสอน
# ═══════════════════════════════════════════════════════════════

def get_teacher_schedule(teacher_name: str) -> dict:
    """ดูตารางสอนเต็มทั้งสัปดาห์ของอาจารย์ที่ระบุ (คาบติดกันของวิชาเดียวกันรวมเป็นช่วงเดียว)

    Args:
        teacher_name: ชื่ออาจารย์ (ค้นหาแบบ partial match ได้)

    Returns:
        สำเร็จ: dict มี key "schedule" เป็น list ของ {subject_id, name_thai, session_type (บรรยาย/ปฏิบัติ),
                day, start_time, end_time, room_name, groups (กลุ่มนิสิตที่สอน), co_teachers (อาจารย์ที่สอนร่วม)}
        ผิดพลาด: dict ที่มี key "error"
    """
    try:
        teacher_id = _find_teacher_id(teacher_name)
    except ValueError as e:
        return {"error": str(e)}

    teacher_name_full = next(
        (t.get("teacher_name") for t in load("teachers") if t["teacher_id"] == teacher_id), None
    )
    schedule = _schedule_rows("teacher_id", teacher_id)
    for item in schedule:
        # ถามตารางของอาจารย์คนนี้อยู่แล้ว เหลือไว้เฉพาะอาจารย์ที่สอนร่วม (ถ้ามี)
        item["co_teachers"] = [t for t in item.pop("teachers", []) if t != teacher_name_full]

    return {"teacher_id": teacher_id, "schedule": schedule}


def get_teacher_free_slots(teacher_name: str) -> dict:
    """ดูว่าอาจารย์คนนี้ 'ว่างจริง' ช่วงไหนบ้าง (ตัดทั้งคาบที่ตั้งไม่ว่างไว้
    และคาบที่สอนวิชาอื่นอยู่แล้ว — ต่างจาก get_teacher_unavailability ที่ดูแค่ที่ตั้งไม่ว่าง)
    คาบติดกันรวมเป็นช่วงเดียว

    Args:
        teacher_name: ชื่ออาจารย์ (ค้นหาแบบ partial match ได้)

    Returns:
        สำเร็จ: dict มี key "free_slots" เป็น list ของ {day, start_time, end_time}
        ผิดพลาด: dict ที่มี key "error"
    """
    try:
        teacher_id = _find_teacher_id(teacher_name)
    except ValueError as e:
        return {"error": str(e)}

    unavail_rows = supabase.table("teacher_unavailability").select("timeslot_id").eq("teacher_id", teacher_id).execute().data
    teaching_rows = supabase.table("timetable_ai").select("timeslot_id").eq("teacher_id", teacher_id).execute().data
    busy_ids = {r["timeslot_id"] for r in unavail_rows} | {r["timeslot_id"] for r in teaching_rows}

    free = merge_slots([t for t in load("timeslots") if t["timeslot_id"] not in busy_ids])

    return {"teacher_id": teacher_id, "free_slots": free}


def list_teachers_workload() -> dict:
    """[ใหม่] สรุปภาระสอนของอาจารย์ "ทุกคน" ในครั้งเดียว ใช้ตอบคำถามแบบ
    "อาจารย์คนไหนไม่มีคาบสอน", "ใครสอนเยอะที่สุด", "อาจารย์แต่ละคนสอนกี่ชั่วโมง"

    แยกอาจารย์ที่ไม่มีคาบสอนเป็น 2 แบบ เพราะแก้คนละที่:
      - no_subjects: ไม่ได้ถูกผูกสอนวิชาไหนเลยในภาคเรียนนี้ (ต้องไปผูกอาจารย์ให้วิชา)
      - assigned_but_not_scheduled: ผูกสอนวิชาแล้ว แต่ยังไม่มีคาบในตาราง
        (ยังไม่ได้จัดตาราง หรือวิชานั้นจัดไม่ได้)

    Returns:
        dict มี "teacher_count", "no_subjects", "assigned_but_not_scheduled" (รายชื่อ)
        และ "teaching" เป็น list ของ {teacher, hours_per_week, subject_count} เรียงจากสอนมากไปน้อย
    """
    teachers = load("teachers")
    timeslots_by_id = {t["timeslot_id"]: t for t in load("timeslots")}

    # ชั่วโมงสอนในตารางที่จัดแล้ว — dedupe (teacher, session, timeslot) กันนับซ้ำ
    # เพราะ session เดียวที่มีหลายกลุ่มถูก insert ไว้หลายแถว
    rows = supabase.table("timetable_ai").select("teacher_id, session_id, timeslot_id").execute().data
    seen = set()
    hours: dict = {}
    for r in rows:
        tid = r.get("teacher_id")
        ts = timeslots_by_id.get(r.get("timeslot_id"))
        key = (tid, r.get("session_id"), r.get("timeslot_id"))
        if not tid or not ts or key in seen:
            continue
        seen.add(key)
        hours[tid] = hours.get(tid, 0) + _slot_hours(ts)

    # วิชาที่ถูกผูกให้สอนในภาคเรียนนี้ (นับรหัสวิชาไม่ซ้ำ)
    links = (
        supabase.table("subject_selected_teachers")
        .select("teacher_id, subject_selected(subject_id)")
        .execute()
        .data
    )
    subjects: dict = {}
    for link in links:
        sid = (link.get("subject_selected") or {}).get("subject_id")
        if link.get("teacher_id") and sid:
            subjects.setdefault(link["teacher_id"], set()).add(sid)

    no_subjects, not_scheduled, teaching = [], [], []
    for t in teachers:
        tid, name = t["teacher_id"], t.get("teacher_name") or str(t["teacher_id"])
        h, n = hours.get(tid, 0), len(subjects.get(tid, ()))
        if h:
            teaching.append({"teacher": name, "hours_per_week": h, "subject_count": n})
        elif n:
            not_scheduled.append(name)
        else:
            no_subjects.append(name)

    teaching.sort(key=lambda x: -x["hours_per_week"])
    return {
        "teacher_count": len(teachers),
        "no_subjects": sorted(no_subjects),
        "assigned_but_not_scheduled": sorted(not_scheduled),
        "teaching": teaching,
    }


def get_teacher_workload(teacher_name: str) -> dict:
    """ดูว่าอาจารย์คนนี้สอนกี่วิชา กี่ชั่วโมงรวมต่อสัปดาห์

    Args:
        teacher_name: ชื่ออาจารย์ (ค้นหาแบบ partial match ได้)

    Returns:
        สำเร็จ: dict มี key "subject_count", "hours_per_week", "subjects" (รายชื่อวิชาที่สอน)
        ผิดพลาด: dict ที่มี key "error"
    """
    try:
        teacher_id = _find_teacher_id(teacher_name)
    except ValueError as e:
        return {"error": str(e)}

    rows = supabase.table("timetable_ai").select("session_id, subject_id, timeslot_id").eq("teacher_id", teacher_id).execute().data
    timeslots_by_id = {t["timeslot_id"]: t for t in load("timeslots")}
    subjects_by_id = {s["subject_id"]: s for s in load("subjects")}

    # dedupe ด้วย (session_id, timeslot_id) ก่อนนับชั่วโมง — กัน session ที่ผูกกับหลาย
    # group (เช่น LECTURE รวมของหลาย section) ถูกนับชั่วโมงสอนซ้ำเกินจริง
    seen = set()
    hours = 0
    subject_ids_seen = set()
    for r in rows:
        key = (r.get("session_id"), r["timeslot_id"])
        if key in seen:
            continue
        seen.add(key)
        ts = timeslots_by_id.get(r["timeslot_id"])
        if not ts:
            continue
        hours += _slot_hours(ts)
        subject_ids_seen.add(r["subject_id"])

    return {
        "teacher_id": teacher_id,
        "subject_count": len(subject_ids_seen),
        "hours_per_week": hours,
        "subjects": [subjects_by_id.get(sid, {}).get("name_thai", sid) for sid in subject_ids_seen],
    }