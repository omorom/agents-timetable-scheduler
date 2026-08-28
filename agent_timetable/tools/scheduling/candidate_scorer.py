"""
candidate_scorer.py
เช็คว่า candidate (session + block ของ 2 timeslot) หนึ่งตัวผ่าน rule กี่ข้อจาก 4 ข้อ (ทั้งหมดเป็น hard แล้ว):
1. section_clash        — section A/B ของวิชาเดียวกันไม่ชนกัน (hard)
2. teacher_overload     — อาจารย์ไม่สอนเกิน 3 "block" รวด (hard) — เช็คทุกคนใน teacher_ids
   (1 block = 1 session = 2 timeslot ติดกัน — นับติดกันเป็น block ไม่ใช่ timeslot รายชั่วโมง
   เพราะ 1 session เดียวกินพื้นที่ 2 timeslot อยู่แล้วโดยปกติ ถ้านับแบบ timeslot รายชั่วโมง
   แค่สอน 2 session ติดกัน (ปกติ ไม่ผิด) จะกลายเป็น 4 timeslot ติดกัน โดนฟ้องผิดพลาด)
3. full_day             — กลุ่มนิสิตไม่เรียนเกิน 3 วิชา/วัน (hard) — เช็คทุกกลุ่มใน group_ids
4. lecture_lab_diff_day — LAB ต้องอยู่คนละวันกับ LECTURE ของวิชาเดียวกัน (hard)
   (เดิมเป็น soft และบังคับว่า LAB ต้องอยู่ "วันหลัง" LECTURE เท่านั้น — เปลี่ยนเป็น hard
   และแค่ต้อง "คนละวัน" ไม่บังคับลำดับก่อนหลังอีกต่อไป)

สำคัญ: candidate ตอนนี้คือ "block" (2 timeslot ติดกัน ไม่คร่อมข้าม block_id)
ฟังก์ชันเช็คทุกตัวรับ timeslot_ids เป็น list (2 ตัว) แล้วเช็คทุก timeslot ใน
block นั้น — ต้องผ่านทั้งคู่ถึงจะนับว่า block นี้ผ่าน

หมายเหตุ: teacher_unavailability/room_unavailability ถูกกรองออกไปแล้วตั้งแต่ชั้น
slot_filter.py ไฟล์นี้ไม่ต้องเช็คซ้ำ — เช็คแค่ conflict ระหว่าง assignment กันเอง
"""

from .load_data import get_cached_data

DAY_SEQUENCE = ["MON", "TUE", "WED", "THU", "FRI"]
DAY_RANK = {day: i for i, day in enumerate(DAY_SEQUENCE)}


def _build_day_order(timeslots: list[dict]) -> dict:
    """timeslot_id -> (day, ลำดับคาบในวันนั้น เริ่มที่ 0)"""
    result = {}
    for day in DAY_SEQUENCE:
        same_day = sorted(
            [t for t in timeslots if t["day"] == day],
            key=lambda t: t["start_time"],
        )
        for i, t in enumerate(same_day):
            result[str(t["timeslot_id"])] = (day, i)
    return result


def _build_block_order(timeslots: list[dict]) -> dict:
    """timeslot_id -> (day, ลำดับ 'block' ในวันนั้น เริ่มที่ 0)

    1 block = 2 timeslot ติดกัน (block_id เดียวกัน) = 1 session (LECTURE หรือ LAB)
    ต้องนับ 'ติดกันกี่ block' ไม่ใช่ 'ติดกันกี่ timeslot รายชั่วโมง' เพราะ 1 session
    เดียวกินพื้นที่ 2 timeslot อยู่แล้วโดยปกติ (ไม่ใช่ overload) ถ้านับแบบ timeslot
    รายชั่วโมง แค่สอน 2 session ติดกัน (ซึ่งปกติ ไม่ผิด) จะกลายเป็น 4 timeslot ติดกัน
    แล้วโดนฟ้องผิดพลาดว่า 'เกิน 3' ทันที ทั้งที่จริงคือแค่ 2 block เท่านั้น
    """
    result = {}
    for day in DAY_SEQUENCE:
        same_day = [t for t in timeslots if t["day"] == day]
        # เรียง block ตามเวลาเริ่มของ timeslot แรกในแต่ละ block
        block_start: dict = {}
        for t in same_day:
            bid = t["block_id"]
            if bid not in block_start or t["start_time"] < block_start[bid]:
                block_start[bid] = t["start_time"]
        ordered_block_ids = sorted(block_start.keys(), key=lambda bid: block_start[bid])
        block_rank = {bid: i for i, bid in enumerate(ordered_block_ids)}

        for t in same_day:
            result[str(t["timeslot_id"])] = (day, block_rank[t["block_id"]])
    return result


def day_of(timeslot_id: str, timeslots: list[dict] | None = None) -> str:
    if timeslots is None:
        timeslots = get_cached_data()["timeslots"]
    info = _build_day_order(timeslots).get(str(timeslot_id))
    return info[0] if info else ""


def _check_section_clash(session: dict, timeslot_ids: list[str], assignments: list[dict]) -> bool:
    """True ถ้า section อื่นของวิชาเดียวกันไม่อยู่คาบเดียวกัน (เช็คทุก timeslot ใน block)"""
    if not session.get("section"):
        return True
    base_id = session["session_id"].rsplit("-", 1)[0]
    for a in assignments:
        sid = a.get("session_id")
        if not sid:
            continue
        is_sibling = sid.rsplit("-", 1)[0] == base_id and sid != session["session_id"]
        if is_sibling and str(a["timeslot_id"]) in timeslot_ids:
            return False
    return True


