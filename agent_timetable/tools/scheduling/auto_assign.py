from agent_timetable.tools.get_data import supabase
from .load_data import refresh_cache, get_cached_data
from .section_logic import build_session_list
from .slot_filter import get_valid_slots, get_valid_continuous_slots, _timeslot_label
from .candidate_picker import pick_best_candidate, assign_lab_pair_deterministic, assign_group_same_time
from .candidate_scorer import day_of, DAY_SEQUENCE
from .assignment_store import (
    record_assignment, get_current_schedule, get_current_schedule_raw, move_session, delete_session_assignment,
)
from .find_issues import find_issues
from .retry_hints import set_active, clear_active

__all__ = ["auto_assign_all", "retry_failed_sessions", "get_current_schedule", "move_session"]

MAX_FIX_ROUNDS = 3

# วิชาที่ต้องเรียน LECTURE เวลาเดียวกัน คนละห้อง (ข้ามคนละ unit/คนละกลุ่มนิสิตได้)
# แต่ละ tuple = 1 กลุ่มที่ต้องตรงเวลากัน (ใส่ได้ตั้งแต่ 2 วิชาขึ้นไป)
# ใส่รหัสวิชาเดียวใน tuple = ทุก section ของวิชานั้นที่เป็น "คนละกลุ่มนิสิต" ต้องเรียน LECTURE
# เวลาเดียวกัน คนละห้อง (เช่น 273100 ที่ section CS-Y1 กับ IT-Y1 แยกกันเรียนแต่ต้องตรงเวลากัน)
SYNC_LECTURE_GROUPS: list[tuple[str, ...]] = [
    ("254391", "273391"),
    ("273100",),
]

# True  = ถ้าจัดพร้อมกันไม่ได้ ให้ fail ทั้งกลุ่ม (ไม่ถอยไปจัดแยก)
# False = ถ้าจัดพร้อมกันไม่ได้ ให้ถอยไปจัดแยกตามปกติ (แต่เวลาอาจไม่ตรงกัน/นอกช่วงที่กำหนด)
SYNC_STRICT = True

# ช่วงเวลาที่อนุญาตให้ LECTURE ของกลุ่ม sync ลงได้ รูปแบบ ("HH:MM", "HH:MM")
# เทียบกับ start_time ของ timeslot แรก และ end_time ของ timeslot สุดท้าย
# หมายเหตุ: คาบ 16:00-17:00 มี end_time = 17:00 ดังนั้น "ถึง 16:50" ต้องเขียนเป็น "17:00"
#   ("15:00", "17:00") = คาบ 15:00 หรือ 16:00 (block 4/8/12/16/20)
#   ("15:00", "16:00") = เฉพาะคาบ 15:00-16:00
#   ("16:00", "17:00") = เฉพาะคาบ 16:00-17:00
#   None               = ไม่จำกัดเวลา
# ใส่เป็นรายกลุ่ม — กลุ่มที่ไม่ได้ใส่ไว้ = ไม่จำกัดเวลา
SYNC_TIME_WINDOWS: dict[tuple[str, ...], tuple[str, str] | None] = {
    ("254391", "273391"): ("15:00", "17:00"),
    ("273100",): ("15:00", "17:00"),   # CS-Y1 กับ IT-Y1 เรียนพร้อมกันช่วงบ่าย 15:00-17:00 (วันไหนก็ได้)
}


def _lecture_days_to_avoid(lab_sessions: list[dict]) -> set[str] | None:
    """[ใหม่] มองล่วงหน้าก่อนวาง LECTURE: LAB ของวิชานี้ลงได้วันไหนบ้าง (ตามตารางตอนนี้)
    แล้วคืน "วันที่ LECTURE ควรเลี่ยง" = วันที่ไม่มีวัน LAB ว่างอยู่หลังจากนั้นเลย
    เช่น LAB ว่างแค่ จ.-พ. -> LECTURE ควรเลี่ยง พ. พฤ. ศ. (ไม่งั้น LAB ต้องอยู่ก่อน LECTURE)
    เดิม LECTURE ตกวันท้ายๆ ของสัปดาห์ได้บ่อย (สุ่ม) แล้ว LAB ไม่มีที่ลงหลัง LECTURE
    """
    if not lab_sessions:
        return None
    lab_days: set[str] | None = None
    for lab in lab_sessions:
        res = get_valid_slots(lab["session_id"], limit=None)
        days = {c["day"] for c in res.get("valid_slots", [])}
        lab_days = days if lab_days is None else lab_days & days
    if not lab_days:
        return None   # LAB ไม่มีที่ลงอยู่แล้ว เลี่ยงวันไหนก็ไม่ช่วย
    rank = {d: i for i, d in enumerate(DAY_SEQUENCE)}
    return {d for d in DAY_SEQUENCE if not any(rank[ld] > rank[d] for ld in lab_days)}


def _avoid_days(candidates: list[dict], avoid: set[str] | None) -> list[dict]:
    """ตัด candidate ที่อยู่ในวันที่ควรเลี่ยงออก — ถ้าตัดแล้วไม่เหลือเลย คืนชุดเดิม (ไม่ทำให้วิชาหลุด)"""
    if not avoid:
        return candidates
    keep = [c for c in candidates if (c.get("day") or day_of(c["timeslot_ids"][0])) not in avoid]
    return keep or candidates


def _fail_entry(session: dict, reason: str) -> dict:
    """สร้าง dict มาตรฐานสำหรับ failed.append() — ใส่ subject_id/session_type/section
    ติดไปด้วยเสมอ (ไม่ใช่แค่ session_id) ให้ frontend โชว์ "วิชาอะไร ประเภทไหน section
    ไหน" ให้ user อ่านรู้เรื่องได้ทันที ไม่ต้องไป join หา subject_id เพิ่มเองทีหลัง
    """
    return {
        "session_id": session["session_id"],
        "subject_id": session.get("subject_id"),
        "session_type": session.get("session_type"),
        "section": session.get("section"),
        "group_ids": session.get("group_ids"),
        "reason": reason,
    }


def reset_ai_schedule() -> None:
    """ลบตารางที่ AI เคยจัดไว้ทั้งหมด (ไม่แตะ existing/GENERAL ที่ล็อกไว้ต่างหาก)"""
    supabase.table("timetable_ai").delete().neq("id", 0).execute()
    refresh_cache()


