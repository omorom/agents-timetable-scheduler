"""
candidate_picker.py
เลือก candidate (block ของ 2 timeslot + ห้อง) ที่ดีที่สุดสำหรับ session หนึ่ง
ใช้ retry-until-valid: สุ่มหาตัวคะแนนเต็มก่อน ถ้าไม่เจอค่อยไล่เช็คที่เหลือทั้งหมด

สำหรับ LAB/LECTURE ที่มี 2 section (1/2) มี 2 กรณี:
  - อาจารย์คนเดียวกันสอนทั้งคู่ (same_teacher=True): ห้องเดียวกันคือข้อบังคับ (hard),
    เวลาให้ติดกันในวันเดียวกันถ้าเป็นไปได้ (ทำไม่ได้ ยอมคนละวัน ห้องเดิม)
    — เพราะอาจารย์คนเดียวสอน 2 ห้องพร้อมกันไม่ได้
  - อาจารย์คนละคนสอนแต่ละ section (same_teacher=False): ให้จัด "เวลาเดียวกัน คนละห้อง"
    เพราะสอนพร้อมกันได้ (คนละอาจารย์ คนละห้อง)

สำคัญ: candidate ตอนนี้คือ "block" มี candidate["timeslot_ids"] เป็น list 2 ตัว
เสมอ ใช้ candidate["timeslot_ids"][0] เป็นตัวแทนตอนต้องเทียบ "วัน/ลำดับ" (เพราะ
ทั้ง 2 timeslot ใน block อยู่วันเดียวกันเสมออยู่แล้ว) ส่วนตอนเช็ค hard rule
ส่ง timeslot_ids ทั้ง list เข้า score_candidate/score_hard_only เพื่อเช็คครบทั้ง block

แก้ไขล่าสุด (สำคัญ): เดิม pick_best_candidate มี "fallback" ยอมคืน candidate ที่
hard rule ไม่ผ่านครบ (คะแนนต่ำกว่า HARD_FULL_SCORE) ถ้าหาตัวที่ผ่านครบไม่เจอเลย —
ทำให้ hard rule (เช่น teacher_overload, full_day) ถูกละเมิดได้เงียบๆ โดยไม่มีใครรู้
จนกว่าจะไปเจอตอน find_issues() ทีหลัง ตอนนี้เปลี่ยนเป็น "เข้มงวด 100%": ถ้าไม่มี
candidate ไหนผ่าน hard rule ครบเลยจริงๆ จะคืน None (ทำให้ session นั้นไปอยู่ใน
"failed" แทนที่จะย้ายไปแอบละเมิดกฎ) — ผู้ใช้เลือกไว้ว่ายอมให้วิชาจัดไม่ได้ ดีกว่า
ปล่อยให้ผิดเงื่อนไข hard
"""

import random

from .load_data import get_cached_data
from .candidate_scorer import score_candidate, score_hard_only, _build_day_order

MAX_RANDOM_TRIES = 10
FULL_SCORE = 5       # hard rules ทั้งหมด (รวม lecture/lab ต้องคนละวัน + LAB ต้องอยู่หลัง
                      # LECTURE — ทดลองเปลี่ยนจาก soft เป็น hard ดูผล) ผ่านครบ — ดีที่สุด
HARD_FULL_SCORE = 5  # hard rules ผ่านครบ — ถือว่า "ใช้ได้" แล้ว (เท่ากับ FULL_SCORE เพราะ
                      # ตอนนี้ไม่มี soft rule เหลืออยู่แล้ว)


def _passes_hard_rules(session: dict, timeslot_ids: list[str], assignments: list[dict], lecture_day: str | None = None) -> bool:
    return score_hard_only(session, timeslot_ids, assignments, lecture_day) == HARD_FULL_SCORE


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
    ลองสุ่มสูงสุด MAX_RANDOM_TRIES ครั้ง หา candidate (block) ที่คะแนนเต็ม
    ถ้าเจอ candidate ที่ hard rules ผ่านครบอยู่แล้ว ก็ใช้ได้เลย ไม่ต้องสุ่มต่อ
    ถ้าสุ่มจนครบโควต้าแล้วยังไม่เจอตัวที่ hard ผ่านครบ ไล่เช็คที่เหลือ "ทั้งหมด"
    (ไม่ใช่แค่ pool ที่สุ่มมา) เพื่อหาตัวที่ hard ผ่านครบให้ได้จริงๆ ก่อนยอมแพ้

    เข้มงวด 100%: ถ้าไล่เช็คทุก candidate แล้วไม่มีตัวไหนผ่าน hard rule ครบเลย
    คืน None (ให้ session นี้ไปอยู่ใน "failed") — ไม่มี fallback ยอมรับ candidate
    ที่ผิด hard rule อีกต่อไป (เดิมเคยมี fallback แบบนั้น ทำให้กฎถูกละเมิดเงียบๆ)
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

    for _ in range(min(MAX_RANDOM_TRIES, len(pool))):
        remaining = [c for c in pool if (c["room_id"], c["timeslot_ids"][0]) not in tried_keys]
        if not remaining:
            break
        candidate = random.choice(remaining)
        tried_keys.add((candidate["room_id"], candidate["timeslot_ids"][0]))

        full_score = score_candidate(session, candidate["timeslot_ids"], assignments, lecture_day)
        if full_score == FULL_SCORE:
            return candidate

    # สุ่มไม่เจอ — ไล่เช็ค candidate ที่เหลือทั้งหมด (ที่ยังไม่เคยลอง) หาให้ครบว่ามีตัวไหน
    # ผ่าน hard rule เต็มคะแนนไหม ก่อนจะยอมแพ้จริงๆ
    for candidate in candidates:
        key = (candidate["room_id"], candidate["timeslot_ids"][0])
        if key in tried_keys:
            continue
        if score_hard_only(session, candidate["timeslot_ids"], assignments, lecture_day) == HARD_FULL_SCORE:
            return candidate

    # ไม่มี candidate ไหนผ่าน hard rule ครบเลยจริงๆ — เข้มงวด 100% ไม่ fallback
    # คืน None ให้ผู้เรียก (auto_assign.py) ใส่ session นี้ลงใน "failed" แทน
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

    lecture_day: ถ้าระบุ (ตอนจัด LAB ที่มี LECTURE ของวิชาเดียวกันจัดไปแล้ว) จะบังคับ
    (hard) ว่า LAB block ที่จัดคู่นี้ห้ามตกวันเดียวกับ lecture_day เลย — เดิมฟังก์ชันนี้
    ไม่รับ lecture_day เลย ทำให้ตอนจัดคู่ (parallel/team-teaching) กฎ 'LAB ต้องคนละวัน
    กับ LECTURE' ไม่ถูกเช็คเลยแม้แต่น้อย (bug เดิม ซ่อนอยู่นาน เพิ่งเจอตอนเปิดให้ LECTURE
    แยกคู่ขนานได้ด้วย ไม่ใช่รวมเป็นก้อนเดียวเสมอเหมือนก่อน)
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