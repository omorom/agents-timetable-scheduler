from itertools import product

from agent_timetable.tools.get_data import supabase
from .load_data import get_cached_data, refresh_cache


def record_assignment(session: dict, candidate: dict) -> dict:
    """บันทึก assignment ลง Supabase — insert 1 แถวต่อคู่ (teacher_id, group_id, timeslot_id)
    candidate["timeslot_ids"] มี 2 ตัวเสมอ (ทั้ง block) — insert ครบทั้ง 2 timeslot
    เพื่อให้ conflict-checking อื่นๆ เห็นว่า block นี้ถูกจองเต็มทั้ง 2 ชั่วโมงจริง
    """
    teacher_ids = session["teacher_ids"] or [None]
    group_ids = session["group_ids"] or [None]
    timeslot_ids = candidate["timeslot_ids"]

    rows = [
        {
            "session_id": session["session_id"],
            "subject_selected_id": session["subject_selected_id"],
            "subject_id": session["subject_id"],
            "session_type": session["session_type"],
            "section": session.get("section"),
            "teacher_id": teacher_id,
            "room_id": candidate["room_id"],
            "timeslot_id": int(timeslot_id),
            "group_id": group_id,
        }
        for teacher_id, group_id in product(teacher_ids, group_ids)
        for timeslot_id in timeslot_ids
    ]

    supabase.table("timetable_ai").insert(rows).execute()
    refresh_cache()  # ให้ get_valid_slots รอบถัดไปเห็น assignment ใหม่นี้ทันที

    return {
        "session_id": session["session_id"],
        "subject_id": session["subject_id"],
        "section": session.get("section"),
        "timeslot": candidate["timeslot_label"],
        "room_id": candidate["room_id"],
        "room_name": candidate["room_name"],
        "teacher_ids": session["teacher_ids"],
        "group_ids": session["group_ids"],
    }


def get_current_schedule() -> list[dict]:
    """คืนตารางปัจจุบันทั้งหมด รวมแถวที่ insert แยกไว้ (teacher-group pair) กลับเป็น
    1 รายการต่อ session (เอา field ที่ไม่ใช่ key มาจากแถวแรกพอ เพราะเหมือนกันหมดทุกแถว
    ยกเว้น teacher_id/group_id/timeslot_id ที่ต้องรวมเป็น list — โดยเฉพาะ timeslot_id
    ต้องเก็บ "ทั้ง 2 ตัว" ของ block เสมอ (ไม่ใช่แค่ตัวแรกที่เจอ) ไม่งั้น frontend
    จะแสดงผลแค่ 1 ชั่วโมง ทั้งที่จริงจอง 2 ชั่วโมงติดกัน
    """
    data = get_cached_data()
    rows = data["assignments"]

    by_session: dict[str, dict] = {}
    for r in rows:
        sid = r.get("session_id")
        if not sid:
            continue
        entry = by_session.setdefault(sid, {
            "session_id": sid,
            "subject_id": r.get("subject_id"),
            "subject_selected_id": r.get("subject_selected_id"),
            "session_type": r.get("session_type"),
            "section": r.get("section"),
            "room_id": r.get("room_id"),
            "timeslot_ids": set(),  # ← เปลี่ยนจาก "timeslot_id" เดี่ยว เป็น set เก็บได้ทั้ง block
            "teacher_ids": set(),
            "group_ids": set(),
        })
        if r.get("timeslot_id") is not None:
            entry["timeslot_ids"].add(r["timeslot_id"])
        if r.get("teacher_id"):
            entry["teacher_ids"].add(r["teacher_id"])
        if r.get("group_id"):
            entry["group_ids"].add(r["group_id"])

    result = []
    for entry in by_session.values():
        entry["teacher_ids"] = list(entry["teacher_ids"])
        entry["group_ids"] = list(entry["group_ids"])
        entry["timeslot_ids"] = sorted(entry["timeslot_ids"])
        result.append(entry)
    return result


def get_current_schedule_raw() -> list[dict]:
    """คืนแถวดิบตรงๆ ไม่รวม (ใช้ตอนเช็ค conflict ที่ต้องการ 1 แถว = 1 teacher/1 group)"""
    return get_cached_data()["assignments"]