def _assign_one(session, lecture_day, assigned, failed, prefer_early_day=False, avoid_days=None):
    """จัด session เดียวแบบปกติ (ไม่ pairing) คืน chosen candidate หรือ None ถ้าล้มเหลว"""
    result = get_valid_slots(session["session_id"], limit=None)
    if result.get("error") or not result["valid_slots"]:
        failed.append(_fail_entry(session, result.get("error", "ไม่มี slot ว่างเลย")))
        return None

    current = get_current_schedule_raw()
    candidates = _avoid_days(result["valid_slots"], avoid_days)
    chosen = pick_best_candidate(session, candidates, lecture_day, current, prefer_early_day)
    if chosen is None and candidates is not result["valid_slots"]:
        chosen = pick_best_candidate(session, result["valid_slots"], lecture_day, current, prefer_early_day)
    if chosen is None:
        failed.append(_fail_entry(session, "ไม่สามารถเลือก candidate ได้"))
        return None

    item = record_assignment(session, chosen)
    assigned.append(item)
    return chosen


def _assign_continuous_block(sessions, lecture_day, assigned, failed, prefer_early_day=False, avoid_days=None):
    """จัดวิชาที่ต้อง lecture ติดกันหลายชั่วโมงในวันเดียว (เช่น 3 ชม. รวด) — sessions
    มีแค่ 1 session เดียว (ดู section_logic.py: วิชา continuous สร้าง session เดียว
    ที่มี continuous_size บอกจำนวนชั่วโมง ไม่ได้แตกเป็นหลาย session ต่อชั่วโมง)

    หา slot แบบ atomic ทั้งชุดด้วย get_valid_continuous_slots แล้ว insert
    ครั้งเดียวโดยรวม timeslot_ids ทั้งหมดไว้ใน record เดียว (record_assignment
    รองรับ timeslot_ids กี่ตัวก็ได้อยู่แล้ว) เพื่อให้ DB มี session_id เดียว
    ครอบคลุมทุก timeslot — frontend จะ merge เป็นแท่งเดียวให้เองโดยไม่ต้องแก้อะไร
    เพิ่ม (ดู get_current_schedule ที่รวม timeslot_ids ต่อ session_id อยู่แล้ว)

    คืนวันที่จัดสำเร็จ (เอาไปใช้เป็น lecture_day ต่อให้ LAB ของวิชาเดียวกัน) หรือ
    lecture_day เดิมถ้าจัดไม่สำเร็จ
    """
    session = sessions[0]
    num_units = session["continuous_size"]

    result = get_valid_continuous_slots(session, num_units, limit=None)
    if result.get("error") or not result["valid_slots"]:
        failed.append(_fail_entry(
            session, result.get("error", f"ไม่มีวันไหนว่างครบ {num_units} ชม. ติดกันเลย")
        ))
        return lecture_day

    current = get_current_schedule_raw()
    candidates = _avoid_days(result["valid_slots"], avoid_days)
    chosen = pick_best_candidate(session, candidates, lecture_day, current, prefer_early_day)
    if chosen is None and candidates is not result["valid_slots"]:
        chosen = pick_best_candidate(session, result["valid_slots"], lecture_day, current, prefer_early_day)
    if chosen is None:
        failed.append(_fail_entry(session, "ไม่สามารถเลือก candidate ได้"))
        return lecture_day

    timeslots = get_cached_data()["timeslots"]
    candidate = {
        "timeslot_ids": chosen["timeslot_ids"],
        "timeslot_label": _timeslot_label(chosen["timeslot_ids"], timeslots),
        "room_id": chosen["room_id"],
        "room_name": chosen["room_name"],
        "day": chosen["day"],
    }
    item = record_assignment(session, candidate)
    assigned.append(item)

    return chosen["day"]


