"""
auto_assign.py
จัดตารางทีละ "วิชา" (ไม่ใช่แยก LECTURE ทั้งหมดก่อน LAB ทั้งหมด) โดยเรียงวิชาที่
"ยากที่สุด" ก่อนเสมอ — วิชาที่ผูกกับหลายกลุ่มนิสิตพร้อมกัน (เช่น Y3+Y4) ต้องได้
ทั้ง LECTURE และ LAB ของตัวเองจัดเสร็จก่อนวิชาอื่นทุกตัว ไม่ใช่แค่ LECTURE เท่านั้น
(ถ้าแยก LECTURE ทั้งหมดก่อน LAB ทั้งหมด วิชาอื่นจะแย่ง slot ที่ Y3+Y4 ว่างพร้อมกัน
ไปหมดก่อนถึงตา LAB ของวิชา 2 กลุ่ม แม้จะได้ priority ตอน LECTURE ก็ตาม)

แก้ไข: เดิม LECTURE ของวิชาที่มี 2 section (1/2) จัดทีละ session แยกกันอิสระ
ไม่มีการจับคู่เหมือน LAB เลย ทำให้ 2 section ของ LECTURE ไปตกคนละเวลากันมั่ว
ตอนนี้เปลี่ยนมาใช้ฟังก์ชันเดียวกัน (_assign_paired_group) กับทั้ง LECTURE และ LAB:
  - section คู่ 1/2 ที่มีอาจารย์คนเดียวกันสอนทั้งคู่ -> ห้องเดียวกัน เวลาติดกัน (เดิม)
  - section คู่ 1/2 ที่มีอาจารย์คนละคนสอน           -> เวลาเดียวกัน คนละห้อง (ใหม่)
นอกจากนี้ LECTURE กับ LAB ของวิชาเดียวกันตอนนี้บังคับ (hard) ว่าต้องคนละวันเสมอ
(แก้ใน candidate_scorer.py แล้ว)

แก้ไขล่าสุด: เปลี่ยน key ที่ใช้จัดกลุ่ม session เป็น "หน่วยเดียวกัน" จาก
subject_selected_id ตรงๆ เป็น (subject_id, group_ids) แทน — เพราะตอนนี้
section_logic.py รองรับ "parallel group" (หลายแถว subject_selected คนละอาจารย์
แต่วิชา+ปี+กลุ่มนิสิตเดียวกัน) โดยรวม LECTURE เป็น session เดียว (ใช้
subject_selected_id ของสมาชิกตัวแรกเป็นตัวแทน) แต่ LAB ยังคงแยกคนละ session
ต่อ subject_selected_id เดิม — ถ้ายังจัดกลุ่ม unit ด้วย subject_selected_id
ตรงๆ เหมือนเดิม LAB ของแต่ละ parallel section จะกลายเป็นคนละ unit ไม่เห็นกัน
เลย ทำให้ pairing (_assign_paired_group) ไม่ทำงานข้าม unit ได้ ต้องเปลี่ยนมา
จัดกลุ่มด้วย (subject_id, group_ids) ถึงจะเห็น LAB ของ parallel sections
อยู่ใน unit เดียวกัน จับคู่กันได้ถูกต้อง

เพิ่มเติมล่าสุด: รองรับวิชาที่ต้องเรียน LECTURE ติดกันหลาย block ในวันเดียว
(เช่น 4 ชม. รวด = 2 block ติดกัน ไม่แยกวัน) ผ่าน _assign_continuous_block()
วิชาที่ต้องการแบบนี้ต้องมี continuous_size ตั้งไว้ตอนสร้าง session ใน
section_logic.py (ดู CONTINUOUS_SUBJECT_SELECTED_IDS)
"""

from agent_timetable.tools.get_data import supabase
from .load_data import refresh_cache, get_cached_data
from .section_logic import build_session_list
from .slot_filter import get_valid_slots, get_valid_continuous_slots, _timeslot_label
from .candidate_picker import pick_best_candidate, assign_lab_pair_deterministic
from .candidate_scorer import day_of
from .assignment_store import record_assignment, get_current_schedule, get_current_schedule_raw, move_session

__all__ = ["auto_assign_all", "get_current_schedule", "move_session"]


def reset_ai_schedule() -> None:
    """ลบตารางที่ AI เคยจัดไว้ทั้งหมด (ไม่แตะ existing/GENERAL ที่ล็อกไว้ต่างหาก)"""
    supabase.table("timetable_ai").delete().neq("id", 0).execute()
    refresh_cache()


def _assign_one(session, lecture_day, assigned, failed, prefer_early_day=False):
    """จัด session เดียวแบบปกติ (ไม่ pairing) คืน chosen candidate หรือ None ถ้าล้มเหลว"""
    result = get_valid_slots(session["session_id"], limit=None)
    if result.get("error") or not result["valid_slots"]:
        failed.append({
            "session_id": session["session_id"],
            "reason": result.get("error", "ไม่มี slot ว่างเลย"),
        })
        return None

    current = get_current_schedule_raw()
    chosen = pick_best_candidate(session, result["valid_slots"], lecture_day, current, prefer_early_day)
    if chosen is None:
        failed.append({"session_id": session["session_id"], "reason": "ไม่สามารถเลือก candidate ได้"})
        return None

    item = record_assignment(session, chosen)
    assigned.append(item)
    return chosen


