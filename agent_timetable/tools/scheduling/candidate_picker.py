"""
candidate_picker.py
เลือก candidate (block ของ 2 timeslot + ห้อง) ที่ดีที่สุดสำหรับ session หนึ่ง

แก้ไขล่าสุด (สำคัญ): เปลี่ยนจาก "ต้องได้คะแนนเต็ม 100% เท่านั้น" มาเป็น "เลือก
candidate ที่คะแนนสูงสุดในบรรดาตัวที่ผ่าน hard rule จริงครบ" แทน — เดิมระบบ
รวม soft rule (lecture_lab_diff_day, lab_after_lecture) เข้าไปเป็น hard ด้วย
ทำให้ต้องผ่านครบทุกข้อพร้อมกัน พอวิชา/สาขาเพิ่มขึ้น ตารางแน่นขึ้น โอกาสที่จะ
มี slot ผ่านครบทุกข้อยิ่งน้อยลงเรื่อยๆ ทำให้บาง session (เช่น LAB) หา slot ไม่
เจอเลย แล้วหายไปแบบเงียบๆ เข้า "failed" list ที่ไม่มีใครเห็น

ตอนนี้: hard rule จริง (section_clash, teacher_overload, full_day) ยังคง
บังคับผ่านครบ 100% เหมือนเดิมทุกอย่าง (ไม่มีการผ่อนเลย) — แต่ soft rule
(lecture_lab_diff_day, lab_after_lecture) กลายเป็น "คะแนนบวก" ที่ใช้จัดอันดับ
เท่านั้น ถ้ามี candidate ที่ได้ soft เต็มก็จะถูกเลือกเป็นอันดับแรกอยู่ดี แต่ถ้า
ไม่มีตัวไหนได้ soft เต็มเลย ระบบจะเลือกตัวที่ soft สูงสุดเท่าที่มี แทนที่จะ fail
(คืน None ให้ session ไปอยู่ใน "failed" ก็ต่อเมื่อไม่มี candidate ไหนผ่าน hard
รู้จริงเลยสักตัว ซึ่งเป็นเคสที่ slot ไม่พอจริงๆ แก้ด้วยการผ่อนไม่ได้อยู่ดี)

เพิ่มเติมล่าสุด (สำคัญ): เพิ่ม fallback รอบสุดท้ายใน pick_best_candidate — ถ้าลอง
แบบเข้มงวดครบทั้ง 4 ข้อแล้วไม่เจอ candidate ไหนผ่านเลยจริงๆ (เช่น อาจารย์ว่างแค่
วันเดียว ซึ่งดันชนกับวันที่ LECTURE จัดไปแล้วพอดี — เจอเคสจริงกับวิชา 254451)
จะลองรอบสุดท้ายโดยผ่อน lecture_lab_diff_day (กฎ "ความเรียบร้อยของตาราง" ไม่ใช่
การชนที่นั่งจริง) — ยังคงบังคับ section_clash/teacher_overload/full_day 100%
เหมือนเดิมทุกอย่าง ไม่มีทางเกิดการชนที่นั่งจริงจากการผ่อนนี้เลย candidate ที่ได้
จากรอบนี้จะติด key "_relaxed_diff_day" = True ให้ auto_assign.py เอาไปแสดงเป็น
"warning" แยกต่างหากจาก assigned ปกติ ให้เจ้าหน้าที่รู้ว่าควรเช็คด้วยตาอีกที

สำหรับ LAB/LECTURE ที่มี 2 section (1/2) มี 2 กรณี:
  - อาจารย์คนเดียวกันสอนทั้งคู่ (same_teacher=True): ห้องเดียวกันคือข้อบังคับ (hard),
    เวลาให้ติดกันในวันเดียวกันถ้าเป็นไปได้ (ทำไม่ได้ ยอมคนละวัน ห้องเดิม)
    — เพราะอาจารย์คนเดียวสอน 2 ห้องพร้อมกันไม่ได้
  - อาจารย์คนละคนสอนแต่ละ section (same_teacher=False): ให้จัด "เวลาเดียวกัน คนละห้อง"
    เพราะสอนพร้อมกันได้ (คนละอาจารย์ คนละห้อง)

สำคัญ: candidate ตอนนี้คือ "block" มี candidate["timeslot_ids"] เป็น list 2 ตัว
เสมอ ใช้ candidate["timeslot_ids"][0] เป็นตัวแทนตอนต้องเทียบ "วัน/ลำดับ" (เพราะ
ทั้ง 2 timeslot ใน block อยู่วันเดียวกันเสมออยู่แล้ว) ส่วนตอนเช็ค hard rule
ส่ง timeslot_ids ทั้ง list เข้า passes_hard_rules เพื่อเช็คครบทั้ง block

เข้มงวด 100% กับ hard จริง 3 ข้อ (section_clash, teacher_overload, full_day):
ถ้าไม่มี candidate ไหนผ่านครบเลยจริงๆ (แม้จะผ่อน diff_day แล้วก็ตาม) จะคืน None
(ทำให้ session นั้นไปอยู่ใน "failed" แทนที่จะย้ายไปแอบละเมิดกฎที่ชนที่นั่งจริง)
"""