def _assign_paired_group(sessions, lecture_day, assigned, failed, prefer_early_day=False, avoid_days=None):
    """จัด session ของวิชาเดียว 1 ประเภท (LECTURE หรือ LAB) ให้ครบ ไม่ว่าจะมี section
    เดียวหรือคู่ 1/2 — ถ้ามี section คู่ จะเช็คว่าอาจารย์เป็นคนเดียวกันหรือคนละคน
    เพื่อเลือกวิธีจับคู่ที่ถูกต้อง (ห้องเดียวกัน+ติดกัน หรือ เวลาเดียวกัน+คนละห้อง)

    แยกจัดการ 3 กรณีให้ชัดเจน:
      0) session มี continuous_size ตั้งไว้ (วิชาที่ต้องเรียนติดกันในวันเดียว เช่น
         4 ชม. รวด) -> ส่งต่อให้ _assign_continuous_block() จัดแบบ atomic ทั้งชุด
         ไม่ผ่าน logic ด้านล่างเลย
      1) ทุก session ใน sessions มี section=None ทั้งหมด (ไม่มีการแบ่ง parallel/
         team-teaching เลย) -> จัดแยกอิสระทีละ block (ไม่ pairing เพราะไม่มีคู่จริง)
         ไม่ว่าจะมีกี่ block ก็ตาม (lecture_hours=1,2,3,...)
      2) มี session ที่ label "1"/"2" อยู่ (parallel/team-teaching) -> จับคู่กันตาม
         "ลำดับ block" (block แรกของฝั่ง 1 คู่กับ block แรกของฝั่ง 2, block ที่สอง
         คู่กับ block ที่สอง ฯลฯ) รองรับกรณีมีหลาย block ต่อฝั่งด้วย ไม่ใช่แค่ 1 ต่อ 1

    คืนค่าวันของ session สุดท้ายที่จัดสำเร็จ (เอาไปใช้เป็น lecture_day ต่อให้ LAB ของ
    วิชาเดียวกัน) หรือค่า lecture_day เดิมถ้าจัดไม่สำเร็จเลยสักตัว
    """
    # กรณี 0: วิชาที่ต้องเรียน LECTURE ติดกันหลาย block ในวันเดียว (ไม่แยกวัน)
    if sessions and sessions[0].get("continuous_size"):
        return _assign_continuous_block(sessions, lecture_day, assigned, failed, prefer_early_day, avoid_days)

    # [แก้] ตอนจัด LAB ต้องคง lecture_day (วัน LECTURE ของวิชานี้) ไว้ตลอดทุก block
    # เดิมหลังจัด LAB block แรกเสร็จ result_day ถูกเขียนทับด้วย "วันของ LAB block นั้น"
    # ทำให้ LAB block ถัดไปเอาวัน LAB มาเช็คเป็นวัน LECTURE (ผิดทั้งกฎคนละวันและคะแนน soft)
    # ตอนนี้จะอัปเดต result_day เฉพาะตอนจัด LECTURE เท่านั้น
    track_day = sessions[0].get("session_type") == "LECTURE" if sessions else False

    sessions = sorted(sessions, key=lambda s: (s.get("section") or "", s["session_id"]))

    by_section: dict[str | None, list[dict]] = {}
    for s in sessions:
        by_section.setdefault(s.get("section"), []).append(s)

    section_keys = set(by_section.keys())

    # กรณี 1: ไม่มีการแบ่ง section เลย (ทุกตัว section=None) — จัดแยกอิสระทีละ block
    # บังคับให้ทุก block ใช้ "ห้องเดียวกัน" เสมอ (นิสิตจะได้ไม่ต้องสับสนห้องระหว่างสัปดาห์)
    if section_keys == {None}:
        result_day = lecture_day
        locked_room_id: str | None = None
        for s in by_section[None]:
            result = get_valid_slots(s["session_id"], limit=None)
            if result.get("error") or not result["valid_slots"]:
                failed.append(_fail_entry(s, result.get("error", "ไม่มี slot ว่างเลย")))
                continue

            # [แก้] "ห้องเดียวกับ block ก่อนหน้า" เป็นแค่ความชอบ ไม่ใช่กฎบังคับ
            # เดิมถ้าห้องเดิมไม่ว่างเลย block นี้จะ "จัดไม่ได้" ทันที ทั้งที่ห้องอื่นยังว่าง
            # (เจอจริงกับ 254374 ปี 3: LECTURE block แรกลงวันพฤหัส แล้ว block ที่สองหลุด
            # ทั้งที่ลากวางเองได้ เพราะลากวางเลือกห้องไหนก็ได้) -> ลองห้องเดิมก่อน ไม่ได้ค่อยใช้ห้องอื่น
            candidates = result["valid_slots"]
            pools = []
            if locked_room_id is not None:
                same_room = [c for c in candidates if c["room_id"] == locked_room_id]
                if same_room:
                    pools.append(same_room)
            pools.append(candidates)

            current = get_current_schedule_raw()
            chosen = None
            for pool in pools:
                preferred = _avoid_days(pool, avoid_days)
                chosen = pick_best_candidate(s, preferred, result_day, current, prefer_early_day)
                if chosen is None and preferred is not pool:
                    chosen = pick_best_candidate(s, pool, result_day, current, prefer_early_day)
                if chosen is not None:
                    break
            if chosen is None:
                failed.append(_fail_entry(s, "ไม่มีช่องที่ผ่านกฎตาราง (เกิน 3 วิชา/วัน, อาจารย์สอนรวด ฯลฯ)"))
                continue
            if locked_room_id is not None and chosen["room_id"] != locked_room_id:
                print(f"[assign] {s.get('subject_id')}: ห้อง {locked_room_id} ไม่ว่าง ใช้ห้อง {chosen['room_id']} แทน")

            item = record_assignment(s, chosen)
            assigned.append(item)
            if track_day:
                result_day = day_of(chosen["timeslot_ids"][0])
            if locked_room_id is None:
                locked_room_id = chosen["room_id"]  # ← ล็อกห้องไว้ให้ block ถัดไปใช้ตาม
        return result_day

    # กรณี 2: มี section คู่ขนาน (parallel/team-teaching) — รองรับ N ตัว (N >= 2)
    # ไม่ใช่แค่คู่ 1/2 เหมือนเดิม (เจอเคสจริง: วิชาที่เปิด 4 section 4 อาจารย์)
    # เรียง label ตามตัวเลข ("1","2","3",...) ไม่รวม None (None ถูกจัดการแยกไปแล้ว
    # ในกรณี 1 ด้านบน — ถ้ามาถึงตรงนี้ได้แปลว่ามี label ตัวเลขอยู่อย่างน้อย 1 ตัว)
    labels = sorted((k for k in section_keys if k is not None), key=lambda x: int(x))
    lists_by_label = [by_section[label] for label in labels]

    result_day = lecture_day
    max_len = max(len(lst) for lst in lists_by_label)
    for idx in range(max_len):
        block_sections = [lst[idx] if idx < len(lst) else None for lst in lists_by_label]
        present_sections = [s for s in block_sections if s is not None]

        if not present_sections:
            continue

        # มีแค่ตัวเดียวโผล่ในลำดับ block นี้ (labels ไม่สมมาตรกัน — ไม่ควรเกิดปกติ
        # แต่กันไว้เผื่อข้อมูลไม่ครบ) จัดแบบเดี่ยวไปเลย
        if len(present_sections) == 1:
            chosen = _assign_one(present_sections[0], result_day, assigned, failed, prefer_early_day, avoid_days)
            if chosen and track_day:
                result_day = day_of(chosen["timeslot_ids"][0])
            continue

        # กรณีคู่พอดี 2 ตัว — ใช้ logic เดิม (รองรับทั้ง same_teacher/ต่างอาจารย์)
        if len(present_sections) == 2:
            section_a, section_b = present_sections
            result_a = get_valid_slots(section_a["session_id"], limit=None)
            result_b = get_valid_slots(section_b["session_id"], limit=None)

            if result_a.get("error") or not result_a["valid_slots"]:
                failed.append(_fail_entry(section_a, result_a.get("error", "ไม่มี slot ว่างเลย")))
                continue
            if result_b.get("error") or not result_b["valid_slots"]:
                failed.append(_fail_entry(section_b, result_b.get("error", "ไม่มี slot ว่างเลย")))
                continue

            current = get_current_schedule_raw()
            teachers_a = set(section_a.get("teacher_ids") or [])
            teachers_b = set(section_b.get("teacher_ids") or [])
            same_teacher = bool(teachers_a & teachers_b)

            pair = None
            cand_a, cand_b = _avoid_days(result_a["valid_slots"], avoid_days), _avoid_days(result_b["valid_slots"], avoid_days)
            if cand_a is not result_a["valid_slots"] or cand_b is not result_b["valid_slots"]:
                pair = assign_lab_pair_deterministic(section_a, section_b, cand_a, cand_b, current,
                                                     same_teacher=same_teacher, lecture_day=result_day)
            if pair is None:
                pair = assign_lab_pair_deterministic(
                    section_a, section_b, result_a["valid_slots"], result_b["valid_slots"], current,
                    same_teacher=same_teacher, lecture_day=result_day,
                )

            if pair is None:
                failed.append(_fail_entry(section_a, "ไม่สามารถจัดคู่ section ได้"))
                failed.append(_fail_entry(section_b, "ไม่สามารถจัดคู่ section ได้"))
                continue

            candidate_a, candidate_b = pair
            item_a = record_assignment(section_a, candidate_a)
            assigned.append(item_a)
            item_b = record_assignment(section_b, candidate_b)
            assigned.append(item_b)
            if track_day:
                result_day = day_of(candidate_a["timeslot_ids"][0])
            continue

        # กรณี 3+ section คู่ขนาน — ใช้ assign_group_same_time() (เวลาเดียวกัน
        # ทุกคน คนละห้องหมด สมมติว่าคนละอาจารย์เสมอ เพราะอาจารย์คนเดียวสอนพร้อมกัน
        # หลายห้องไม่ได้อยู่แล้วในทางปฏิบัติ)
        candidates_list = []
        missing = False
        for s in present_sections:
            r = get_valid_slots(s["session_id"], limit=None)
            if r.get("error") or not r["valid_slots"]:
                failed.append(_fail_entry(s, r.get("error", "ไม่มี slot ว่างเลย")))
                missing = True
                continue
            candidates_list.append(r["valid_slots"])
        if missing:
            continue

        current = get_current_schedule_raw()
        group_result = None
        if avoid_days:
            group_result = assign_group_same_time(present_sections, [_avoid_days(c, avoid_days) for c in candidates_list],
                                                  current, lecture_day=result_day)
        if group_result is None:
            group_result = assign_group_same_time(present_sections, candidates_list, current, lecture_day=result_day)

        if group_result is None:
            for s in present_sections:
                failed.append(_fail_entry(s, "ไม่สามารถจัดให้ทุก section เรียนเวลาเดียวกัน (คนละห้อง) ได้"))
            continue

        for s, cand in zip(present_sections, group_result):
            item = record_assignment(s, cand)
            assigned.append(item)
        if track_day:
            result_day = day_of(group_result[0]["timeslot_ids"][0])

    return result_day


