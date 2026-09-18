from itertools import product

from agent_timetable.tools.get_data import supabase
from .load_data import get_cached_data, refresh_cache
from .candidate_scorer import passes_hard_rules as passes_hard_rules_check


def record_assignment(session: dict, candidate: dict) -> dict:
    """Insert assignment ลง Supabase — 1 แถวต่อคู่ (teacher, group, timeslot) ครบทั้ง block"""
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
    refresh_cache()

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
    """รวมแถวดิบเป็น 1 รายการต่อ session (timeslot_ids เก็บครบทั้ง block เสมอ)"""
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
            "timeslot_ids": set(),
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
    """แถวดิบตรงๆ ไม่รวม (ใช้เช็ค conflict)"""
    return get_cached_data()["assignments"]


def _find_paired_session(sessions: list[dict], session: dict) -> dict | None:
    """หา section คู่ (วิชา+ปี+กลุ่ม+session_type เดียวกัน คนละ subject_selected_id)"""
    if not session.get("section"):
        return None
    my_key = (session["subject_id"], tuple(sorted(session.get("group_ids") or [])), session["session_type"])
    return next(
        (
            s for s in sessions
            if s["session_id"] != session["session_id"]
            and s.get("section")
            and (s["subject_id"], tuple(sorted(s.get("group_ids") or [])), s["session_type"]) == my_key
        ),
        None,
    )


def delete_session_assignment(session_id: str) -> None:
    supabase.table("timetable_ai").delete().eq("session_id", session_id).execute()
    refresh_cache()


def _diagnose_slot_failure(
    session: dict,
    target_timeslot_ids: list[str],
    target_room_id: str | None,
    exclude_session_ids: set[str],
) -> str:
    """หาสาเหตุที่แท้จริงว่าทำไม target_timeslot ถึงย้ายไม่ได้ สำหรับ session นี้
    เช็คตามลำดับ: อาจารย์ชน -> กลุ่มชน -> ห้องชน -> อาจารย์/ห้องถูกตั้งไม่ว่าง -> ไม่มีห้องว่างเลย
    คืนข้อความที่บอกชื่อวิชา/กลุ่ม/ห้องที่ชนจริงๆ แทน generic message "ย้ายไม่สำเร็จ"
    เรียกตอน rollback (ก่อน insert คืนค่าเดิม) เพื่อให้เห็น state ปัจจุบันตรงกับตอนที่ลองหา slot จริง
    """
    data = get_cached_data()
    current = data["existing"] + data["assignments"]
    subjects_by_id = {s["subject_id"]: s for s in data["subjects"]}
    rooms_by_id = {r["room_id"]: r["room_name"] for r in data["rooms"]}

    def _subject_label(subject_id: str | None) -> str:
        if not subject_id:
            return "วิชาอื่น"
        subj = subjects_by_id.get(subject_id, {})
        return subj.get("name_thai") or subj.get("name_english") or subject_id

    target_ids_str = [str(t) for t in target_timeslot_ids]
    rows_at_target = [
        r for r in current
        if str(r.get("timeslot_id")) in target_ids_str
        and r.get("session_id") not in exclude_session_ids
    ]

    # 1) อาจารย์ชน
    teacher_ids = session.get("teacher_ids") or []
    for r in rows_at_target:
        if r.get("teacher_id") in teacher_ids:
            return f"อาจารย์สอนวิชา {_subject_label(r.get('subject_id'))} (กลุ่ม {r.get('group_id', '-')}) อยู่แล้วในช่วงเวลานี้"

    # 2) กลุ่มนิสิตชน
    group_ids = session.get("group_ids") or []
    for r in rows_at_target:
        if r.get("group_id") in group_ids:
            return f"กลุ่ม {r.get('group_id')} ติดเรียนวิชา {_subject_label(r.get('subject_id'))} อยู่แล้วในช่วงเวลานี้"

    # 3) ห้องชน (เฉพาะถ้าระบุห้องเป้าหมายมา — เช่น user ลากไปวางในห้องที่มองเห็นบนกริด)
    if target_room_id:
        for r in rows_at_target:
            if r.get("room_id") == target_room_id:
                room_name = rooms_by_id.get(target_room_id, target_room_id)
                return f"ห้อง {room_name} ไม่ว่างในช่วงเวลานี้ (มีวิชา {_subject_label(r.get('subject_id'))} อยู่แล้ว)"

    # 4) อาจารย์/ห้อง ถูกตั้ง unavailability ไว้ตรงๆ
    for row in data["teacher_unavailability"]:
        if row["teacher_id"] in teacher_ids and str(row["timeslot_id"]) in target_ids_str:
            return "อาจารย์ถูกตั้งค่าไม่ว่างไว้ในช่วงเวลานี้"

    if target_room_id:
        for row in data["room_unavailability"]:
            if row["room_id"] == target_room_id and str(row["timeslot_id"]) in target_ids_str:
                room_name = rooms_by_id.get(target_room_id, target_room_id)
                return f"ห้อง {room_name} ถูกตั้งค่าไม่ว่างไว้ในช่วงเวลานี้"

    # 5) ไม่มีห้องที่ตรง room_type ว่างเลยสักห้อง (ไม่ได้ระบุห้องเป้าหมายมา หรือเช็คผ่านหมดแล้วแต่ยังไม่เจอ)
    return "ไม่มีห้องที่เหมาะสมว่างในช่วงเวลานี้ หรือชนกับเงื่อนไขอื่นที่ระบบตั้งไว้"