import random

from .load_data import get_cached_data
from .candidate_scorer import (
    score_candidate,
    score_hard_only,
    passes_hard_rules,
    passes_core_hard_rules,
    soft_score,
    _build_day_order,
    HARD_RULE_COUNT,
    MAX_SOFT_SCORE,
)

MAX_RANDOM_TRIES = 10
HARD_FULL_SCORE = HARD_RULE_COUNT  # = 4 — hard rules จริงผ่านครบ ถือว่า "ใช้ได้"
BEST_POSSIBLE_SCORE = HARD_RULE_COUNT + MAX_SOFT_SCORE  # = ผ่าน hard ครบ + soft เต็ม


def _passes_hard_rules(session: dict, timeslot_ids: list[str], assignments: list[dict], lecture_day: str | None = None) -> bool:
    # diff_day กลับมาเป็น hard แล้ว (ดู candidate_scorer.py) ต้องส่ง lecture_day เข้าไป
    # ด้วยเสมอ ไม่งั้นจะไม่เช็คกฎ "ห้าม LAB วันเดียวกับ LECTURE" เลย
    return passes_hard_rules(session, timeslot_ids, assignments, lecture_day)


def _fake_assignment_for(session: dict, candidate: dict) -> dict:
    """สร้าง assignment จำลอง 1 แถว (ใช้ timeslot แรกของ block พอสำหรับเช็ค hard rule
    ชั่วคราวตอนหาคู่ section — ตัวจริงตอน insert จะสร้างครบทุก timeslot ใน assignment_store.py)
    """
    return {
        "session_id": session["session_id"],
        "subject_id": session["subject_id"],
        "teacher_id": session["teacher_ids"][0] if session["teacher_ids"] else None,
        "room_id": candidate["room_id"],
        "timeslot_id": candidate["timeslot_ids"][0],
        "group_id": session["group_ids"][0] if session["group_ids"] else None,
    }


def _rooms_in_order(candidates: list[dict]) -> list:
    return list(dict.fromkeys(c["room_id"] for c in candidates))


def _group_by_room(candidates: list[dict]) -> dict:
    result: dict = {}
    for c in candidates:
        result.setdefault(c["room_id"], []).append(c)
    return result


def _group_by_room_day(candidates: list[dict], day_order: dict) -> dict:
    result: dict = {}
    for c in candidates:
        day = day_order.get(str(c["timeslot_ids"][0]), (None, None))[0]
        result.setdefault((c["room_id"], day), []).append(c)
    return result


def _group_by_timeslot(candidates: list[dict]) -> dict:
    result: dict = {}
    for c in candidates:
        result.setdefault(c["timeslot_ids"][0], []).append(c)
    return result