def _unit_key(session: dict) -> tuple:
    """คีย์ระบุว่า session นี้เป็น 'วิชาหน่วยเดียวกัน' กับ session ไหนบ้าง สำหรับใช้จัดกลุ่ม
    ก่อนจัดตาราง (1 unit = 1 วิชา ที่ต้องจัดทั้ง LECTURE+LAB ให้เสร็จก่อนวิชาอื่น)

    ใช้ (subject_id, group_ids) แทน subject_selected_id ตรงๆ เพราะ LAB ของ
    "parallel group" (หลายแถว subject_selected คนละอาจารย์ วิชา+ปี+กลุ่มนิสิต
    เดียวกัน) ยังคงแยกคนละ subject_selected_id กันอยู่ (คนละ session_id) แต่
    ต้องถูกมองเป็น "วิชาเดียวกัน" ตอนจัดตาราง ถึงจะจับคู่ pairing กันได้ถูก
    (ดู section_logic.py หัวข้อ parallel group)
    """
    return (session["subject_id"], tuple(sorted(session.get("group_ids") or [])))


def _unit_student_count(unit: dict, groups_map: dict) -> int:
    """[ใหม่] จำนวนนิสิตสูงสุดของวิชา (unit) นี้ — ใช้เป็นเกณฑ์เรียงลำดับรอง"""
    best = 0
    for s in unit["lecture"] + unit["lab"]:
        count = s.get("max_capacity") or sum(groups_map.get(g, 0) for g in (s.get("group_ids") or []))
        best = max(best, count or 0)
    return best


def _unit_order_key(key: tuple, unit: dict, groups_map: dict, priority: set = frozenset()) -> tuple:
    """[ใหม่] ลำดับการจัดวิชา (วิชาที่ "จัดยาก" ได้เลือกช่องก่อน):
      P) วิชาที่ "เคยจัดไม่ได้" ในรอบก่อน (priority) ได้จัดก่อนเลย — ใช้ตอนจัดซ้ำใน auto_assign_all()
      0) วิชาเรียนรวดหลายชั่วโมงก่อนทุกวิชา — มีช่องให้ลงน้อยที่สุด (3 ชม. รวด ลงได้แค่
         08-11 / 13-16 = 10 ช่องต่อสัปดาห์) ถ้าจัดทีหลัง ช่องมักถูกวิชาอื่นแย่งไปหมด
      1) ผูกกับหลายกลุ่มนิสิตก่อน (เหมือนเดิม — ต้องหาช่องที่ทุกกลุ่มว่างพร้อมกัน)
      2) มีคาบปฏิบัติก่อน (ห้องแล็บมีน้อย + ต้องหาวันที่ไม่ชนกับ LECTURE)
      3) นิสิตเยอะก่อน (ห้องที่จุพอมีน้อยกว่า)
      4) รหัสวิชา — กันลำดับสลับไปมาเองระหว่างรอบ (ผลจัดคงที่ทุกครั้ง)
    """
    return (
        0 if key[0] in priority else 1,
        0 if any(s.get("continuous_size") for s in unit["lecture"]) else 1,
        -len(unit["group_ids"] or []),
        0 if unit["lab"] else 1,
        -_unit_student_count(unit, groups_map),
        str(key[0]),
        key[1],
    )