def move_session(session_id: str) -> dict:
    """ย้าย session อัตโนมัติ (ใช้ตอน AI auto-assign/fix) — ยังคงกฎ pairing ไว้เต็มรูปแบบ
    ต่างจาก manual_move_session ที่ตัด pairing ออกสำหรับกรณี user ลากเอง

    แก้ไขล่าสุด (สำคัญ — แก้บั๊ก): เดิมถ้า pick_paired_section_candidate() หา
    "เวลาเดียวกับคู่ คนละห้อง" ไม่เจอ (กรณี same_teacher=False คนละอาจารย์) จะ
    fallback ไปหา candidate ที่ "ห้องเดียวกับคู่" แทน (same_room_candidates) —
    fallback นี้ถูกออกแบบมาสำหรับ same_teacher=True (ที่ต้องห้องเดียวกันจริง)
    เท่านั้น แต่โค้ดเดิมใช้ fallback เดียวกันกับทั้ง 2 กรณี ทำให้กรณีคนละอาจารย์
    (ต้องการ "เวลาเดียวกัน คนละห้อง") พอหาตรงเป๊ะไม่เจอ กลับไปเลือกห้องเดียวกับคู่
    แทน (ผิดกฎ — สอนพร้อมกันห้องเดียวกันไม่ได้) แล้วเวลาก็ไม่ตรงกับคู่ด้วย เพราะ
    pick_best_candidate ไม่รู้จักข้อจำกัดเรื่อง "ต้องเวลาตรงกับคู่" เลย เจอบั๊กจริง
    กับ 254171 (IT-Y1): section 1/2 จบลงที่ห้องเดียวกัน (16) แต่คนละเวลา

    ตอนนี้แยก fallback ตาม same_teacher ให้ถูกต้อง:
      - same_teacher=True: fallback เดิม (ห้องเดียวกับคู่) ยังคงถูกต้อง ไม่แก้
      - same_teacher=False: ถ้าหา "เวลาเดียวกับคู่ คนละห้อง" ไม่เจอ (partner อาจ
        ถูกย้ายไปที่อื่นแล้วจาก fix รอบก่อนหน้า ทำให้ timeslot เดิมไม่ว่างแล้ว)
        ให้ atomic-repair คู่ทั้งสองใหม่พร้อมกัน (ลบทั้งคู่ หา slot ที่ทั้งคู่ว่าง
        พร้อมกันคนละห้องใหม่ทั้งหมด ผ่าน assign_group_same_time) แทนที่จะยอมให้
        เดี่ยวไปเลือกห้อง/เวลาอะไรก็ได้ตามลำพัง (ซึ่งทำลาย invariant "เวลาเดียวกัน
        คนละห้อง" เสมอ) ถ้า atomic-repair ก็ยังหาไม่ได้ ค่อยยอมแพ้ไปคืน failed
        (ตารางจะไม่ตรง pairing ในเคสที่ทรัพยากรไม่พอจริงๆ ไม่มีทางเลี่ยงได้)
    """
    from .section_logic import build_session_list
    from .slot_filter import get_valid_slots
    from .candidate_scorer import day_of
    from .candidate_picker import pick_best_candidate, pick_paired_section_candidate, assign_group_same_time

    sessions = build_session_list()
    session = next((s for s in sessions if s["session_id"] == session_id), None)
    if not session:
        return {"success": False, "reason": f"ไม่พบ session {session_id}"}

    lecture_session = next(
        (s for s in sessions if s["subject_selected_id"] == session["subject_selected_id"] and s["session_type"] == "LECTURE"),
        None,
    )
    lecture_day = None
    if lecture_session:
        current_before = get_current_schedule_raw()
        lecture_assignment = next((a for a in current_before if a.get("session_id") == lecture_session["session_id"]), None)
        if lecture_assignment:
            lecture_day = day_of(lecture_assignment["timeslot_id"])

    paired_session = _find_paired_session(sessions, session)
    teachers_a = set(session.get("teacher_ids") or [])
    teachers_b = set(paired_session.get("teacher_ids") or []) if paired_session else set()
    same_teacher = bool(teachers_a & teachers_b) if paired_session else True

    # ── กรณีมีคู่ + คนละอาจารย์: ต้องรักษา "เวลาเดียวกัน คนละห้อง" ไว้เสมอ ──
    if paired_session and not same_teacher:
        current = get_current_schedule_raw()
        paired_assignment = next((a for a in current if a.get("session_id") == paired_session["session_id"]), None)

        if paired_assignment:
            paired_room_id = paired_assignment["room_id"]
            paired_timeslot_id = paired_assignment["timeslot_id"]

            delete_session_assignment(session_id)
            result = get_valid_slots(session_id, limit=None)
            if not result.get("error") and result["valid_slots"]:
                current_after_delete = get_current_schedule_raw()
                chosen = pick_paired_section_candidate(
                    session, result["valid_slots"], paired_room_id, paired_timeslot_id, current_after_delete,
                    same_teacher=False,
                )
                if chosen is not None:
                    item = record_assignment(session, chosen)
                    return {"success": True, "new_assignment": item}

            # ── หา "เวลาเดียวกับคู่ คนละห้อง" ไม่เจอ (เช่น partner ถูกย้ายไปแล้ว
            # จน timeslot เดิมไม่ว่างสำหรับ session นี้อีกต่อไป) — atomic-repair
            # คู่ทั้งสองใหม่พร้อมกัน แทนที่จะปล่อยให้ session นี้ไปเลือกที่ไหนก็ได้
            # ตามลำพัง (ซึ่งจะทำลาย invariant "เวลาเดียวกัน คนละห้อง")
            old_pair_rows = [a for a in current if a.get("session_id") == paired_session["session_id"]]
            delete_session_assignment(paired_session["session_id"])

            result_a = get_valid_slots(session_id, limit=None)
            result_b = get_valid_slots(paired_session["session_id"], limit=None)

            if not result_a.get("error") and result_a["valid_slots"] and not result_b.get("error") and result_b["valid_slots"]:
                current_both_removed = get_current_schedule_raw()
                repaired = assign_group_same_time(
                    [session, paired_session],
                    [result_a["valid_slots"], result_b["valid_slots"]],
                    current_both_removed,
                    lecture_day=lecture_day,
                )
                if repaired is not None:
                    item_a = record_assignment(session, repaired[0])
                    record_assignment(paired_session, repaired[1])
                    return {"success": True, "new_assignment": item_a, "paired_repaired": True}

            # atomic-repair ก็หาไม่ได้จริงๆ — คืนคู่กลับตำแหน่งเดิม แล้วยอมแพ้เฉพาะ
            # session นี้ (ให้ไปอยู่ใน "failed" แทนที่จะทำลาย pairing เงียบๆ)
            if old_pair_rows:
                supabase.table("timetable_ai").insert(old_pair_rows).execute()
                refresh_cache()
            return {"success": False, "reason": "ไม่สามารถหา slot ที่รักษาคู่ (เวลาเดียวกัน คนละห้อง) ไว้ได้"}

    # ── กรณีไม่มีคู่ หรือมีคู่แบบ same_teacher=True (ห้องเดียวกัน) — เดิมทุกอย่าง ──
    delete_session_assignment(session_id)

    result = get_valid_slots(session_id, limit=None)
    if result.get("error") or not result["valid_slots"]:
        return {"success": False, "reason": result.get("error", "ไม่มี slot ว่างเลย")}

    current = get_current_schedule_raw()

    chosen = None
    paired_room_id = None
    if paired_session:
        paired_assignment = next((a for a in current if a.get("session_id") == paired_session["session_id"]), None)
        if paired_assignment:
            paired_room_id = paired_assignment["room_id"]
            chosen = pick_paired_section_candidate(
                session, result["valid_slots"], paired_room_id, paired_assignment["timeslot_id"], current,
                same_teacher=True,
            )

    if chosen is None and paired_room_id is not None:
        # fallback นี้ถูกต้องเฉพาะ same_teacher=True เท่านั้น (ห้องเดียวกันคือ
        # ข้อบังคับจริงของกรณีนี้) — ปลอดภัย เพราะโค้ดมาถึงบรรทัดนี้ได้ก็ต่อเมื่อ
        # same_teacher=True แล้วเท่านั้น (กรณี False ถูก handle แยกไปข้างบนแล้ว)
        same_room_candidates = [c for c in result["valid_slots"] if c["room_id"] == paired_room_id]
        if same_room_candidates:
            chosen = pick_best_candidate(session, same_room_candidates, lecture_day, current)
    elif chosen is None:
        chosen = pick_best_candidate(session, result["valid_slots"], lecture_day, current)

    if chosen is None:
        return {"success": False, "reason": "ไม่สามารถเลือก candidate ใหม่ได้"}

    item = record_assignment(session, chosen)
    return {"success": True, "new_assignment": item}


