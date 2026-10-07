"""
query_data_spaces.py
Tool สำหรับ "อ่าน" ข้อมูลเจาะจงเกี่ยวกับ 🏫 ห้องเรียน, 📚 วิชา (ส่วนเพิ่มเติม),
และ 📅 ตาราง (ภาพรวมทั้งระบบ)
แยกออกมาจาก query_data.py เพื่อไม่ให้ไฟล์นั้นยาวเกินไป
ใช้ helper (_find_* / slot_of / group_label) และ supabase/load ร่วมกับ query_data.py

แก้ไขล่าสุด: วันในผลลัพธ์เป็นภาษาไทยและเรียงจันทร์ → ศุกร์, ชื่อกลุ่มนิสิตแสดงเป็น
"วิทยาการคอมพิวเตอร์ (CS) ปี 3" แทน group_id ดิบ (Agent ไม่ต้องแปลงเองใน prompt)
"""

from .get_data import supabase, load
from .query_data import (
    _find_room_id,
    _find_subject_id,
    _find_timeslot_ids_by_range,
    group_label,
    slot_of,
    slot_sort_key,
)


# ═══════════════════════════════════════════════════════════════
# 🏫 ห้องเรียน — ตารางใช้งาน / ว่างช่วงไหน / สถิติการใช้งาน
# ═══════════════════════════════════════════════════════════════

def get_room_schedule(room_name: str) -> dict:
    """ดูว่าห้องเรียนนี้ตอนนี้มีวิชาอะไรอยู่บ้าง ช่วงไหนบ้าง (ตารางการใช้งานเต็ม)

    Args:
        room_name: รหัสห้อง เช่น "SC1-311"

    Returns:
        สำเร็จ: dict มี key "schedule" เป็น list ของ {subject_id, name_thai, day, start_time, end_time}
        ผิดพลาด: dict ที่มี key "error"
    """
    try:
        room_id = _find_room_id(room_name)
    except ValueError as e:
        return {"error": str(e)}

    rows = supabase.table("timetable_ai").select("session_id, subject_id, timeslot_id").eq("room_id", room_id).execute().data
    subjects_by_id = {s["subject_id"]: s for s in load("subjects")}
    timeslots_by_id = {t["timeslot_id"]: t for t in load("timeslots")}

    # dedupe ด้วย (session_id, timeslot_id) — session ที่มีหลายอาจารย์/กลุ่มผูกอยู่ ถูก insert ซ้ำหลายแถว
    seen = set()
    schedule = []
    for r in rows:
        key = (r.get("session_id"), r["timeslot_id"])
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
        })
    schedule.sort(key=slot_sort_key)

    return {"room_id": room_id, "schedule": schedule}


def get_room_free_slots(room_name: str) -> dict:
    """ดูว่าห้องเรียนนี้ว่างช่วงไหนบ้าง (ตัดทั้งคาบที่ตั้งไม่ว่างไว้ และคาบที่มีวิชาใช้อยู่แล้ว)

    Args:
        room_name: รหัสห้อง เช่น "SC1-311"

    Returns:
        สำเร็จ: dict มี key "free_slots" เป็น list ของ {day, start_time, end_time}
        ผิดพลาด: dict ที่มี key "error"
    """
    try:
        room_id = _find_room_id(room_name)
    except ValueError as e:
        return {"error": str(e)}

    unavail_rows = supabase.table("room_unavailability").select("timeslot_id").eq("room_id", room_id).execute().data
    used_rows = supabase.table("timetable_ai").select("timeslot_id").eq("room_id", room_id).execute().data
    busy_ids = {r["timeslot_id"] for r in unavail_rows} | {r["timeslot_id"] for r in used_rows}

    free = [slot_of(t) for t in load("timeslots") if t["timeslot_id"] not in busy_ids]
    free.sort(key=slot_sort_key)

    return {"room_id": room_id, "free_slots": free}


def get_room_usage_stats() -> dict:
    """ดูสถิติการใช้งานห้องเรียนทั้งหมด (ห้องไหนถูกใช้เยอะ/น้อยที่สุด กี่คาบ)

    Returns:
        dict มี key "usage" เป็น list ของ {room_name, slots_used} เรียงจากใช้เยอะไปน้อย
    """
    rows = supabase.table("timetable_ai").select("session_id, room_id, timeslot_id").execute().data
    room_name_by_id = {r["room_id"]: r["room_name"] for r in load("rooms")}

    # dedupe ด้วย (session_id, room_id, timeslot_id) — กันนับคาบซ้ำเกินจริง
    seen = set()
    count_by_room: dict[str, int] = {}
    for r in rows:
        rid = r.get("room_id")
        if not rid:
            continue
        key = (r.get("session_id"), rid, r["timeslot_id"])
        if key in seen:
            continue
        seen.add(key)
        count_by_room[rid] = count_by_room.get(rid, 0) + 1

    usage = sorted(
        [{"room_name": room_name_by_id.get(rid, rid), "slots_used": c} for rid, c in count_by_room.items()],
        key=lambda x: -x["slots_used"],
    )

    return {"usage": usage}