def _days_of_sessions(session_ids: set) -> set[str]:
    """[ใหม่] คืน set ของ "ทุกวัน" ที่ session เหล่านี้ถูกจัดลงไปแล้วในตารางปัจจุบัน"""
    days = set()
    for a in get_current_schedule_raw():
        if a.get("session_id") in session_ids:
            d = day_of(a["timeslot_id"])
            if d:
                days.add(d)
    return days


def _lecture_ids_for_lab_unit(unit_key: tuple, sessions: list[dict]) -> set[str]:
    """[แก้บั๊ก] session_id ของ LECTURE "ทุกตัว" ที่เป็นของ LAB unit นี้

    เดิมหา LECTURE เฉพาะใน unit เดียวกัน (key = subject_id + group_ids) แต่ LECTURE ที่
    เรียนรวมข้ามกลุ่ม (lecture_combine_group เช่น CS-Y4 + IT-Y4 เรียนร่วมกัน) ถูกสร้างเป็น
    session เดียวที่มี group_ids รวมทุกกลุ่ม -> key ไม่ตรงกับ LAB ของแต่ละกลุ่ม -> LAB หา
    LECTURE ของตัวเองไม่เจอ -> ไม่ได้เช็คกฎ "LAB ห้ามวันเดียวกับ LECTURE" เลย
    (เจอจริงกับ 254483 ปี 4 ที่ LECTURE กับ LAB ตกวันจันทร์ทั้ง CS และ IT)

    ตอนนี้จับคู่ด้วย "วิชาเดียวกัน + มีกลุ่มนิสิตร่วมกัน" แบบเดียวกับ move_session()
    """
    subject_id, groups = unit_key[0], set(unit_key[1])
    return {
        s["session_id"] for s in sessions
        if s["session_type"] == "LECTURE"
        and s["subject_id"] == subject_id
        and (not groups or groups & set(s.get("group_ids") or []))
    }


def _lookup_timeslot(timeslots_by_id: dict, tid):
    """หา timeslot จาก id โดยไม่สนว่า id เป็น int หรือ str (โค้ดส่วนอื่นอย่าง
    find_issues.py ใช้ str(timeslot_id) เป็น key เสมอ แปลว่าชนิดของ id อาจปนกัน
    ถ้า lookup ตรงๆ แล้วชนิดไม่ตรง ทุก slot จะถูกตัดทิ้งเงียบๆ)"""
    for k in (tid, str(tid)):
        if k in timeslots_by_id:
            return timeslots_by_id[k]
    try:
        return timeslots_by_id.get(int(tid))
    except (TypeError, ValueError):
        return None


def _slot_in_window(candidate: dict, timeslots_by_id: dict, window: tuple[str, str] | None) -> bool:
    """candidate ทุก timeslot ต้องเริ่ม/จบอยู่ในช่วง window (None = ไม่จำกัด)
    (คอลัมน์ในตาราง timeslots: timeslot_id, block_id, day, start_time, end_time
    เวลาเป็นรูปแบบ 'HH:MM:SS' จึงตัดเหลือ 'HH:MM' เทียบเป็น string ได้ตรงๆ)
    """
    if window is None:
        return True
    lo, hi = window
    for tid in candidate["timeslot_ids"]:
        ts = _lookup_timeslot(timeslots_by_id, tid)
        if not ts:
            return False
        if str(ts["start_time"])[:5] < lo or str(ts["end_time"])[:5] > hi:
            return False
    return True


def _assign_sync_lecture_groups(by_subject: dict, assigned: list, failed: list) -> dict:
    """จัด LECTURE ของวิชาใน SYNC_LECTURE_GROUPS ให้ 'เวลาเดียวกัน คนละห้อง'
    (ข้ามคนละ unit / คนละกลุ่มนิสิตได้) โดยใช้ assign_group_same_time() เดิม
    และจำกัดช่วงเวลาตาม SYNC_TIME_WINDOWS (ถ้ากลุ่มนั้นตั้งไว้)

    - จับคู่ตาม "ลำดับ block" (block แรกของวิชา A คู่กับ block แรกของวิชา B ฯลฯ)
    - session ที่จัดสำเร็จแล้วจะถูกตัดออกจาก unit["lecture"] เพื่อไม่ให้
      _assign_pass จัดซ้ำอีกรอบ
    - ถ้าจัดพร้อมกันไม่ได้:
        SYNC_STRICT=True  -> ลง failed ทั้ง block แล้วตัดออกจาก unit ด้วย (ไม่ถูกจัดซ้ำ)
        SYNC_STRICT=False -> ปล่อยไว้ให้ไปจัดแยกตามปกติ

    คืน {unit_key: วันของ LECTURE ที่จัดได้} ไว้ให้ LAB ของ unit นั้นใช้เป็น lecture_day
    (กฎ LECTURE กับ LAB ต้องคนละวัน)
    """
    sync_days: dict = {}
    timeslots_by_id = {t["timeslot_id"]: t for t in get_cached_data()["timeslots"]}

    for subject_ids in SYNC_LECTURE_GROUPS:
        window = SYNC_TIME_WINDOWS.get(tuple(subject_ids))
        if len(subject_ids) == 1:
            # [ใหม่] วิชาเดียวกัน: ทุก unit (คนละกลุ่มนิสิต) ของวิชานี้ต้องตรงเวลากัน
            keys = sorted(k for k, u in by_subject.items() if k[0] == subject_ids[0] and u["lecture"])
            if len(keys) < 2:
                continue
        else:
            # หา unit ของแต่ละวิชา (ต้องเจอครบและมี LECTURE ทุกวิชา ไม่งั้นข้ามกลุ่มนี้)
            unit_of: dict = {}
            for key, unit in by_subject.items():
                if key[0] in subject_ids and unit["lecture"]:
                    unit_of.setdefault(key[0], key)
            if len(unit_of) < len(subject_ids):
                continue
            keys = [unit_of[sid] for sid in subject_ids]
        lists = [sorted(by_subject[k]["lecture"], key=lambda s: s["session_id"]) for k in keys]

        def _remove_from_units(block_sessions):
            ids = {s["session_id"] for s in block_sessions}
            for k in keys:
                by_subject[k]["lecture"] = [
                    s for s in by_subject[k]["lecture"] if s["session_id"] not in ids
                ]

        def _give_up(block_sessions, reason):
            """ไม่ strict: ทำอะไรเลย (ปล่อยให้ไปจัดแยก) / strict: ลง failed + ตัดออก"""
            if not SYNC_STRICT:
                return
            for s in block_sessions:
                failed.append(_fail_entry(s, reason))
            _remove_from_units(block_sessions)

        last_day = None
        for idx in range(min(len(lst) for lst in lists)):
            block = [lst[idx] for lst in lists]

            candidates_list = []
            reason = None
            for s in block:
                r = get_valid_slots(s["session_id"], limit=None)
                if r.get("error") or not r["valid_slots"]:
                    reason = f"{s.get('subject_id')}: " + str(r.get("error", "ไม่มี slot ว่างเลย"))
                    break
                valid = [c for c in r["valid_slots"] if _slot_in_window(c, timeslots_by_id, window)]
                if not valid:
                    reason = (
                        f"{s.get('subject_id')}: ไม่มี slot ว่างในช่วงเวลาที่กำหนด "
                        f"{window}"
                    )
                    break
                candidates_list.append(valid)

            if reason is not None:
                _give_up(block, reason)
                continue

            current = get_current_schedule_raw()
            result = assign_group_same_time(block, candidates_list, current, lecture_day=last_day)

            if result is None:
                _give_up(block, "ไม่สามารถจัดให้เรียนเวลาเดียวกัน (คนละห้อง) กับวิชาคู่ได้")
                continue

            for s, cand in zip(block, result):
                assigned.append(record_assignment(s, cand))
            last_day = day_of(result[0]["timeslot_ids"][0])

            _remove_from_units(block)
            for k in keys:
                sync_days[k] = last_day

    return sync_days