def _find_pair_same_day(room, by_room_day_a, by_room_b, session_a, session_b, assignments, day_order, lecture_day=None):
    """หาคู่ (A, B) ในห้องเดียวกัน วันเดียวกัน — ไล่หา "คาบติดกัน" ในทุกวันก่อนเป็นรอบแรก
    (ไม่ใช่แค่วันแรกที่เจอตัวเลือก) ถ้าไม่เจอคาบติดกันเลยสักวัน ค่อยรอบสองไล่หาคาบไม่
    ติดกันแทน — เดิมพอเจอ "คู่ที่ใช้ได้ตัวแรก" (ไม่ว่าติดกันไหม) จะหยุดค้นหาทันทีที่วันนั้น
    ทำให้พลาดวันอื่นที่มีคาบติดกันจริงๆ ไปอย่างน่าเสียดาย (เช่น เจอวันอังคารมีตัวเลือกไม่
    ติดกันก่อน ทั้งที่จริงวันพุธมีติดกันพอดี)
    """
    DAY_NAMES = ["MON", "TUE", "WED", "THU", "FRI"]
    days = sorted(
        {d for (r, d) in by_room_day_a if r == room and d is not None},
        key=lambda d: DAY_NAMES.index(d),
    )
    b_by_day: dict = {}
    for c in by_room_b.get(room, []):
        d = day_order.get(str(c["timeslot_ids"][0]), (None, None))[0]
        if d:
            b_by_day.setdefault(d, []).append(c)

    # เก็บ candidate ที่ไม่ติดกันไว้ก่อน เผื่อรอบแรก (หาติดกัน) ไม่เจอเลยสักวัน
    fallback_non_adjacent: tuple[dict, dict] | None = None

    for day in days:
        a_options = by_room_day_a.get((room, day), [])
        b_options = b_by_day.get(day, [])
        if not a_options or not b_options:
            continue

        pairs = []
        for a_c in a_options:
            a_idx = day_order.get(str(a_c["timeslot_ids"][0]), (None, -999))[1]
            for b_c in b_options:
                if a_c["timeslot_ids"][0] == b_c["timeslot_ids"][0]:
                    continue
                b_idx = day_order.get(str(b_c["timeslot_ids"][0]), (None, -999))[1]
                pairs.append((abs(a_idx - b_idx) != 1, a_c, b_c))  # False (ติดกัน) มาก่อน

        for is_non_adjacent, a_c, b_c in sorted(pairs, key=lambda p: p[0]):
            if not _passes_hard_rules(session_a, a_c["timeslot_ids"], assignments, lecture_day):
                continue
            local = assignments + [_fake_assignment_for(session_a, a_c)]
            if not _passes_hard_rules(session_b, b_c["timeslot_ids"], local, lecture_day):
                continue

            if not is_non_adjacent:
                # เจอคู่ "ติดกัน" แล้ว — ใช้ทันที ไม่ต้องหาต่อ (นี่คือคำตอบที่ดีที่สุด)
                return (a_c, b_c)

            # เจอคู่ไม่ติดกันตัวแรกในวันนี้ — เก็บไว้เป็น fallback แต่ "ยังไม่ return"
            # เพราะอาจจะมีวันอื่นที่มีคู่ติดกันรออยู่ ต้องไล่ให้ครบทุกวันก่อน
            if fallback_non_adjacent is None:
                fallback_non_adjacent = (a_c, b_c)

    # ไล่ครบทุกวันแล้ว ไม่เจอคู่ที่ติดกันเลยสักวัน — ค่อยใช้ fallback (ถ้ามี)
    return fallback_non_adjacent


def _find_pair_diff_day(room, candidates_a, by_room_b, session_a, session_b, assignments, lecture_day=None):
    """หาคู่ (A, B) ในห้องเดียวกัน คนละวันก็ได้"""
    a_options = [c for c in candidates_a if c["room_id"] == room]
    b_options = by_room_b.get(room, [])
    for a_c in a_options:
        if not _passes_hard_rules(session_a, a_c["timeslot_ids"], assignments, lecture_day):
            continue
        local = assignments + [_fake_assignment_for(session_a, a_c)]
        for b_c in b_options:
            if a_c["timeslot_ids"][0] != b_c["timeslot_ids"][0] and _passes_hard_rules(session_b, b_c["timeslot_ids"], local, lecture_day):
                return (a_c, b_c)
    return None