# ═══════════════════════════════════════════════════════════════
# 📚 วิชา — ตารางปัจจุบัน / เช็คย้ายได้ไหม
# ═══════════════════════════════════════════════════════════════

def get_subject_current_schedule(subject_name: str) -> dict:
    """ดูว่าวิชานี้ตอนนี้ถูกจัดอยู่วัน/เวลา/ห้องไหนบ้าง (ทุก section รวมกัน)

    Args:
        subject_name: รหัสวิชาหรือชื่อวิชา

    Returns:
        สำเร็จ: dict มี key "schedule" เป็น list ของ {session_type, section, day, start_time, end_time, room_name, teacher_name}
        ผิดพลาด: dict ที่มี key "error"
    """
    try:
        subject_id = _find_subject_id(subject_name)
    except ValueError as e:
        return {"error": str(e)}

    rows = supabase.table("timetable_ai").select("session_id, session_type, section, room_id, teacher_id, timeslot_id").eq("subject_id", subject_id).execute().data
    rooms_by_id = {r["room_id"]: r["room_name"] for r in load("rooms")}
    teachers_by_id = {t["teacher_id"]: t.get("teacher_name") for t in load("teachers")}
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
            "session_type": r["session_type"],
            "section": r.get("section"),
            **slot_of(ts),
            "room_name": rooms_by_id.get(r["room_id"], r["room_id"]),
            "teacher_name": teachers_by_id.get(r.get("teacher_id"), r.get("teacher_id")),
        })
    schedule.sort(key=slot_sort_key)

    return {"subject_id": subject_id, "schedule": schedule}


def check_move_feasibility(subject_name: str, day: str, start_time: str, end_time: str) -> dict:
    """เช็คว่าวิชานี้ย้ายไปวัน/เวลาที่ระบุได้ไหม โดยไม่ย้ายจริง
    เช็คจาก 3 อย่าง: อาจารย์ชน / กลุ่มนิสิตชน / ห้องเดิมชน

    Args:
        subject_name: รหัสวิชาหรือชื่อวิชา
        day: วัน เช่น "จันทร์"
        start_time: เวลาเริ่ม เช่น "15:00"
        end_time: เวลาสิ้นสุด เช่น "16:50"

    Returns:
        dict มี key "feasible" (bool) และ "reason" (ถ้า feasible=False อธิบายว่าติดอะไร)
        หรือ {"error": ...} ถ้าหาวิชา/วัน/เวลาไม่เจอ
    """
    try:
        subject_id = _find_subject_id(subject_name)
        target_ids = _find_timeslot_ids_by_range(day, start_time, end_time)
    except ValueError as e:
        return {"error": str(e)}

    current_rows = supabase.table("timetable_ai").select("subject_id, teacher_id, room_id, group_id, timeslot_id").execute().data
    my_rows = [r for r in current_rows if r["subject_id"] == subject_id]
    if not my_rows:
        return {"error": f"ไม่พบตารางปัจจุบันของวิชา {subject_id}"}

    my_teacher_ids = {r["teacher_id"] for r in my_rows if r.get("teacher_id")}
    my_group_ids = {r["group_id"] for r in my_rows if r.get("group_id")}
    my_room_ids = {r["room_id"] for r in my_rows if r.get("room_id")}

    target_id_set = set(target_ids)
    others = [r for r in current_rows if r["subject_id"] != subject_id and r["timeslot_id"] in target_id_set]
    subjects_by_id = {s["subject_id"]: s for s in load("subjects")}

    def _name(sid):
        return subjects_by_id.get(sid, {}).get("name_thai", sid)

    for r in others:
        if r.get("teacher_id") in my_teacher_ids:
            return {"feasible": False, "reason": f"อาจารย์สอนวิชา {_name(r['subject_id'])} อยู่แล้วในช่วงเวลานี้"}
    for r in others:
        if r.get("group_id") in my_group_ids:
            return {"feasible": False, "reason": f"{group_label(r['group_id'])} ติดเรียนวิชา {_name(r['subject_id'])} อยู่แล้วในช่วงเวลานี้"}
    for r in others:
        if r.get("room_id") in my_room_ids:
            return {"feasible": False, "reason": f"ห้องเดิมของวิชานี้ไม่ว่าง (มีวิชา {_name(r['subject_id'])} อยู่แล้ว) — อาจต้องเปลี่ยนห้องด้วย"}

    return {"feasible": True, "reason": None}


