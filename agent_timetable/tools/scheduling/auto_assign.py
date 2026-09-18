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

แก้ไขล่าสุด (สำคัญ): ย้าย fix-loop ที่เดิมอยู่ใน scheduling_agent.py
(assign_and_fix_schedule, เรียกผ่าน LLM สั่ง tool ทีละรอบ) เข้ามาไว้ใน
auto_assign_all() เอง — วนแก้ hard issues สูงสุด MAX_FIX_ROUNDS รอบเหมือนเดิม
แต่เป็น Python loop ล้วน ไม่ต้องพึ่ง Gemini API เลยสักครั้งในขั้นตอนนี้
เหตุผล: เดิมแต่ละรอบ fix ต้องให้ LLM (checker_agent) ตัดสินใจวนต่อ ทำให้
1) เปลือง quota เร็ว (ชน 429 กลางทางบ่อย) 2) เสี่ยง tool hallucinate ตอน
session สะสม/สับสนว่าอยู่ agent ไหน 3) ผลลัพธ์ไม่ deterministic เพราะพึ่ง LLM
ตอนนี้ auto_assign_all() คืนค่าที่ "จัดจบสมบูรณ์แล้ว" (ผ่าน fix ครบรอบ) กลับไป
ให้ agent ชั้นนอกแค่สรุปผลให้ user อ่าน ไม่ต้องมีสิทธิ์ตัดสินใจ retry เองอีก

แก้ไขล่าสุด (สำคัญ): เดิม failed.append() ทุกจุดเก็บแค่ {"session_id", "reason"}
ทำให้ frontend เอาไปโชว์ user ไม่ได้เลยว่า "วิชาอะไร" จัดไม่ได้ (มีแต่ session_id
เป็นเลข/uuid อ่านไม่รู้เรื่อง) ตอนนี้เพิ่ม subject_id, session_type, section เข้าไป
ด้วยทุกจุด (ใช้ _fail_entry() เป็นตัวช่วยสร้าง dict ให้ field ตรงกันทุกที่) — ตัว
session/section dict ที่ส่งเข้ามาแต่ละจุดมีข้อมูลพวกนี้อยู่แล้วในมือ (ดู
build_session_list() ใน section_logic.py) แค่ไม่เคยถูกดึงมาใส่ตอน fail เท่านั้น
"""

from agent_timetable.tools.get_data import supabase
from .load_data import refresh_cache, get_cached_data
from .section_logic import build_session_list
from .slot_filter import get_valid_slots, get_valid_continuous_slots, _timeslot_label
from .candidate_picker import pick_best_candidate, assign_lab_pair_deterministic, assign_group_same_time
from .candidate_scorer import day_of
from .assignment_store import record_assignment, get_current_schedule, get_current_schedule_raw, move_session
from .find_issues import find_issues

__all__ = ["auto_assign_all", "get_current_schedule", "move_session"]

MAX_FIX_ROUNDS = 3


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


def _assign_one(session, lecture_day, assigned, failed, prefer_early_day=False):
    """จัด session เดียวแบบปกติ (ไม่ pairing) คืน chosen candidate หรือ None ถ้าล้มเหลว"""
    result = get_valid_slots(session["session_id"], limit=None)
    if result.get("error") or not result["valid_slots"]:
        failed.append(_fail_entry(session, result.get("error", "ไม่มี slot ว่างเลย")))
        return None

    current = get_current_schedule_raw()
    chosen = pick_best_candidate(session, result["valid_slots"], lecture_day, current, prefer_early_day)
    if chosen is None:
        failed.append(_fail_entry(session, "ไม่สามารถเลือก candidate ได้"))
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
        failed.append(_fail_entry(
            session, result.get("error", f"ไม่มีวันไหนว่างครบ {num_units} ชม. ติดกันเลย")
        ))
        return lecture_day

    current = get_current_schedule_raw()
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


def _assign_paired_group(sessions, lecture_day, assigned, failed, prefer_early_day=False):
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
        return _assign_continuous_block(sessions, lecture_day, assigned, failed, prefer_early_day)

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

            candidates = result["valid_slots"]
            if locked_room_id is not None:
                same_room_candidates = [c for c in candidates if c["room_id"] == locked_room_id]
                if not same_room_candidates:
                    failed.append(_fail_entry(
                        s,
                        f"ห้อง {locked_room_id} (ห้องเดียวกับ block ก่อนหน้าของวิชานี้) "
                        "ไม่ว่างเลย ไม่สามารถคงห้องเดิมได้",
                    ))
                    continue
                candidates = same_room_candidates

            current = get_current_schedule_raw()
            chosen = pick_best_candidate(s, candidates, result_day, current, prefer_early_day)
            if chosen is None:
                failed.append(_fail_entry(s, "ไม่สามารถเลือก candidate ได้"))
                continue

            item = record_assignment(s, chosen)
            assigned.append(item)
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
            chosen = _assign_one(present_sections[0], result_day, assigned, failed, prefer_early_day)
            if chosen:
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
        group_result = assign_group_same_time(present_sections, candidates_list, current, lecture_day=result_day)

        if group_result is None:
            for s in present_sections:
                failed.append(_fail_entry(s, "ไม่สามารถจัดให้ทุก section เรียนเวลาเดียวกัน (คนละห้อง) ได้"))
            continue

        for s, cand in zip(present_sections, group_result):
            item = record_assignment(s, cand)
            assigned.append(item)
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


def _assign_pass() -> tuple[list, list]:
    """จัดตารางทั้งหมด 1 รอบ (ไม่ reset) — ใช้ทั้งตอนจัดครั้งแรกและตอน retry
    หลัง fix บางส่วน คืน (assigned, failed) ของรอบนี้เท่านั้น
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

    subject_order = sorted(by_subject.keys(), key=lambda k: -len(by_subject[k]["group_ids"]))

    for unit_key in subject_order:
        unit = by_subject[unit_key]

        lecture_day = None
        if unit["lecture"]:
            lecture_day = _assign_paired_group(unit["lecture"], None, assigned, failed, prefer_early_day=True)

        if unit["lab"]:
            _assign_paired_group(unit["lab"], lecture_day, assigned, failed)

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
    reset_ai_schedule()

    assigned, failed = _assign_pass()

    issues = find_issues()
    hard_issues = [i for i in issues if i.get("severity") == "hard"]
    soft_issues = [i for i in issues if i.get("severity") == "soft"]

    rounds_used = 1
    while hard_issues and rounds_used < MAX_FIX_ROUNDS:
        _fix_all_sessions(hard_issues)
        issues = find_issues()
        hard_issues = [i for i in issues if i.get("severity") == "hard"]
        soft_issues = [i for i in issues if i.get("severity") == "soft"]
        rounds_used += 1

    return {
        "assigned_count": len(assigned),
        "failed_count": len(failed),
        "assigned": assigned,
        "failed": failed,
        "rounds_used": rounds_used,
        "converged": len(hard_issues) == 0,
        "remaining_hard_issue_count": len(hard_issues),
        "remaining_soft_issue_count": len(soft_issues),
    }