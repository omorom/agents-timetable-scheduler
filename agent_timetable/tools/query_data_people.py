"""
query_data_people.py
Tool สำหรับ "อ่าน" ข้อมูลเจาะจงเกี่ยวกับคน — 🎓 นิสิต (group) และ 👨‍🏫 อาจารย์ (teacher)
แยกออกมาจาก query_data.py เพื่อไม่ให้ไฟล์นั้นยาวเกินไป
ใช้ helper (_find_*) และ supabase/load ร่วมกับ query_data.py
"""

from .get_data import supabase, load
from .query_data import _find_group_id, _find_teacher_id


# ═══════════════════════════════════════════════════════════════
# 🎓 นิสิต (group) — ตารางเต็ม / ว่างช่วงไหน / ชม.รวมต่อสัปดาห์
# ═══════════════════════════════════════════════════════════════

def get_group_schedule(group_name: str) -> dict:
    """ดูตารางเรียนเต็มทั้งสัปดาห์ของกลุ่มนิสิต/ชั้นปีที่ระบุ

    Args:
        group_name: ชื่อกลุ่ม/ชั้นปี เช่น "IT ปี 1" (ค้นหาแบบ partial/เลขปี match ได้)

    Returns:
        สำเร็จ: dict มี key "schedule" เป็น list ของ {subject_id, name_thai, day, start_time, end_time, room_name}
        ผิดพลาด: dict ที่มี key "error"
    """
    try:
        group_id = _find_group_id(group_name)
    except ValueError as e:
        return {"error": str(e)}

    rows = supabase.table("timetable_ai").select("session_id, subject_id, room_id, timeslot_id").eq("group_id", group_id).execute().data
    subjects_by_id = {s["subject_id"]: s for s in load("subjects")}
    rooms_by_id = {r["room_id"]: r["room_name"] for r in load("rooms")}
    timeslots_by_id = {t["timeslot_id"]: t for t in load("timeslots")}

    # dedupe ด้วย (session_id, timeslot_id) — เพราะ 1 session ที่มีหลายอาจารย์
    # (team-teaching) ถูก insert ไว้หลายแถวใน timetable_ai (1 แถวต่อคู่ teacher x group
    # x timeslot ดู record_assignment() ใน assignment_store.py) ถ้าไม่ dedupe ตรงนี้
    # วิชาเดียวกัน ช่วงเวลาเดียวกัน จะโผล่ซ้ำกันหลายรอบเท่าจำนวนอาจารย์ที่สอนร่วม
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
        subject = subjects_by_id.get(r["subject_id"], {})
        schedule.append({
            "subject_id": r["subject_id"],
            "name_thai": subject.get("name_thai"),
            "day": ts["day"],
            "start_time": ts["start_time"],
            "end_time": ts["end_time"],
            "room_name": rooms_by_id.get(r["room_id"], r["room_id"]),
        })
    schedule.sort(key=lambda s: (s["day"], s["start_time"]))

    return {"group_id": group_id, "schedule": schedule}


def get_group_free_slots(group_name: str) -> dict:
    """ดูว่ากลุ่มนิสิต/ชั้นปีนี้ว่างช่วงไหนบ้าง (ไม่มีวิชาเรียนเลย)

    Args:
        group_name: ชื่อกลุ่ม/ชั้นปี เช่น "IT ปี 1"

    Returns:
        สำเร็จ: dict มี key "free_slots" เป็น list ของ {day, start_time, end_time}
        ผิดพลาด: dict ที่มี key "error"
    """
    try:
        group_id = _find_group_id(group_name)
    except ValueError as e:
        return {"error": str(e)}

    rows = supabase.table("timetable_ai").select("timeslot_id").eq("group_id", group_id).execute().data
    busy_ids = {r["timeslot_id"] for r in rows}

    timeslots = load("timeslots")
    free = [
        {"day": t["day"], "start_time": t["start_time"], "end_time": t["end_time"]}
        for t in timeslots
        if t["timeslot_id"] not in busy_ids
    ]
    free.sort(key=lambda s: (s["day"], s["start_time"]))

    return {"group_id": group_id, "free_slots": free}