def _fake_assignment_for(session: dict, candidate: dict) -> dict:
    """assignment จำลอง 1 แถว ใช้เช็ค hard rule ก่อน insert จริง"""
    return {
        "session_id": session["session_id"],
        "subject_id": session["subject_id"],
        "teacher_id": session["teacher_ids"][0] if session["teacher_ids"] else None,
        "room_id": candidate["room_id"],
        "timeslot_id": candidate["timeslot_ids"][0],
        "group_id": session["group_ids"][0] if session["group_ids"] else None,
    }


def _double_check_still_free(room_id: str, teacher_ids: list[str], group_ids: list[str], timeslot_ids: list[str], exclude_session_ids: set[str]) -> str | None:
    """เช็คซ้ำกับ DB สดก่อน insert จริง กัน race condition"""
    rows = (
        supabase.table("timetable_ai")
        .select("session_id, room_id, teacher_id, group_id, timeslot_id")
        .in_("timeslot_id", [int(ts) for ts in timeslot_ids])
        .execute()
        .data
    )
    rows = [r for r in rows if r.get("session_id") not in exclude_session_ids]

    if any(r["room_id"] == room_id for r in rows):
        return "ห้องนี้เพิ่งถูกจองไปโดยการย้ายอื่นในเวลาไล่เลี่ยกัน (race condition) กรุณาลองใหม่"
    if teacher_ids and any(r.get("teacher_id") in teacher_ids for r in rows):
        return "อาจารย์เพิ่งถูกจัดสอนวิชาอื่นในช่วงนี้ไปโดยการย้ายอื่นในเวลาไล่เลี่ยกัน (race condition) กรุณาลองใหม่"
    if group_ids and any(r.get("group_id") in group_ids for r in rows):
        return "กลุ่มนิสิตเพิ่งถูกจัดวิชาอื่นในช่วงนี้ไปโดยการย้ายอื่นในเวลาไล่เลี่ยกัน (race condition) กรุณาลองใหม่"
    return None