# ═══════════════════════════════════════════════════════════════
# 📅 ตาราง — ภาพรวมทั้งระบบ
# ═══════════════════════════════════════════════════════════════

def get_availability_at(day: str, start_time: str, end_time: str) -> dict:
    """ดูว่าวัน/ช่วงเวลานี้ มีอาจารย์/ห้อง/กลุ่มไหนไม่ว่างบ้าง (รวม 3 อย่างในคำถามเดียว)
    ใช้เฉพาะเมื่อผู้ใช้ระบุวันและเวลามาแล้ว

    Args:
        day: วัน เช่น "จันทร์"
        start_time: เวลาเริ่ม เช่น "15:00"
        end_time: เวลาสิ้นสุด เช่น "16:50"

    Returns:
        dict มี key:
        - busy_teachers, busy_rooms, busy_groups: ไม่ว่างเพราะมีวิชาสอนอยู่ในช่วงนี้
        - rooms_marked_unavailable: ห้องที่ตั้ง "ช่วงไม่ว่าง" ไว้ในช่วงนี้
        หรือ {"error": ...} ถ้าหาวัน/เวลาไม่เจอ
    """
    try:
        target_ids = set(_find_timeslot_ids_by_range(day, start_time, end_time))
    except ValueError as e:
        return {"error": str(e)}

    rows = supabase.table("timetable_ai").select("teacher_id, room_id, group_id, timeslot_id").execute().data
    unavail_rows = supabase.table("room_unavailability").select("room_id, timeslot_id").execute().data
    teacher_name_by_id = {t["teacher_id"]: t.get("teacher_name") for t in load("teachers")}
    room_name_by_id = {r["room_id"]: r["room_name"] for r in load("rooms")}

    busy_teachers, busy_rooms, busy_group_ids = set(), set(), set()
    for r in rows:
        if r["timeslot_id"] not in target_ids:
            continue
        if r.get("teacher_id"):
            busy_teachers.add(teacher_name_by_id.get(r["teacher_id"], r["teacher_id"]))
        if r.get("room_id"):
            busy_rooms.add(room_name_by_id.get(r["room_id"], r["room_id"]))
        if r.get("group_id"):
            busy_group_ids.add(r["group_id"])

    marked_unavailable = {
        room_name_by_id.get(r["room_id"], r["room_id"])
        for r in unavail_rows
        if r["timeslot_id"] in target_ids
    }

    return {
        "day": day,
        "start_time": start_time,
        "end_time": end_time,
        "busy_teachers": sorted(busy_teachers),
        "busy_rooms": sorted(busy_rooms),
        "busy_groups": sorted(group_label(gid) for gid in busy_group_ids),
        "rooms_marked_unavailable": sorted(marked_unavailable),
    }


def get_system_summary() -> dict:
    """สรุปภาพรวมทั้งระบบ (จำนวนวิชา section ห้อง อาจารย์ กลุ่มนิสิต ที่มีอยู่ตอนนี้)

    หมายเหตุ: 'subjects' คือแคตตาล็อกวิชาทั้งหลักสูตร ส่วน 'subject_selected' คือ section
    ที่เปิดสอนจริงภาคเรียนนี้ — "เปิดสอนกี่วิชา" ต้องตอบจาก open_subjects_this_term

    Returns:
        dict มี key:
        - total_subjects_in_curriculum: จำนวนวิชาทั้งหมดในหลักสูตร (ไม่ใช่เทอมนี้)
        - open_subjects_this_term: จำนวนวิชา (ไม่นับซ้ำ) ที่เปิดสอนจริงภาคเรียนนี้
        - section_count: จำนวน section ทั้งหมดที่เปิดสอนภาคเรียนนี้
        - room_count, teacher_count, group_count
    """
    sections = load("subject_selected")
    open_subject_ids = {s["subject_id"] for s in sections if s.get("subject_id")}

    return {
        "total_subjects_in_curriculum": len(load("subjects")),
        "open_subjects_this_term": len(open_subject_ids),
        "section_count": len(sections),
        "room_count": len(load("rooms")),
        "teacher_count": len(load("teachers")),
        "group_count": len(load("groups")),
    }