def get_group_workload(group_name: str) -> dict:
    """ดูว่ากลุ่มนิสิต/ชั้นปีนี้เรียนกี่ชั่วโมงต่อสัปดาห์ พร้อมเทียบกับกลุ่มอื่นทั้งหมด

    Args:
        group_name: ชื่อกลุ่ม/ชั้นปี เช่น "IT ปี 1"

    Returns:
        สำเร็จ: dict มี key "hours_per_week" (ของกลุ่มนี้) และ "all_groups_hours"
                (เทียบทุกกลุ่ม เรียงจากมากไปน้อย)
        ผิดพลาด: dict ที่มี key "error"
    """
    try:
        group_id = _find_group_id(group_name)
    except ValueError as e:
        return {"error": str(e)}

    rows = supabase.table("timetable_ai").select("group_id, timeslot_id").execute().data
    timeslots_by_id = {t["timeslot_id"]: t for t in load("timeslots")}
    groups_by_id = {g["group_id"]: g.get("group_name") for g in load("groups")}

    # dedupe ด้วย (group_id, timeslot_id) เท่านั้น (ไม่รวม session_id) — เพราะบางวิชา
    # แบ่ง section สอนพร้อมกันหลายห้อง (parallel) ในเวลาเดียวกัน คนละ session_id แต่
    # นักศึกษากลุ่มเดียวกันไม่ได้เรียน 2 ห้องพร้อมกันจริง ถือว่า "ไม่ว่าง" แค่ 1 ครั้ง
    # ต่อ timeslot เท่านั้น (ใช้ logic เดียวกับ get_group_free_slots ที่ dedupe ด้วย
    # timeslot_id set อยู่แล้ว — เดิมรวม session_id เข้าไปด้วยทำให้นับชั่วโมงซ้ำเกินจริง)
    seen = set()
    hours_by_group: dict[str, float] = {}
    for r in rows:
        gid = r.get("group_id")
        ts = timeslots_by_id.get(r["timeslot_id"])
        if not gid or not ts:
            continue
        key = (gid, r["timeslot_id"])
        if key in seen:
            continue
        seen.add(key)
        h_start = int(ts["start_time"][:2])
        h_end = int(ts["end_time"][:2])
        hours_by_group[gid] = hours_by_group.get(gid, 0) + (h_end - h_start)

    all_groups_hours = sorted(
        [{"group_name": groups_by_id.get(gid, gid), "hours_per_week": h} for gid, h in hours_by_group.items()],
        key=lambda x: -x["hours_per_week"],
    )

    return {
        "group_id": group_id,
        "hours_per_week": hours_by_group.get(group_id, 0),
        "all_groups_hours": all_groups_hours,
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

    rows = supabase.table("timetable_ai").select("session_id, subject_id, room_id, timeslot_id").eq("teacher_id", teacher_id).execute().data
    subjects_by_id = {s["subject_id"]: s for s in load("subjects")}
    rooms_by_id = {r["room_id"]: r["room_name"] for r in load("rooms")}
    timeslots_by_id = {t["timeslot_id"]: t for t in load("timeslots")}

    # dedupe เหมือนกับ get_group_schedule — 1 session ที่มีหลาย group ผูกอยู่
    # (เช่น LECTURE รวมของหลาย section) ถูก insert ไว้หลายแถวต่อ group ใน timetable_ai
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
        subject = subjects_by_id.get(r["subject_id"], {})
        schedule.append({
            "subject_id": r["subject_id"],
            "name_thai": subject.get("name_thai"),
            "day": ts["day"],
            "start_time": ts["start_time"],
            "end_time": ts["end_time"],
            "room_name": rooms_by_id.get(r["room_id"], r["room_id"]),
        })
    schedule.sort(key=lambda s: (s["day"], s["start_time"]))

    return {"teacher_id": teacher_id, "schedule": schedule}


def get_teacher_free_slots(teacher_name: str) -> dict:
    """ดูว่าอาจารย์คนนี้ 'ว่างจริง' ช่วงไหนบ้าง (รวมทั้งคาบที่ตั้ง unavailability ไว้
    และคาบที่สอนวิชาอื่นอยู่แล้ว — ต่างจาก get_teacher_unavailability ที่ดูแค่
    unavailability อย่างเดียว)

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

    timeslots = load("timeslots")
    free = [
        {"day": t["day"], "start_time": t["start_time"], "end_time": t["end_time"]}
        for t in timeslots
        if t["timeslot_id"] not in busy_ids
    ]
    free.sort(key=lambda s: (s["day"], s["start_time"]))

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
        h_start = int(ts["start_time"][:2])
        h_end = int(ts["end_time"][:2])
        hours += (h_end - h_start)
        subject_ids_seen.add(r["subject_id"])

    return {
        "teacher_id": teacher_id,
        "subject_count": len(subject_ids_seen),
        "hours_per_week": hours,
        "subjects": [subjects_by_id.get(sid, {}).get("name_thai", sid) for sid in subject_ids_seen],
    }