def _manual_move_continuous_session(session: dict, target_timeslot_id: str, target_room_id: str | None = None) -> dict:
    """ย้าย session ที่ต้อง lecture ติดกันหลายชั่วโมง (มี continuous_size ตั้งไว้ เช่น
    3 ชม.รวด) — แยก path ต่างหากจาก manual_move_session ปกติ เพราะ get_valid_slots
    เดิมคืน candidate แค่ 2 timeslot (block ตายตัว) เสมอ ไม่รองรับ session ที่ต้องการ
    3+ timeslot ต่อเนื่อง ถ้าใช้ path เดิมจะได้ candidate ผิดขนาด ย้ายแล้วเหลือแค่
    2 ชม. (ตัดทอนไปเงียบๆ)

    ผู้ใช้ลากไปวางที่ timeslot ไหน ถือว่าเป็น "ชั่วโมงแรก" ของก้อน แล้วหาว่าต่อจากนั้น
    อีก (continuous_size - 1) ชั่วโมง ว่างติดกันจริงไหม (ห้อง/อาจารย์/นิสิต) ถ้าไม่ว่าง
    ครบทั้งก้อน ถือว่าย้ายไม่สำเร็จ ไม่มีการตัดทอนให้เหลือแค่บางชั่วโมง
    """
    from .slot_filter import get_valid_continuous_slots, _timeslot_label

    session_id = session["session_id"]
    num_units = session["continuous_size"]

    old_rows = [a for a in get_current_schedule_raw() if a.get("session_id") == session_id]
    if not old_rows:
        return {"success": False, "reason": f"ไม่พบ session {session_id} ในตารางปัจจุบัน"}

    delete_session_assignment(session_id)

    result = get_valid_continuous_slots(session, num_units, limit=None)
    if result.get("error"):
        supabase.table("timetable_ai").insert(old_rows).execute()
        refresh_cache()
        return {"success": False, "reason": result["error"]}

    # ต้องเป็นก้อนที่ timeslot แรกตรงกับจุดที่ลากไปวางเป๊ะ (ผู้ใช้ลากวางที่ไหน = เริ่มตรงนั้น)
    candidates_at_target = [
        c for c in result["valid_slots"] if c["timeslot_ids"][0] == str(target_timeslot_id)
    ]
    if target_room_id:
        candidates_at_target = [c for c in candidates_at_target if c["room_id"] == target_room_id]

    if not candidates_at_target:
        supabase.table("timetable_ai").insert(old_rows).execute()
        refresh_cache()
        return {"success": False, "reason": f"ย้ายไม่สำเร็จ (ห้อง/อาจารย์/นิสิตไม่ว่างครบ {num_units} ชม.ติดกันที่จุดนี้)"}

    chosen = candidates_at_target[0]

    dcheck = _double_check_still_free(
        chosen["room_id"], session["teacher_ids"], session["group_ids"], chosen["timeslot_ids"], {session_id}
    )
    if dcheck:
        supabase.table("timetable_ai").insert(old_rows).execute()
        refresh_cache()
        return {"success": False, "reason": dcheck}

    timeslots = get_cached_data()["timeslots"]
    candidate = {
        "timeslot_ids": chosen["timeslot_ids"],
        "timeslot_label": _timeslot_label(chosen["timeslot_ids"], timeslots),
        "room_id": chosen["room_id"],
        "room_name": chosen["room_name"],
    }
    item = record_assignment(session, candidate)
    return {"success": True, "new_assignment": item}