def _find_pair_same_time_diff_room(candidates_a, candidates_b, session_a, session_b, assignments, lecture_day=None):
    """หาคู่ (A, B) ที่ 'เวลาเดียวกัน คนละห้อง' — ใช้ตอนอาจารย์ของ 2 section เป็นคนละคน
    เพราะสอนพร้อมกันคนละห้องได้ (ต่างจากกรณีอาจารย์คนเดียวกันที่ต้องบังคับห้องเดียวกัน)
    """
    by_timeslot_b = _group_by_timeslot(candidates_b)

    for a_c in candidates_a:
        ts = a_c["timeslot_ids"][0]
        b_options = by_timeslot_b.get(ts, [])
        if not b_options:
            continue
        if not _passes_hard_rules(session_a, a_c["timeslot_ids"], assignments, lecture_day):
            continue
        local = assignments + [_fake_assignment_for(session_a, a_c)]
        for b_c in b_options:
            if b_c["room_id"] == a_c["room_id"]:
                continue  # ต้องคนละห้องเสมอ (สอนพร้อมกันห้องเดียวกันไม่ได้)
            if _passes_hard_rules(session_b, b_c["timeslot_ids"], local, lecture_day):
                return (a_c, b_c)
    return None


def pick_best_candidate(
    session: dict,
    candidates: list[dict],
    lecture_day: str | None,
    assignments: list[dict],
    prefer_early_day: bool = False,
) -> dict | None:
    """
    เลือก candidate (block) ที่ "คะแนนรวมสูงสุด" ในบรรดาตัวที่ผ่าน hard rule จริงครบ
    (section_clash, teacher_overload, full_day, lecture_lab_diff_day) คะแนนรวม =
    hard (คงที่ถ้าผ่าน) + soft (lab_after_lecture — ยิ่งผ่านมากยิ่งได้คะแนนสูง)

    ก่อนหน้านี้ต้องได้คะแนนเต็มเป๊ะ (ผ่านทั้ง hard และ soft ครบ) ถึงจะถูกเลือก ทำให้
    session ที่หา slot ผ่านครบทุกข้อไม่ได้ (เช่น ตารางแน่นมากตอนสาขาเพิ่มขึ้น) หา
    ไม่เจอเลยแล้ว fail ทั้งที่จริงมี slot ที่ผ่าน hard ครบอยู่ (แค่ soft ไม่ครบ)

    ตอนนี้: ลองสุ่มหา candidate ที่คะแนนเต็ม (BEST_POSSIBLE_SCORE) ก่อนสูงสุด
    MAX_RANDOM_TRIES ครั้ง (เร็ว เจอบ่อยเวลาตารางไม่แน่นมาก) ถ้าไม่เจอ ไล่เช็ค
    candidate ที่เหลือ "ทั้งหมด" หาตัวที่คะแนนสูงสุดเท่าที่มี (ต้องผ่าน hard ครบ
    เสมอ ไม่ว่า soft จะได้เท่าไหร่ก็ตาม)

    เพิ่มเติม: ถ้าลองแบบเข้มงวดครบทั้ง 4 ข้อแล้วไม่เจอ candidate ไหนผ่านเลยจริงๆ
    จะลองรอบสุดท้ายโดยผ่อน lecture_lab_diff_day (กฎ "ความเรียบร้อยของตาราง" ไม่ใช่
    การชนที่นั่งจริง) ผ่าน passes_core_hard_rules — ยังคงบังคับ section_clash/
    teacher_overload/full_day 100% เหมือนเดิมทุกอย่าง candidate ที่ได้จากรอบนี้จะ
    ติด key "_relaxed_diff_day"=True ให้ผู้เรียก (auto_assign.py) เอาไปแสดงเป็น
    "warning" แยกจาก assigned ปกติ

    เข้มงวด 100% กับ hard จริง 3 ข้อ: ถ้าไม่มี candidate ไหนผ่านครบเลยจริงๆ (แม้จะ
    ผ่อน diff_day แล้วก็ตาม) จะคืน None (ให้ session นี้ไปอยู่ใน "failed")
    """
    day_order = _build_day_order(get_cached_data()["timeslots"])

    pool = candidates
    if prefer_early_day:
        early_days = {"MON", "TUE"}
        weighted = []
        for c in candidates:
            day = day_order.get(str(c["timeslot_ids"][0]), (None, None))[0]
            weighted.append(c)
            if day in early_days:
                weighted.extend([c] * 7)
        pool = weighted

    tried_keys = set()

    # รอบสุ่ม: หาตัวคะแนนเต็ม (ผ่าน hard + soft ครบ) ให้เจอไวๆ ก่อน ถ้าตารางไม่แน่นมาก
    for _ in range(min(MAX_RANDOM_TRIES, len(pool))):
        remaining = [c for c in pool if (c["room_id"], c["timeslot_ids"][0]) not in tried_keys]
        if not remaining:
            break
        candidate = random.choice(remaining)
        tried_keys.add((candidate["room_id"], candidate["timeslot_ids"][0]))

        total_score = score_candidate(session, candidate["timeslot_ids"], assignments, lecture_day)
        if total_score == BEST_POSSIBLE_SCORE:
            return candidate

    # สุ่มไม่เจอตัวคะแนนเต็ม — ไล่เช็ค candidate ที่เหลือ "ทั้งหมด" หาตัวคะแนนสูงสุด
    # เท่าที่มี (ต้องผ่าน hard ครบเสมอ — score_candidate คืน -1 ถ้า hard ไม่ผ่าน)
    best_candidate: dict | None = None
    best_score = -1
    for candidate in candidates:
        total_score = score_candidate(session, candidate["timeslot_ids"], assignments, lecture_day)
        if total_score > best_score:
            best_score = total_score
            best_candidate = candidate
            if best_score == BEST_POSSIBLE_SCORE:
                break  # เจอตัวดีที่สุดเท่าที่เป็นไปได้แล้ว ไม่ต้องหาต่อ

    if best_candidate is not None and best_score >= HARD_FULL_SCORE:
        return best_candidate

    # ── Fallback สุดท้าย: ไม่มี candidate ไหนผ่านครบ 4 ข้อเลยจริงๆ ──
    # ลองผ่อน lecture_lab_diff_day เป็นทางเลือกสุดท้าย ยังคงบังคับ 3 ข้อที่ชนที่นั่ง
    # จริง (section_clash, teacher_overload, full_day) 100% เหมือนเดิม ไม่มีทาง
    # เกิดการชนที่นั่งจริงจากการผ่อนนี้เลย — แค่ยอมให้ LAB ตกวันเดียวกับ LECTURE
    for candidate in candidates:
        if passes_core_hard_rules(session, candidate["timeslot_ids"], assignments):
            relaxed = dict(candidate)
            relaxed["_relaxed_diff_day"] = True
            return relaxed

    # ไม่ผ่านแม้แต่ core 3 ข้อเลยจริงๆ — ยอมแพ้ ให้ไปอยู่ใน "failed"
    return None