def _check_teacher_overload(
    teacher_ids: list[str], timeslot_ids: list[str], assignments: list[dict], block_order: dict
) -> bool:
    """True ถ้าไม่ทำให้อาจารย์คนไหนใน teacher_ids สอนเกิน 3 "block" รวด (นับที่ระดับ block
    ไม่ใช่ timeslot รายชั่วโมง — ดู _build_block_order ว่าทำไม) เช็คทุก timeslot ใน block นี้
    """
    if not teacher_ids:
        return True

    for timeslot_id in timeslot_ids:
        day, idx = block_order.get(str(timeslot_id), (None, None))
        if day is None:
            continue

        for teacher_id in teacher_ids:
            blocks_today = sorted({
                block_order[str(a["timeslot_id"])][1]
                for a in assignments
                if a.get("teacher_id") == teacher_id
                and block_order.get(str(a["timeslot_id"]), (None, None))[0] == day
            } | {idx})

            streak = longest = 1
            for i in range(1, len(blocks_today)):
                streak = streak + 1 if blocks_today[i] == blocks_today[i - 1] + 1 else 1
                longest = max(longest, streak)
            if longest > 3:
                return False
    return True


def _check_full_day(group_ids: list[str], subject_id: str, timeslot_ids: list[str], assignments: list[dict], day_order: dict) -> bool:
    """True ถ้าไม่ทำให้กลุ่มไหนใน group_ids เรียนเกิน 3 วิชา/วัน (เช็คทุก timeslot ใน block)"""
    if not group_ids:
        return True

    for timeslot_id in timeslot_ids:
        day = day_order.get(str(timeslot_id), (None, None))[0]
        if day is None:
            continue

        for group_id in group_ids:
            subjects_today = {
                a["subject_id"]
                for a in assignments
                if a.get("group_id") == group_id
                and day_order.get(str(a["timeslot_id"]), (None, None))[0] == day
            }
            subjects_today.add(subject_id)
            if len(subjects_today) > 3:
                return False
    return True


def _check_lecture_lab_diff_day(session: dict, timeslot_ids: list[str], lecture_day: str | None, day_order: dict) -> bool:
    """True ถ้า LAB อยู่คนละวันกับ LECTURE ของวิชาเดียวกัน (hard — ไม่บังคับลำดับก่อนหลังอีกต่อไป
    แค่ต้องไม่ใช่วันเดียวกัน) ใช้ timeslot แรกของ block เป็นตัวแทนวัน
    """
    if session["session_type"] != "LAB" or not lecture_day:
        return True
    info = day_order.get(str(timeslot_ids[0]))
    lab_day = info[0] if info else None
    return lab_day != lecture_day


def _check_lab_after_lecture(session: dict, timeslot_ids: list[str], lecture_day: str | None, day_order: dict) -> bool:
    """True ถ้า LAB อยู่ "วันหลัง" LECTURE ของวิชาเดียวกัน (hard — ทดลองเปลี่ยนจาก soft
    เดิม เพื่อดูว่า failed เพิ่มขึ้นเยอะไหม ถ้าเยอะเกินไปค่อยเปลี่ยนกลับเป็น soft)
    ใช้ DAY_RANK (MON=0 ... FRI=4) เทียบลำดับวัน ไม่นับวันเดียวกันซ้ำ (เพราะกฎ
    _check_lecture_lab_diff_day บังคับคนละวันอยู่แล้วเป็นอีกข้อหนึ่งแยกกัน)
    """
    if session["session_type"] != "LAB" or not lecture_day:
        return True
    info = day_order.get(str(timeslot_ids[0]))
    lab_day = info[0] if info else None
    if lab_day is None:
        return True
    return DAY_RANK.get(lab_day, -1) > DAY_RANK.get(lecture_day, -1)


def score_candidate(
    session: dict,
    timeslot_ids: list[str],
    assignments: list[dict],
    lecture_day: str | None = None,
) -> int:
    """คะแนนรวม 0-5: ตอนนี้ทั้ง 5 ข้อเป็น hard หมดแล้ว (ไม่มี soft rule เหลืออยู่ — คงชื่อ
    ฟังก์ชันนี้ไว้เพื่อไม่ต้องแก้จุดเรียกใช้ใน candidate_picker.py)
    """
    return score_hard_only(session, timeslot_ids, assignments, lecture_day)


def score_hard_only(
    session: dict,
    timeslot_ids: list[str],
    assignments: list[dict],
    lecture_day: str | None = None,
) -> int:
    """คะแนน hard rules ทั้งหมด (0-5)"""
    timeslots = get_cached_data()["timeslots"]
    day_order = _build_day_order(timeslots)
    block_order = _build_block_order(timeslots)

    return sum([
        _check_section_clash(session, timeslot_ids, assignments),
        _check_teacher_overload(session["teacher_ids"], timeslot_ids, assignments, block_order),
        _check_full_day(session["group_ids"], session["subject_id"], timeslot_ids, assignments, day_order),
        _check_lecture_lab_diff_day(session, timeslot_ids, lecture_day, day_order),
        _check_lab_after_lecture(session, timeslot_ids, lecture_day, day_order),
    ])