def manual_move_session(session_id: str, target_timeslot_id: str, target_room_id: str | None = None) -> dict:
    """ย้าย session ที่ user ลาก — คู่เวลาเดียวกันย้ายด้วยกัน (atomic), คู่คนละเวลาย้ายแค่ตัวเดียว"""
    from .section_logic import build_session_list
    from .slot_filter import get_valid_slots

    sessions = build_session_list()
    session = next((s for s in sessions if s["session_id"] == session_id), None)
    if not session:
        return {"success": False, "reason": f"ไม่พบ session {session_id}"}

    # ── วิชาที่ต้อง lecture ติดกันหลายชั่วโมงในวันเดียว (เช่น 3 ชม.รวด) ──
    # ต้องแยก path ต่างหาก เพราะ get_valid_slots ปกติคืน candidate แค่ 2 timeslot
    # (block ตายตัว) เสมอ ไม่รองรับ session ที่ต้องการ 3+ timeslot ต่อเนื่อง
    if session.get("continuous_size"):
        return _manual_move_continuous_session(session, target_timeslot_id, target_room_id)

    refresh_cache()

    old_rows = [a for a in get_current_schedule_raw() if a.get("session_id") == session_id]
    if not old_rows:
        return {"success": False, "reason": f"ไม่พบ session {session_id} ในตารางปัจจุบัน"}
    old_room_id = old_rows[0]["room_id"]
    old_timeslot_ids = {str(r["timeslot_id"]) for r in old_rows}

    def _rollback(*row_groups: list[dict]):
        restore_rows = [r for group in row_groups for r in group]
        if restore_rows:
            supabase.table("timetable_ai").insert(restore_rows).execute()
            refresh_cache()

    paired_session = _find_paired_session(sessions, session)
    paired_old_rows: list[dict] = []
    same_time_as_pair = False
    if paired_session:
        paired_old_rows = [a for a in get_current_schedule_raw() if a.get("session_id") == paired_session["session_id"]]
        paired_old_timeslot_ids = {str(r["timeslot_id"]) for r in paired_old_rows}
        same_time_as_pair = bool(old_timeslot_ids & paired_old_timeslot_ids)

    # ── ไม่มีคู่ หรือคู่คนละเวลา -> ย้ายตัวเดียว ──
    if not paired_session or not same_time_as_pair:
        delete_session_assignment(session_id)

        result = get_valid_slots(session_id, limit=None)
        if result.get("error"):
            _rollback(old_rows)
            return {"success": False, "reason": result["error"]}

        candidates_at_target = [c for c in result["valid_slots"] if str(target_timeslot_id) in c["timeslot_ids"]]
        if not candidates_at_target:
            # ── ไม่พบ candidate ที่ตรง timeslot เป้าหมายเลย -> วินิจฉัยสาเหตุจริง
            # ก่อน rollback (ต้องเช็คตอนที่ session นี้ยังถูกลบออกไปแล้ว เพื่อดู
            # ว่าใครไปครองช่วงเวลานั้นแทนอยู่ ไม่ใช่ตัวมันเอง)
            reason = _diagnose_slot_failure(session, [str(target_timeslot_id)], target_room_id, {session_id})
            _rollback(old_rows)
            return {"success": False, "reason": reason}

        chosen = next((c for c in candidates_at_target if c["room_id"] == (target_room_id or old_room_id)), None)
        if target_room_id and not chosen:
            reason = _diagnose_slot_failure(session, [str(target_timeslot_id)], target_room_id, {session_id})
            _rollback(old_rows)
            return {"success": False, "reason": reason}
        if not chosen:
            chosen = candidates_at_target[0]

        dcheck = _double_check_still_free(chosen["room_id"], session["teacher_ids"], session["group_ids"], chosen["timeslot_ids"], {session_id})
        if dcheck:
            _rollback(old_rows)
            return {"success": False, "reason": dcheck}

        item = record_assignment(session, chosen)
        return {"success": True, "new_assignment": item}

    # ── คู่เวลาเดียวกัน -> atomic pairing: เช็คทั้งคู่ผ่านก่อน ค่อย commit พร้อมกัน ──
    delete_session_assignment(session_id)
    delete_session_assignment(paired_session["session_id"])

    result_primary = get_valid_slots(session_id, limit=None)
    if result_primary.get("error"):
        _rollback(old_rows, paired_old_rows)
        return {"success": False, "reason": result_primary["error"]}

    primary_candidates = [c for c in result_primary["valid_slots"] if str(target_timeslot_id) in c["timeslot_ids"]]
    if target_room_id:
        primary_candidates = [c for c in primary_candidates if c["room_id"] == target_room_id]
    if not primary_candidates:
        exclude_ids = {session_id, paired_session["session_id"]}
        reason = _diagnose_slot_failure(session, [str(target_timeslot_id)], target_room_id, exclude_ids)
        _rollback(old_rows, paired_old_rows)
        return {"success": False, "reason": reason}

    result_partner = get_valid_slots(paired_session["session_id"], limit=None)
    if result_partner.get("error"):
        _rollback(old_rows, paired_old_rows)
        return {"success": False, "reason": f"ย้ายไม่สำเร็จ (คู่ section: {result_partner['error']})"}

    partner_candidates_at_time = [c for c in result_partner["valid_slots"] if str(target_timeslot_id) in c["timeslot_ids"]]
    current_base = get_current_schedule_raw()

    # หาคู่ (primary, partner) ที่ผ่าน hard rule พร้อมกัน — จำลอง primary assign แล้วก่อนเช็ค partner
    chosen_primary = chosen_partner = None
    for p_cand in primary_candidates:
        partner_room_options = [c for c in partner_candidates_at_time if c["room_id"] != p_cand["room_id"]]
        if not partner_room_options:
            continue
        local_current = current_base + [_fake_assignment_for(session, p_cand)]
        for pt_cand in partner_room_options:
            if not passes_hard_rules_check(paired_session, pt_cand["timeslot_ids"], local_current):
                continue
            if not passes_hard_rules_check(session, p_cand["timeslot_ids"], current_base):
                continue
            chosen_primary, chosen_partner = p_cand, pt_cand
            break
        if chosen_primary:
            break

    if not chosen_primary or not chosen_partner:
        exclude_ids = {session_id, paired_session["session_id"]}
        reason = _diagnose_slot_failure(session, [str(target_timeslot_id)], target_room_id, exclude_ids)
        _rollback(old_rows, paired_old_rows)
        return {"success": False, "reason": f"ย้ายไม่สำเร็จ (ต้องรักษาคู่ section ไว้ด้วย): {reason}"}

    exclude_ids = {session_id, paired_session["session_id"]}
    dcheck_primary = _double_check_still_free(chosen_primary["room_id"], session["teacher_ids"], session["group_ids"], chosen_primary["timeslot_ids"], exclude_ids)
    if dcheck_primary:
        _rollback(old_rows, paired_old_rows)
        return {"success": False, "reason": dcheck_primary}

    dcheck_partner = _double_check_still_free(chosen_partner["room_id"], paired_session["teacher_ids"], paired_session["group_ids"], chosen_partner["timeslot_ids"], exclude_ids)
    if dcheck_partner:
        _rollback(old_rows, paired_old_rows)
        return {"success": False, "reason": dcheck_partner}

    primary_item = record_assignment(session, chosen_primary)
    partner_item = record_assignment(paired_session, chosen_partner)
    return {"success": True, "new_assignment": primary_item, "paired_assignment": partner_item}