def assign_lab_pair_deterministic(
    session_a: dict,
    session_b: dict,
    candidates_a: list[dict],
    candidates_b: list[dict],
    assignments: list[dict],
    same_teacher: bool = True,
    lecture_day: str | None = None,
) -> tuple[dict, dict] | None:
    """จัดคู่ section 1/2 ของวิชาเดียวกัน (LECTURE หรือ LAB ก็ใช้ฟังก์ชันนี้ได้เหมือนกัน)

    same_teacher=True  (อาจารย์คนเดียวกันสอนทั้งคู่): ห้องเดียวกันคือข้อบังคับ
        ลองหาในวันเดียวกันก่อน (adjacent block ก่อน non-adjacent) แล้วค่อย fallback
        เป็นห้องเดียวกันคนละวัน — เพราะอาจารย์คนเดียวสอน 2 ห้องพร้อมกันไม่ได้อยู่แล้ว
    same_teacher=False (อาจารย์คนละคน): จัดเวลาเดียวกัน คนละห้อง เพราะสอนพร้อมกันได้

    lecture_day: ถ้าระบุ (ตอนจัด LAB ที่มี LECTURE ของวิชาเดียวกันจัดไปแล้ว) จะใช้เป็น
    soft preference ว่า LAB block ที่จัดคู่นี้ "อยากให้" ไม่ตกวันเดียวกับ lecture_day
    (ไม่ใช่ hard บังคับอีกต่อไป — ดู candidate_scorer.py) ฟังก์ชันหาคู่พวกนี้ยังใช้
    hard rule เป็นตัวกรองหลักเหมือนเดิม แค่ตอนนี้ hard ไม่รวม lecture/lab day แล้ว

    หมายเหตุ: ฟังก์ชันนี้ (สำหรับ pairing แบบ section คู่/team-teaching) ยังไม่มี
    fallback ผ่อน diff_day เหมือน pick_best_candidate — ถ้าจำเป็นต้องเพิ่มในอนาคต
    ค่อยทำเพิ่ม ตอนนี้ยังคงพฤติกรรมเดิม (คืน None ถ้าหาคู่ไม่เจอ ไปอยู่ใน "failed")
    """
    if not same_teacher:
        return _find_pair_same_time_diff_room(candidates_a, candidates_b, session_a, session_b, assignments, lecture_day)

    day_order = _build_day_order(get_cached_data()["timeslots"])

    rooms = _rooms_in_order(candidates_a)
    by_room_b = _group_by_room(candidates_b)
    by_room_day_a = _group_by_room_day(candidates_a, day_order)

    for room in rooms:
        if room not in by_room_b:
            continue
        pair = _find_pair_same_day(room, by_room_day_a, by_room_b, session_a, session_b, assignments, day_order, lecture_day)
        if pair:
            return pair

    for room in rooms:
        if room not in by_room_b:
            continue
        pair = _find_pair_diff_day(room, candidates_a, by_room_b, session_a, session_b, assignments, lecture_day)
        if pair:
            return pair

    return None