def _assign_pass(look_ahead_lab: bool = True, priority: set = frozenset()) -> tuple[list, list]:
    """จัดตารางทั้งหมด 1 รอบ (ไม่ reset) — ใช้ทั้งตอนจัดครั้งแรกและตอน retry
    หลัง fix บางส่วน คืน (assigned, failed) ของรอบนี้เท่านั้น
    priority = รหัสวิชาที่ให้จัดก่อนวิชาอื่น (วิชาที่เคยจัดไม่ได้ในรอบก่อน)
    """
    sessions = build_session_list()

    assigned: list = []
    failed: list = []

    by_subject: dict[tuple, dict] = {}
    for s in sessions:
        key = _unit_key(s)
        unit = by_subject.setdefault(key, {"lecture": [], "lab": [], "group_ids": s["group_ids"]})
        if s["session_type"] == "LECTURE":
            unit["lecture"].append(s)
        else:
            unit["lab"].append(s)

    # [แก้] เรียงวิชาด้วยหลายเกณฑ์ (ดู _unit_order_key) แทนเกณฑ์เดียว — ผลคงที่ทุกรอบ
    groups_map = {g["group_id"]: g["total_students"] for g in get_cached_data()["groups"]}
    subject_order = sorted(by_subject.keys(), key=lambda k: _unit_order_key(k, by_subject[k], groups_map, priority))

    # [ใหม่] จำ session_id ของ LECTURE ทุกตัวในแต่ละวิชาไว้ก่อน (รวมตัวที่จะถูกจัด
    # ในกลุ่ม sync ซึ่งจะถูกตัดออกจาก unit["lecture"]) เอาไว้หา "ทุกวัน" ที่มี LECTURE
    lecture_ids_by_unit = {k: {s["session_id"] for s in u["lecture"]} for k, u in by_subject.items()}

    # จัด LECTURE ของวิชาที่ต้องเวลาตรงกันก่อน (ข้ามคนละ unit) — session ที่จัดแล้ว
    # จะถูกตัดออกจาก unit["lecture"] ในฟังก์ชันนี้เอง
    _assign_sync_lecture_groups(by_subject, assigned, failed)

    for unit_key in subject_order:
        unit = by_subject[unit_key]

        if unit["lecture"]:
            # LAB ของวิชานี้ (รวม LAB ของกลุ่มที่เรียน LECTURE ร่วมกัน)
            lec_groups = {g for s in unit["lecture"] for g in s.get("group_ids") or []}
            labs = [s for s in sessions if s["session_type"] == "LAB" and s["subject_id"] == unit_key[0]
                    and lec_groups & set(s.get("group_ids") or [])]
            _assign_paired_group(unit["lecture"], None, assigned, failed, prefer_early_day=True,
                                 avoid_days=_lecture_days_to_avoid(labs) if look_ahead_lab else None)

        if unit["lab"]:
            # [แก้] ส่ง "ทุกวัน" ที่มี LECTURE ของวิชานี้ให้ LAB (เดิมส่งแค่วันของ
            # LECTURE block สุดท้าย → LAB ไปลงวันเดียวกับ LECTURE block แรกได้)
            # [แก้บั๊ก] รวม LECTURE ที่เรียนร่วมกับกลุ่มอื่นด้วย (ดู _lecture_ids_for_lab_unit)
            lecture_ids = lecture_ids_by_unit.get(unit_key, set()) | _lecture_ids_for_lab_unit(unit_key, sessions)
            lecture_days = _days_of_sessions(lecture_ids) or None
            _assign_paired_group(unit["lab"], lecture_days, assigned, failed)

    return assigned, failed


def _fix_all_sessions(hard_issues: list[dict]) -> dict:
    """ย้าย session ที่ก่อปัญหา hard issue ทีละตัว (ตัดซ้ำด้วย seen) — ยกมาจาก
    scheduling_agent.py เดิม (_fix_all_sessions) แค่ย้ายมาไว้ในนี้ ไม่เปลี่ยน logic
    """
    fixed, failed, seen = [], [], set()
    for issue in hard_issues:
        session_id = issue.get("fix_session_id")
        if not session_id or session_id in seen:
            continue
        seen.add(session_id)
        result = move_session(session_id)
        if result.get("success"):
            fixed.append(session_id)
        else:
            failed.append({"session_id": session_id, "reason": result.get("reason")})
    return {"fixed_session_ids": fixed, "failed": failed}