def manual_edit_session(session_id: str, room_id: str | None = None, teacher_ids: list[str] | None = None) -> dict:
    """แก้ไขห้อง/อาจารย์ของ session (เวลาเดิมไม่เปลี่ยน)"""
    from .load_data import get_cached_data
    from .section_logic import build_session_list

    old_rows = [a for a in get_current_schedule_raw() if a.get("session_id") == session_id]
    if not old_rows:
        return {"success": False, "reason": f"ไม่พบ session {session_id} ในตารางปัจจุบัน"}

    old_room_id = old_rows[0]["room_id"]
    old_timeslot_ids = sorted({str(r["timeslot_id"]) for r in old_rows})
    old_teacher_ids = list({r["teacher_id"] for r in old_rows if r.get("teacher_id")})
    old_group_ids = {r["group_id"] for r in old_rows if r.get("group_id")}

    session_static = next((s for s in build_session_list() if s["session_id"] == session_id), None)
    if not session_static:
        return {"success": False, "reason": f"ไม่พบ session {session_id}"}

    final_room_id = room_id or old_room_id
    final_teacher_ids = old_teacher_ids if teacher_ids is None else [t for t in teacher_ids if t]

    data = get_cached_data()
    other_rows = [r for r in data["assignments"] if r.get("session_id") != session_id and str(r.get("timeslot_id")) in old_timeslot_ids]

    if any(r.get("room_id") == final_room_id for r in other_rows):
        return {"success": False, "reason": f"ห้อง {final_room_id} ไม่ว่างในคาบเวลานี้ มีวิชาอื่นอยู่แล้ว"}

    if any(u["room_id"] == final_room_id and str(u["timeslot_id"]) in old_timeslot_ids for u in data["room_unavailability"]):
        return {"success": False, "reason": f"ห้อง {final_room_id} ถูกตั้งค่าไม่ว่างไว้ในคาบนี้"}

    for tid in final_teacher_ids:
        if any(r.get("teacher_id") == tid for r in other_rows):
            return {"success": False, "reason": f"อาจารย์ {tid} สอนวิชาอื่นอยู่แล้วในคาบเวลานี้"}
        if any(u["teacher_id"] == tid and str(u["timeslot_id"]) in old_timeslot_ids for u in data["teacher_unavailability"]):
            return {"success": False, "reason": f"อาจารย์ {tid} ถูกตั้งค่าไม่ว่างไว้ในคาบนี้"}

    delete_session_assignment(session_id)

    effective_session = {
        **session_static,
        "teacher_ids": final_teacher_ids,
        "group_ids": list(old_group_ids) or session_static["group_ids"],
    }
    ts_rows = [t for t in data["timeslots"] if str(t["timeslot_id"]) in old_timeslot_ids]
    ts_rows.sort(key=lambda t: t["start_time"])
    label = f"{ts_rows[0]['day']} {ts_rows[0]['start_time']}-{ts_rows[-1]['end_time']}" if ts_rows else ""
    room_name = next((r["room_name"] for r in data["rooms"] if r["room_id"] == final_room_id), final_room_id)
    candidate = {
        "timeslot_ids": old_timeslot_ids,
        "timeslot_label": label,
        "room_id": final_room_id,
        "room_name": room_name,
    }

    item = record_assignment(effective_session, candidate)
    return {"success": True, "new_assignment": item}