def _find_paired_session(sessions: list[dict], session: dict) -> dict | None:
    """หา session คู่ (section อื่นของวิชา+ปี+กลุ่มนิสิตเดียวกัน+session_type เดียวกัน)

    เทียบจาก (subject_id, group_ids, session_type) แทนการเทียบ session_id string
    ตรงๆ เพราะกรณี parallel (คู่กันจากคนละแถว subject_selected) session_id ฐาน
    ไม่เหมือนกันเลย (เช่น SS162-LAB-1 กับ SS163-LAB-2) เทียบ string ไม่เจอ
    """
    if not session.get("section"):
        return None
    my_key = (session["subject_id"], tuple(sorted(session.get("group_ids") or [])), session["session_type"])
    return next(
        (
            s for s in sessions
            if s["session_id"] != session["session_id"]
            and s.get("section")  # ต้องมี section ด้วย (ไม่ใช่ session เดี่ยวของวิชาอื่น)
            and (s["subject_id"], tuple(sorted(s.get("group_ids") or [])), s["session_type"]) == my_key
        ),
        None,
    )


def delete_session_assignment(session_id: str) -> None:
    """ลบ assignment เดิมของ session นี้ทั้งหมดออกจาก Supabase"""
    supabase.table("timetable_ai").delete().eq("session_id", session_id).execute()
    refresh_cache()


def move_session(session_id: str) -> dict:
    """
    ย้าย session ที่มีปัญหาไปยัง slot ใหม่ที่ดีกว่า
    ถ้า session นี้มี section คู่ (1/2) จะบังคับให้ slot ใหม่อยู่ห้องเดียวกับคู่เสมอ
    (hard requirement ไม่มี fallback ข้ามห้อง) ย้ายแค่ session นี้ ไม่กระทบคู่
    """
    from .section_logic import build_session_list
    from .slot_filter import get_valid_slots
    from .candidate_scorer import day_of
    from .candidate_picker import pick_best_candidate, pick_paired_section_candidate

    sessions = build_session_list()
    session = next((s for s in sessions if s["session_id"] == session_id), None)
    if not session:
        return {"success": False, "reason": f"ไม่พบ session {session_id}"}

    delete_session_assignment(session_id)

    result = get_valid_slots(session_id, limit=None)
    if result.get("error") or not result["valid_slots"]:
        return {"success": False, "reason": result.get("error", "ไม่มี slot ว่างเลย")}

    current = get_current_schedule_raw()

    lecture_session = next(
        (s for s in sessions if s["subject_selected_id"] == session["subject_selected_id"] and s["session_type"] == "LECTURE"),
        None,
    )
    lecture_day = None
    if lecture_session:
        lecture_assignment = next(
            (a for a in current if a.get("session_id") == lecture_session["session_id"]), None
        )
        if lecture_assignment:
            lecture_day = day_of(lecture_assignment["timeslot_id"])

    paired_session = _find_paired_session(sessions, session)
    chosen = None
    paired_room_id = None
    if paired_session:
        paired_assignment = next(
            (a for a in current if a.get("session_id") == paired_session["session_id"]), None
        )
        if paired_assignment:
            paired_room_id = paired_assignment["room_id"]
            teachers_a = set(session.get("teacher_ids") or [])
            teachers_b = set(paired_session.get("teacher_ids") or [])
            same_teacher = bool(teachers_a & teachers_b)
            chosen = pick_paired_section_candidate(
                session, result["valid_slots"],
                paired_room_id, paired_assignment["timeslot_id"], current,
                same_teacher=same_teacher,
            )

    if chosen is None and paired_room_id is not None:
        same_room_candidates = [c for c in result["valid_slots"] if c["room_id"] == paired_room_id]
        if same_room_candidates:
            chosen = pick_best_candidate(session, same_room_candidates, lecture_day, current)
    elif chosen is None:
        chosen = pick_best_candidate(session, result["valid_slots"], lecture_day, current)

    if chosen is None:
        return {"success": False, "reason": "ไม่สามารถเลือก candidate ใหม่ได้"}

    item = record_assignment(session, chosen)
    return {"success": True, "new_assignment": item}