def auto_assign_all() -> dict:
    """รีเซ็ตตารางที่ AI จัดไว้ แล้วจัดใหม่ทั้งหมด — จัดทีละ 'วิชา' (LECTURE เสร็จแล้ว
    ตามด้วย LAB ของวิชาเดียวกันทันที) เรียงวิชาที่ผูกกับหลายกลุ่มพร้อมกันให้จัดก่อนเสมอ

    แก้ไขล่าสุด: หลังจัดครั้งแรกจบ วน "ตรวจสอบ + แก้ไข hard issues" ต่อในตัวเองอีก
    สูงสุด MAX_FIX_ROUNDS รอบ (Python ล้วน ไม่ผ่าน LLM) — ก่อนหน้านี้ส่วนนี้อยู่ใน
    scheduling_agent.py ให้ checker_agent (LLM) เป็นคนสั่งวนทีละรอบผ่าน tool call
    ซึ่งเปลือง Gemini quota มาก (เสี่ยงชน 429 กลางทาง) และเสี่ยง tool ถูกเรียกผิด
    agent เวลามีปัญหาเรื่อง session สะสม ย้ายมาไว้ในนี้ผลลัพธ์จะ deterministic และ
    ไม่ต้องพึ่ง Gemini API เลยในขั้นตอนจัดตาราง (เหลือ agent ชั้นนอกไว้แค่สรุปผล)
    """
    from .failure_analysis import snapshot_rows, restore_rows

    # คะแนน (น้อย = ดี): วิชาที่จัดไม่ได้ -> ปัญหาชนกัน -> ปัญหา soft (เช่น LAB อยู่ก่อน LECTURE)
    score = lambda r: (r["failed_count"], r["remaining_hard_issue_count"], r["remaining_soft_issue_count"])

    best = _full_run(look_ahead_lab=True)
    best_rows = None      # snapshot ของรอบที่ดีที่สุด (ถ่ายเมื่อจำเป็นต้องจัดซ้ำเท่านั้น)
    db_has_best = True    # ตารางในฐานข้อมูลตอนนี้คือรอบที่ดีที่สุดหรือยัง
    priority: set = set()

    # [ใหม่] จัดซ้ำหลายรอบ (multi-start) — ทำเฉพาะตอนมีวิชาที่จัดไม่ได้ ถ้ารอบแรกครบก็จบเลย
    # ตัวจัดมีการสุ่ม แต่ละรอบได้ตารางต่างกัน -> ลองใหม่สูงสุด EXTRA_ATTEMPTS รอบ หยุดทันทีที่จัดครบ
    #   - วิชาที่เคยจัดไม่ได้ (สะสมทุกรอบ) ได้จัดก่อนวิชาอื่นในรอบถัดไป
    #   - สลับโหมด: รอบคี่ = LECTURE ไม่เลี่ยงวันท้ายสัปดาห์ (สัปดาห์แน่น) / รอบคู่ = เลี่ยงตามปกติ
    #   - เก็บรอบที่คะแนนดีที่สุดไว้เสมอ
    for attempt in range(1, EXTRA_ATTEMPTS + 1):
        if not best["failed_count"]:
            break
        priority |= {f["subject_id"] for f in best["failed"] if f.get("subject_id")}
        if db_has_best:
            best_rows = snapshot_rows()
        look_ahead = attempt % 2 == 0
        result = _full_run(look_ahead_lab=look_ahead, priority=priority)
        priority |= {f["subject_id"] for f in result["failed"] if f.get("subject_id")}
        better = score(result) < score(best)
        print(f"[assign] จัดซ้ำรอบ {attempt}/{EXTRA_ATTEMPTS} "
              f"(เลี่ยงวันท้าย={look_ahead}, จัดก่อน={sorted(priority)}): "
              f"{score(best)} -> {score(result)}{' ✓ ดีขึ้น' if better else ''}")
        if better:
            best, db_has_best = result, True
        else:
            db_has_best = False

    if not db_has_best:
        restore_rows(best_rows)
    return best


# จำนวนรอบที่ยอมจัดใหม่ เมื่อรอบแรกมีวิชาที่จัดไม่ได้ (0 = ไม่จัดซ้ำ)
# รอบละ ~70 วินาที เสียเวลาเพิ่มเฉพาะรอบที่มีวิชาตกเท่านั้น
EXTRA_ATTEMPTS = 3


def _full_run(look_ahead_lab: bool, priority: set = frozenset()) -> dict:
    """จัดทั้งตารางใหม่ 1 รอบ + ซ่อม hard issue (ใช้ใน auto_assign_all)"""
    reset_ai_schedule()

    assigned, failed = _assign_pass(look_ahead_lab, priority)

    issues = find_issues()
    hard_issues = [i for i in issues if i.get("severity") == "hard"]
    soft_issues = [i for i in issues if i.get("severity") == "soft"]

    # นับเฉพาะรอบซ่อม (ไม่นับรอบจัดครั้งแรก) — MAX_FIX_ROUNDS = ซ่อมได้กี่รอบจริง
    fix_rounds_used = 0
    while hard_issues and fix_rounds_used < MAX_FIX_ROUNDS:
        _fix_all_sessions(hard_issues)
        issues = find_issues()
        hard_issues = [i for i in issues if i.get("severity") == "hard"]
        soft_issues = [i for i in issues if i.get("severity") == "soft"]
        fix_rounds_used += 1

    return {
        "assigned_count": len(assigned),
        "failed_count": len(failed),
        "assigned": assigned,
        "failed": failed,
        "rounds_used": fix_rounds_used,  # จำนวนรอบซ่อม (0 = จัดครั้งแรกไม่มีปัญหา)
        "converged": len(hard_issues) == 0,
        "remaining_hard_issue_count": len(hard_issues),
        "remaining_soft_issue_count": len(soft_issues),
    }

# ─────────────────────────────────────────────────────────────────────────
# [ใหม่] จัดซ้ำ "เฉพาะวิชาที่ยังจัดไม่ได้" ตามคำแนะนำของ CheckerAgent
#
# ต่างจาก auto_assign_all() ที่ลบทั้งตารางแล้วจัดใหม่หมด ตัวนี้คงตารางเดิมไว้ทั้งหมด
# แตะเฉพาะวิชาที่จัดไม่ได้ กับวิชาที่ขวางมันอยู่เท่านั้น:
#   1) ถอดวิชาที่ขวาง (blocker) ออก
#   2) วางวิชาที่จัดไม่ได้ลงไป (ผ่าน move_session — เช็คกฎครบ + รักษาคู่ section)
#   3) หาที่ใหม่ให้วิชาที่ขวาง (ห้ามกลับไปคาบเดิม — ดู retry_hints.forbidden)
#   ขั้นไหนไม่สำเร็จ คืนตารางกลับเป็นก่อนเริ่มขั้นนี้ทั้งหมด (ไม่มีค้างครึ่งๆ กลางๆ)
# ─────────────────────────────────────────────────────────────────────────