def _assign_continuous_block(sessions, lecture_day, assigned, failed, prefer_early_day=False):
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
        failed.append({
            "session_id": session["session_id"],
            "reason": result.get("error", f"ไม่มีวันไหนว่างครบ {num_units} ชม. ติดกันเลย"),
        })
        return lecture_day

    current = get_current_schedule_raw()
    chosen = pick_best_candidate(session, result["valid_slots"], lecture_day, current, prefer_early_day)
    if chosen is None:
        failed.append({"session_id": session["session_id"], "reason": "ไม่สามารถเลือก candidate ได้"})
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


def _assign_paired_group(sessions, lecture_day, assigned, failed, prefer_early_day=False):
    """จัด session ของวิชาเดียว 1 ประเภท (LECTURE หรือ LAB) ให้ครบ ไม่ว่าจะมี section
    เดียวหรือคู่ 1/2 — ถ้ามี section คู่ จะเช็คว่าอาจารย์เป็นคนเดียวกันหรือคนละคน
    เพื่อเลือกวิธีจับคู่ที่ถูกต้อง (ห้องเดียวกัน+ติดกัน หรือ เวลาเดียวกัน+คนละห้อง)

    แก้ไขล่าสุด (สำคัญ): เดิมฟังก์ชันนี้สมมติว่ามีแค่ 2 กรณี "section เดียวไม่มีคู่" (list
    ยาว 1) หรือ "คู่ 1/2 พอดี 2 ตัว" — แต่ถ้าวิชามี lecture_hours/lab_hours > 1 block
    "และ" ไม่มีการแบ่ง section เลย (ทุก session ในลิสต์มี section=None ทั้งหมด แต่มี
    มากกว่า 1 block) เดิมโค้ดจะหยิบแค่ตัวแรกมาเป็น section_a แล้วมองว่า section_b
    หาไม่เจอ (ไม่มีใคร label "2") เลยจัดแค่ block แรก block ที่เหลือหายไปเงียบๆ
    ไม่มี error ให้เห็นเลย (เช่น lecture_hours=2 แต่ถูกจัดแค่ 1 คาบ)

    ตอนนี้แยกจัดการ 3 กรณีให้ชัดเจน:
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
        return _assign_continuous_block(sessions, lecture_day, assigned, failed, prefer_early_day)

    sessions = sorted(sessions, key=lambda s: (s.get("section") or "", s["session_id"]))

    by_section: dict[str | None, list[dict]] = {}
    for s in sessions:
        by_section.setdefault(s.get("section"), []).append(s)

    section_keys = set(by_section.keys())

    # กรณี 1: ไม่มีการแบ่ง section เลย (ทุกตัว section=None) — จัดแยกอิสระทีละ block
    # ไม่ว่าจะมีกี่ block ก็ตาม (เดิมพังตรงนี้ถ้ามีมากกว่า 1 block)
    # บังคับให้ทุก block ใช้ "ห้องเดียวกัน" เสมอ (นิสิตจะได้ไม่ต้องสับสนห้องระหว่างสัปดาห์)
    # — block แรกเลือกห้องได้อิสระตามปกติ ส่วน block ที่ 2 เป็นต้นไป กรอง valid_slots
    # ให้เหลือแค่ห้องเดียวกับ block แรกก่อนค่อยหา candidate
    if section_keys == {None}:
        result_day = lecture_day
        locked_room_id: str | None = None
        for s in by_section[None]:
            result = get_valid_slots(s["session_id"], limit=None)
            if result.get("error") or not result["valid_slots"]:
                failed.append({
                    "session_id": s["session_id"],
                    "reason": result.get("error", "ไม่มี slot ว่างเลย"),
                })
                continue

            candidates = result["valid_slots"]
            if locked_room_id is not None:
                same_room_candidates = [c for c in candidates if c["room_id"] == locked_room_id]
                if not same_room_candidates:
                    failed.append({
                        "session_id": s["session_id"],
                        "reason": f"ห้อง {locked_room_id} (ห้องเดียวกับ block ก่อนหน้าของวิชานี้) ไม่ว่างเลย ไม่สามารถคงห้องเดิมได้",
                    })
                    continue
                candidates = same_room_candidates

            current = get_current_schedule_raw()
            chosen = pick_best_candidate(s, candidates, result_day, current, prefer_early_day)
            if chosen is None:
                failed.append({"session_id": s["session_id"], "reason": "ไม่สามารถเลือก candidate ได้"})
                continue

            item = record_assignment(s, chosen)
            assigned.append(item)
            result_day = day_of(chosen["timeslot_ids"][0])
            if locked_room_id is None:
                locked_room_id = chosen["room_id"]  # ← ล็อกห้องไว้ให้ block ถัดไปใช้ตาม
        return result_day

    # กรณี 2: มี section คู่ 1/2 (parallel/team-teaching) — จับคู่ตามลำดับ block
    # (block แรกของฝั่ง 1 คู่กับ block แรกของฝั่ง 2 ฯลฯ) รองรับหลาย block ต่อฝั่งด้วย
    list_a = by_section.get(None) or by_section.get("1") or []
    list_b = by_section.get("2") or []

    result_day = lecture_day
    max_len = max(len(list_a), len(list_b))
    for idx in range(max_len):
        section_a = list_a[idx] if idx < len(list_a) else None
        section_b = list_b[idx] if idx < len(list_b) else None

        if section_a is None and section_b is None:
            continue

        if section_a is None or section_b is None:
            # block นี้มีแค่ฝั่งเดียว (จำนวน block ไม่เท่ากันระหว่าง 2 ฝั่ง — ไม่ควรเกิดขึ้น
            # ตามปกติ แต่กันไว้เผื่อข้อมูลไม่สมมาตร) จัดแบบเดี่ยวไปเลย
            single = section_a or section_b
            chosen = _assign_one(single, result_day, assigned, failed, prefer_early_day)
            if chosen:
                result_day = day_of(chosen["timeslot_ids"][0])
            continue

        # มี section คู่ 1+2 ในลำดับ block นี้ — จัดพร้อมกันแบบ deterministic ในขั้นตอนเดียว
        result_a = get_valid_slots(section_a["session_id"], limit=None)
        result_b = get_valid_slots(section_b["session_id"], limit=None)

        if result_a.get("error") or not result_a["valid_slots"]:
            failed.append({
                "session_id": section_a["session_id"],
                "reason": result_a.get("error", "ไม่มี slot ว่างเลย"),
            })
            continue
        if result_b.get("error") or not result_b["valid_slots"]:
            failed.append({
                "session_id": section_b["session_id"],
                "reason": result_b.get("error", "ไม่มี slot ว่างเลย"),
            })
            continue

        current = get_current_schedule_raw()

        # เช็คว่าอาจารย์ของ 2 section เป็นคนเดียวกันไหม (มี teacher_id ร่วมกันอย่างน้อย 1 คน)
        teachers_a = set(section_a.get("teacher_ids") or [])
        teachers_b = set(section_b.get("teacher_ids") or [])
        same_teacher = bool(teachers_a & teachers_b)

        pair = assign_lab_pair_deterministic(
            section_a, section_b, result_a["valid_slots"], result_b["valid_slots"], current,
            same_teacher=same_teacher, lecture_day=result_day,
        )

        if pair is None:
            failed.append({"session_id": section_a["session_id"], "reason": "ไม่สามารถจัดคู่ section ได้"})
            failed.append({"session_id": section_b["session_id"], "reason": "ไม่สามารถจัดคู่ section ได้"})
            continue

        candidate_a, candidate_b = pair
        item_a = record_assignment(section_a, candidate_a)
        assigned.append(item_a)
        item_b = record_assignment(section_b, candidate_b)
        assigned.append(item_b)
        result_day = day_of(candidate_a["timeslot_ids"][0])

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


def auto_assign_all() -> dict:
    """รีเซ็ตตารางที่ AI จัดไว้ แล้วจัดใหม่ทั้งหมด — จัดทีละ 'วิชา' (LECTURE เสร็จแล้ว
    ตามด้วย LAB ของวิชาเดียวกันทันที) เรียงวิชาที่ผูกกับหลายกลุ่มพร้อมกันให้จัดก่อนเสมอ
    """
    reset_ai_schedule()
    sessions = build_session_list()

    assigned = []
    failed = []

    # จัดกลุ่ม session ตาม (subject_id, group_ids) — ดู _unit_key ว่าทำไมไม่ใช้
    # subject_selected_id ตรงๆ (จะทำให้ LAB ของ parallel section แยกคนละ unit)
    by_subject: dict[tuple, dict] = {}
    for s in sessions:
        key = _unit_key(s)
        unit = by_subject.setdefault(key, {"lecture": [], "lab": [], "group_ids": s["group_ids"]})
        if s["session_type"] == "LECTURE":
            unit["lecture"].append(s)
        else:
            unit["lab"].append(s)

    # เรียงวิชาที่มีหลายกลุ่มพร้อมกันให้จัดก่อนเสมอ (ยากที่สุดก่อน)
    subject_order = sorted(by_subject.keys(), key=lambda k: -len(by_subject[k]["group_ids"]))

    for unit_key in subject_order:
        unit = by_subject[unit_key]

        lecture_day = None
        if unit["lecture"]:
            lecture_day = _assign_paired_group(unit["lecture"], None, assigned, failed, prefer_early_day=True)

        if unit["lab"]:
            _assign_paired_group(unit["lab"], lecture_day, assigned, failed)

    return {
        "assigned_count": len(assigned),
        "failed_count": len(failed),
        "assigned": assigned,
        "failed": failed,
    }