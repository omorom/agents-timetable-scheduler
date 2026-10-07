"""
query_data_people.py
Tool สำหรับ "อ่าน" ข้อมูลเจาะจงเกี่ยวกับคน — 🎓 นิสิต (group) และ 👨‍🏫 อาจารย์ (teacher)
แยกออกมาจาก query_data.py เพื่อไม่ให้ไฟล์นั้นยาวเกินไป
ใช้ helper (_find_* / slot_of / group_label) และ supabase/load ร่วมกับ query_data.py

แก้ไขล่าสุด:
  - tool ฝั่งนิสิตรับชื่อกลุ่มแบบไม่ระบุสาขาได้ ("ปี 3") แล้วคืนผลแยกทั้ง CS และ IT ให้เอง
    Agent ไม่ต้องเดารหัสกลุ่ม (Y3 / IT-Y3) อีกต่อไป
  - เพิ่ม get_group_student_count — ตอบ "ปี X มีนิสิตกี่คน" ได้ใน 1 call พร้อมผลรวม
  - ชั่วโมงเรียน/สอน คิดจากความยาวคาบจริง (ปัดเป็นชั่วโมง) — เดิมใช้ ชั่วโมงจบ − ชั่วโมงเริ่ม
    ทำให้คาบ 08:00-08:50 ถูกนับเป็น 0 ชั่วโมง
  - วันในผลลัพธ์เป็นภาษาไทย และเรียงจันทร์ → ศุกร์
"""

from .get_data import supabase, load
from .query_data import (
    _find_group_ids,
    _find_teacher_id,
    group_label,
    slot_of,
    slot_sort_key,
)


def _slot_hours(ts: dict) -> int:
    """ความยาวคาบเป็นชั่วโมง (ปัดเศษ) เช่น 08:00-08:50 = 1 ชม."""
    def minutes(t: str) -> int:
        h, m = t[:5].split(":")
        return int(h) * 60 + int(m)
    return max(1, round((minutes(ts["end_time"]) - minutes(ts["start_time"])) / 60))


def _schedule_rows(column: str, value) -> list[dict]:
    """ดึงตารางที่จัดแล้ว (timetable_ai) ตามคอลัมน์ที่กำหนด แล้วแปลงเป็นรายการอ่านง่าย
    dedupe ด้วย (session_id, timeslot_id) — 1 session ที่มีหลายอาจารย์/หลายกลุ่ม
    ถูก insert ไว้หลายแถวใน timetable_ai ถ้าไม่ dedupe วิชาเดียวกันจะโผล่ซ้ำ"""
    rows = (
        supabase.table("timetable_ai")
        .select("session_id, subject_id, room_id, timeslot_id")
        .eq(column, value)
        .execute()
        .data
    )
    subjects_by_id = {s["subject_id"]: s for s in load("subjects")}
    rooms_by_id = {r["room_id"]: r["room_name"] for r in load("rooms")}
    timeslots_by_id = {t["timeslot_id"]: t for t in load("timeslots")}

    seen = set()
    schedule = []
    for r in rows:
        key = (r["session_id"], r["timeslot_id"])
        if key in seen:
            continue
        seen.add(key)
        ts = timeslots_by_id.get(r["timeslot_id"])
        if not ts:
            continue
        schedule.append({
            "subject_id": r["subject_id"],
            "name_thai": subjects_by_id.get(r["subject_id"], {}).get("name_thai"),
            **slot_of(ts),
            "room_name": rooms_by_id.get(r["room_id"], r["room_id"]),
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
    """ดูตารางเรียนเต็มทั้งสัปดาห์ของกลุ่มนิสิต/ชั้นปีที่ระบุ

    Args:
        group_name: เช่น "IT ปี 1", "คอม ปี 2" หรือ "ปี 3" (ไม่ระบุสาขา = คืนทั้ง CS และ IT แยกกัน)

    Returns:
        สำเร็จ: dict มี "groups" เป็น list ของ {group, schedule}
                schedule เป็น list ของ {subject_id, name_thai, day, start_time, end_time, room_name}
        ผิดพลาด: dict ที่มี key "error"
    """
    try:
        groups = _find_group_ids(group_name)
    except ValueError as e:
        return {"error": str(e)}

    return {
        "groups": [
            {"group": group_label(g), "schedule": _schedule_rows("group_id", g["group_id"])}
            for g in groups
        ]
    }


def get_group_free_slots(group_name: str) -> dict:
    """ดูว่ากลุ่มนิสิต/ชั้นปีนี้ว่างช่วงไหนบ้าง (ไม่มีวิชาเรียนเลย)

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
        free = [slot_of(t) for t in timeslots if t["timeslot_id"] not in busy_ids]
        free.sort(key=slot_sort_key)
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
    """ดูตารางสอนเต็มทั้งสัปดาห์ของอาจารย์ที่ระบุ

    Args:
        teacher_name: ชื่ออาจารย์ (ค้นหาแบบ partial match ได้)

    Returns:
        สำเร็จ: dict มี key "schedule" เป็น list ของ {subject_id, name_thai, day, start_time, end_time, room_name}
        ผิดพลาด: dict ที่มี key "error"
    """
    try:
        teacher_id = _find_teacher_id(teacher_name)
    except ValueError as e:
        return {"error": str(e)}

    return {"teacher_id": teacher_id, "schedule": _schedule_rows("teacher_id", teacher_id)}


def get_teacher_free_slots(teacher_name: str) -> dict:
    """ดูว่าอาจารย์คนนี้ 'ว่างจริง' ช่วงไหนบ้าง (ตัดทั้งคาบที่ตั้งไม่ว่างไว้
    และคาบที่สอนวิชาอื่นอยู่แล้ว — ต่างจาก get_teacher_unavailability ที่ดูแค่ที่ตั้งไม่ว่าง)

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

    free = [slot_of(t) for t in load("timeslots") if t["timeslot_id"] not in busy_ids]
    free.sort(key=slot_sort_key)

    return {"teacher_id": teacher_id, "free_slots": free}


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