def pick_paired_section_candidate(
    session: dict,
    candidates: list[dict],
    paired_room_id,
    paired_timeslot_id: str,
    assignments: list[dict],
    same_teacher: bool = True,
    lecture_day: str | None = None,
) -> dict | None:
    day_order = _build_day_order(get_cached_data()["timeslots"])

    paired_day, paired_idx = day_order.get(str(paired_timeslot_id), (None, None))
    if paired_day is None:
        return None

    if not same_teacher:
        # อาจารย์คนละคน — ต้องการ "เวลาเดียวกัน คนละห้อง"
        same_time = [
            c for c in candidates
            if c["timeslot_ids"][0] == paired_timeslot_id and c["room_id"] != paired_room_id
            and _passes_hard_rules(session, c["timeslot_ids"], assignments, lecture_day)
        ]
        return same_time[0] if same_time else None

    same_room = [c for c in candidates if c["room_id"] == paired_room_id]
    if not same_room:
        return None

    same_room_same_day = [
        c for c in same_room
        if day_order.get(str(c["timeslot_ids"][0]), (None, None))[0] == paired_day
    ]

    adjacent_ok = [
        c for c in same_room_same_day
        if abs(day_order.get(str(c["timeslot_ids"][0]), (None, -999))[1] - paired_idx) == 1
        and _passes_hard_rules(session, c["timeslot_ids"], assignments, lecture_day)
    ]
    if adjacent_ok:
        return adjacent_ok[0]

    same_day_ok = [c for c in same_room_same_day if _passes_hard_rules(session, c["timeslot_ids"], assignments, lecture_day)]
    if same_day_ok:
        return same_day_ok[0]

    other_day_ok = [c for c in same_room if _passes_hard_rules(session, c["timeslot_ids"], assignments)]
    return other_day_ok[0] if other_day_ok else None