def manual_move_session(session_id: str, target_timeslot_id: str, target_room_id: str | None = None) -> dict:
    from .section_logic import build_session_list
    from .slot_filter import get_valid_slots
    from .candidate_picker import pick_paired_section_candidate

    sessions = build_session_list()
    session = next((s for s in sessions if s["session_id"] == session_id), None)
    if not session:
        return {"success": False, "reason": f"ไม่พบ session {session_id}"}

    # เก็บแถวเดิมทั้งหมดไว้ก่อนลบ (เผื่อต้อง rollback ถ้า target ไม่ว่าง)
    old_rows = [a for a in get_current_schedule_raw() if a.get("session_id") == session_id]
    if not old_rows:
        return {"success": False, "reason": f"ไม่พบ session {session_id} ในตารางปัจจุบัน"}
    old_room_id = old_rows[0]["room_id"]

    def _snapshot_rows(rows: list[dict]) -> list[dict]:
        return [
            {
                "session_id": r["session_id"],
                "subject_selected_id": r.get("subject_selected_id"),
                "subject_id": r.get("subject_id"),
                "session_type": r.get("session_type"),
                "section": r.get("section"),
                "teacher_id": r.get("teacher_id"),
                "room_id": r.get("room_id"),
                "timeslot_id": r.get("timeslot_id"),
                "group_id": r.get("group_id"),
            }
            for r in rows
        ]

    def _rollback(*row_groups: list[dict]):
        restore_rows = [r for group in row_groups for r in group]
        if restore_rows:
            supabase.table("timetable_ai").insert(restore_rows).execute()
            refresh_cache()

    # ── หาคู่ก่อนลบอะไรเลย (เผื่อ rollback ต้องใช้ snapshot เดิมของคู่ด้วย) ──
    paired_session = _find_paired_session(sessions, session)
    paired_old_rows: list[dict] = []
    if paired_session:
        paired_old_rows = [
            a for a in get_current_schedule_raw() if a.get("session_id") == paired_session["session_id"]
        ]

    delete_session_assignment(session_id)

    result = get_valid_slots(session_id, limit=None)
    if result.get("error"):
        _rollback(old_rows)
        return {"success": False, "reason": result["error"]}

    candidates_at_target = [
        c for c in result["valid_slots"] if str(target_timeslot_id) in c["timeslot_ids"]
    ]

    if not candidates_at_target:
        _rollback(old_rows)
        return {"success": False, "reason": "คาบเวลานี้ไม่ว่าง หรือชนกับข้อจำกัดอื่น (ห้อง/อาจารย์/กลุ่ม/ไม่ว่าง)"}

    chosen = None
    if target_room_id:
        chosen = next((c for c in candidates_at_target if c["room_id"] == target_room_id), None)
        if not chosen:
            _rollback(old_rows)
            return {"success": False, "reason": f"ห้อง {target_room_id} ไม่ว่างในคาบนี้"}
    else:
        chosen = next((c for c in candidates_at_target if c["room_id"] == old_room_id), None)
        if not chosen:
            chosen = candidates_at_target[0]

    if not paired_session:
        item = record_assignment(session, chosen)
        return {"success": True, "new_assignment": item}

    delete_session_assignment(paired_session["session_id"])

    primary_item = record_assignment(session, chosen)

    teachers_primary = set(session.get("teacher_ids") or [])
    teachers_partner = set(paired_session.get("teacher_ids") or [])
    same_teacher = bool(teachers_primary & teachers_partner)

    partner_result = get_valid_slots(paired_session["session_id"], limit=None)
    if partner_result.get("error"):
        # หาคู่ไม่ได้เลย -> rollback ทั้งคู่ ไม่ย้ายอะไรเลย
        delete_session_assignment(session_id)
        _rollback(old_rows, paired_old_rows)
        return {"success": False, "reason": f"ย้ายไม่สำเร็จ: คู่ ({paired_session['session_id']}) หา slot ไม่ได้เลย — {partner_result['error']}"}

    current_after_primary = get_current_schedule_raw()
    partner_chosen = pick_paired_section_candidate(
        paired_session, partner_result["valid_slots"],
        chosen["room_id"], chosen["timeslot_ids"][0], current_after_primary,
        same_teacher=same_teacher,
    )

    if partner_chosen is None:
        # หา slot ให้คู่ไม่ได้ -> rollback ทั้งคู่กลับที่เดิม ไม่ย้ายเลยสักตัว (กันคู่หลุดจากกัน)
        delete_session_assignment(session_id)
        _rollback(old_rows, paired_old_rows)
        return {
            "success": False,
            "reason": (
                f"ย้ายไม่สำเร็จ: คาบนี้จัดให้คู่ ({paired_session['session_id']}) ไม่ได้ "
                f"(ต้องการ{'ห้องเดียวกัน' if same_teacher else 'เวลาเดียวกันคนละห้อง'}กับที่ลากไป) "
                "ไม่ได้ย้ายทั้งคู่ เพื่อกันไม่ให้แยกออกจากกัน"
            ),
        }

    partner_item = record_assignment(paired_session, partner_chosen)

    return {
        "success": True,
        "new_assignment": primary_item,
        "paired_assignment": partner_item,
    }