def _sync_subject_ids() -> set[str]:
    return {sid for group in SYNC_LECTURE_GROUPS for sid in group}


def can_retry_session(session: dict | None) -> bool:
    """วิชาที่ระบบจัดซ้ำเฉพาะจุดไม่ได้ (ให้ผู้ใช้ลากวางเอง):
    - เรียนรวดหลายชั่วโมง (move_session หาได้แค่ช่อง 2 ชม.)
    - LECTURE ที่ต้องตรงเวลากับวิชาอื่น (SYNC_LECTURE_GROUPS) — ย้ายเดี่ยวจะไม่ตรงเวลากัน
    """
    if not session or session.get("continuous_size"):
        return False
    if session.get("session_type") == "LECTURE" and session.get("subject_id") in _sync_subject_ids():
        return False
    return True


def _unplaced_sessions(previous_failed: list[dict]) -> list[dict]:
    """session ที่ควรมีแต่ยังไม่อยู่ในตาราง (คงเหตุผลเดิมไว้ถ้ามี)"""
    reasons = {f.get("session_id"): f.get("reason") for f in previous_failed}
    placed = {a.get("session_id") for a in get_current_schedule_raw() if a.get("session_id")}
    return [
        _fail_entry(s, reasons.get(s["session_id"]) or "ยังจัดไม่ได้")
        for s in build_session_list()
        if s["session_id"] not in placed
    ]


def retry_failed_sessions(hints: dict, previous_failed: list[dict], moves: list[dict]) -> dict:
    """จัดซ้ำเฉพาะวิชาที่ยังไม่ลงตาราง (ไม่แตะวิชาอื่นที่จัดได้แล้ว)

    Args:
        hints: คำแนะนำสะสม {"priority_subject_ids": [...], "forbidden": {session_id: [timeslot_id]}}
        previous_failed: รายการวิชาที่จัดไม่ได้จากรอบก่อน
        moves: ขั้นตอนที่ CheckerAgent เลือก [{"session_id": วิชาที่ขวาง,
               "timeslot_ids": คาบที่ให้เว้น, "for_session_id": วิชาที่จัดไม่ได้}]
    คืนผลหน้าตาเดียวกับ auto_assign_all() + "moves" (บันทึกว่าแต่ละขั้นสำเร็จไหม)
    """
    from .failure_analysis import snapshot_rows, restore_rows

    sessions_by_id = {s["session_id"]: s for s in build_session_list()}
    move_log = []

    set_active(hints)
    try:
        # 1) ทำตามขั้นตอนที่ Agent เลือก: ถอดวิชาที่ขวาง -> วางวิชาที่ไม่ลง -> หาที่ใหม่ให้วิชาที่ขวาง
        for mv in moves:
            target, blocker = mv.get("for_session_id"), mv.get("session_id")
            placed = {a.get("session_id") for a in get_current_schedule_raw()}
            if target in placed:
                continue  # ลงไปแล้วจากขั้นก่อนหน้า
            if not (can_retry_session(sessions_by_id.get(target)) and can_retry_session(sessions_by_id.get(blocker))):
                move_log.append({**mv, "success": False, "reason": "วิชานี้ต้องลากวางเอง"})
                continue

            before = snapshot_rows()
            delete_session_assignment(blocker)
            placed_target = move_session(target)
            if not placed_target.get("success"):
                restore_rows(before)
                move_log.append({**mv, "success": False, "reason": placed_target.get("reason")})
                continue
            replaced_blocker = move_session(blocker)
            if not replaced_blocker.get("success"):
                restore_rows(before)
                move_log.append({**mv, "success": False,
                                 "reason": f"วิชาที่ขวางหาที่ใหม่ไม่ได้: {replaced_blocker.get('reason')}"})
                continue
            move_log.append({**mv, "success": True})

        # 2) วิชาที่ยังไม่ลง ลองวางอีกครั้ง (ตารางอาจมีช่องว่างเพิ่มจากขั้นที่ 1) — วิชาที่แนะนำให้จัดก่อนได้ลองก่อน
        prio = hints.get("priority_subject_ids") or []
        pending = sorted(
            _unplaced_sessions(previous_failed),
            key=lambda f: prio.index(f["subject_id"]) if f.get("subject_id") in prio else len(prio),
        )
        for f in pending:
            if can_retry_session(sessions_by_id.get(f["session_id"])):
                before = snapshot_rows()
                if not move_session(f["session_id"]).get("success"):
                    restore_rows(before)

        # 3) ซ่อม hard issue ที่อาจเกิดใหม่ (วิธีเดียวกับ auto_assign_all)
        issues = find_issues()
        hard_issues = [i for i in issues if i.get("severity") == "hard"]
        fix_rounds_used = 0
        while hard_issues and fix_rounds_used < MAX_FIX_ROUNDS:
            _fix_all_sessions(hard_issues)
            issues = find_issues()
            hard_issues = [i for i in issues if i.get("severity") == "hard"]
            fix_rounds_used += 1
        soft_issues = [i for i in issues if i.get("severity") == "soft"]
    finally:
        clear_active()  # ล้างทุกครั้ง ไม่ให้ค้างไปกระทบการลากย้ายด้วยมือ

    failed = _unplaced_sessions(previous_failed)
    placed_count = len({a.get("session_id") for a in get_current_schedule_raw() if a.get("session_id")})
    return {
        "assigned_count": placed_count,
        "failed_count": len(failed),
        "assigned": [],
        "failed": failed,
        "rounds_used": fix_rounds_used,
        "converged": len(hard_issues) == 0,
        "remaining_hard_issue_count": len(hard_issues),
        "remaining_soft_issue_count": len(soft_issues),
        "moves": move_log,
    }