def manual_edit_session(session_id: str, room_id: str | None = None, teacher_ids: list[str] | None = None) -> dict:
    """แก้ไขห้อง/อาจารย์ของ session (เวลาเดิมไม่เปลี่ยน) เช็ค conflict ก่อนเสมอ
    ถ้าไม่ระบุ room_id/teacher_ids ตัวไหน จะคงค่าเดิมของตัวนั้นไว้

    รองรับหลายอาจารย์ต่อ session (team-teaching) — teacher_ids เป็น list เสมอ
    ถ้าระบุ (แม้แค่ 1 คน) จะแทนที่อาจารย์เดิมทั้งหมดด้วยชุดใหม่นี้

    Args:
        session_id: session ที่จะแก้ไข
        room_id: ห้องใหม่ (ไม่ระบุ = ห้องเดิม)
        teacher_ids: รายชื่ออาจารย์ชุดใหม่ (ไม่ระบุ/None = ใช้ชุดเดิม, [] = ลบอาจารย์ออกหมด)

    Returns:
        สำเร็จ: {"success": True, "new_assignment": {...}}
        ผิดพลาด: {"success": False, "reason": "..."}
    """
    from .load_data import get_cached_data
    from .section_logic import build_session_list

    old_rows = [a for a in get_current_schedule_raw() if a.get("session_id") == session_id]
    if not old_rows:
        return {"success": False, "reason": f"ไม่พบ session {session_id} ในตารางปัจจุบัน"}

    old_room_id = old_rows[0]["room_id"]
    old_timeslot_ids = sorted({str(r["timeslot_id"]) for r in old_rows})  # ทั้ง block (2 ตัว)
    old_teacher_ids = list({r["teacher_id"] for r in old_rows if r.get("teacher_id")})
    old_group_ids = {r["group_id"] for r in old_rows if r.get("group_id")}

    session_static = next((s for s in build_session_list() if s["session_id"] == session_id), None)
    if not session_static:
        return {"success": False, "reason": f"ไม่พบ session {session_id}"}

    final_room_id = room_id or old_room_id
    # teacher_ids=None -> คงชุดเดิม, teacher_ids=[] หรือมีค่า -> แทนที่ทั้งชุด
    final_teacher_ids = old_teacher_ids if teacher_ids is None else [t for t in teacher_ids if t]

    data = get_cached_data()
    other_rows = [
        r for r in data["assignments"]
        if r.get("session_id") != session_id and str(r.get("timeslot_id")) in old_timeslot_ids
    ]

    # เช็คห้องชนกับ session อื่นใน 2 timeslot ของ block นี้ (ต้องว่างทั้งคู่)
    if any(r.get("room_id") == final_room_id for r in other_rows):
        return {"success": False, "reason": f"ห้อง {final_room_id} ไม่ว่างในคาบเวลานี้ มีวิชาอื่นอยู่แล้ว"}

    # เช็คห้องถูกตั้งไม่ว่างไว้ (room_unavailability) ในคาบใดคาบหนึ่งของ block
    if any(
        u["room_id"] == final_room_id and str(u["timeslot_id"]) in old_timeslot_ids
        for u in data["room_unavailability"]
    ):
        return {"success": False, "reason": f"ห้อง {final_room_id} ถูกตั้งค่าไม่ว่างไว้ในคาบนี้"}

    # เช็คอาจารย์ทุกคนในชุดใหม่ ว่าชนกับ session อื่นในคาบเดียวกันไหม (เช็คทีละคน)
    for tid in final_teacher_ids:
        if any(r.get("teacher_id") == tid for r in other_rows):
            return {"success": False, "reason": f"อาจารย์ {tid} สอนวิชาอื่นอยู่แล้วในคาบเวลานี้"}
        if any(
            u["teacher_id"] == tid and str(u["timeslot_id"]) in old_timeslot_ids
            for u in data["teacher_unavailability"]
        ):
            return {"success": False, "reason": f"อาจารย์ {tid} ถูกตั้งค่าไม่ว่างไว้ในคาบนี้"}

    delete_session_assignment(session_id)

    effective_session = {
        **session_static,
        "teacher_ids": final_teacher_ids,
        "group_ids": list(old_group_ids) or session_static["group_ids"],
    }
    ts_rows = [t for t in data["timeslots"] if str(t["timeslot_id"]) in old_timeslot_ids]
    ts_rows.sort(key=lambda t: t["start_time"])
    label = (
        f"{ts_rows[0]['day']} {ts_rows[0]['start_time']}-{ts_rows[-1]['end_time']}"
        if ts_rows else ""
    )
    room_name = next((r["room_name"] for r in data["rooms"] if r["room_id"] == final_room_id), final_room_id)
    candidate = {
        "timeslot_ids": old_timeslot_ids,  # ← ทั้ง block เดิม (เวลาไม่เปลี่ยน แก้แค่ห้อง/อาจารย์)
        "timeslot_label": label,
        "room_id": final_room_id,
        "room_name": room_name,
    }

    item = record_assignment(effective_session, candidate)
    return {"success": True, "new_assignment": item}