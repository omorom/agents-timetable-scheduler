"""
candidate_scorer.py
เช็คว่า candidate (session + block ของ 2 timeslot) หนึ่งตัวผ่านกฎอะไรบ้าง

แก้ไขล่าสุด (สำคัญ): แยกกฎเป็น "hard จริง" กับ "soft" อย่างชัดเจน แทนที่จะรวม
ทุกข้อเป็น hard หมดเหมือนก่อนหน้านี้ — เพราะพอบังคับให้ต้องผ่านครบทุกข้อ (รวม
lecture_lab_diff_day + lab_after_lecture) พร้อมกัน โอกาสที่จะหา slot ผ่านครบ
แคบลงเรื่อยๆ ตามจำนวนวิชา/สาขาที่เพิ่มขึ้น ทำให้บาง session (เช่น LAB ที่ตาราง
อาจารย์/ห้องแน่นอยู่แล้ว) หา slot ไม่เจอเลยสักตัว แล้วหายไปแบบเงียบๆ (เข้า
"failed" list ที่ไม่มีใครเอาไปโชว์ ผู้ใช้ไม่รู้ตัวว่าจัดไม่ได้)

Hard จริง (ชนกันจริง / เกินขีดจำกัดตายตัว / ผิดกฎมหาวิทยาลัยจริงถ้าเกิด — ห้าม
ละเมิดเด็ดขาด filter ทิ้งเสมอ):
1. section_clash        — section A/B ของวิชาเดียวกันไม่ชนกัน
2. teacher_overload     — อาจารย์ไม่สอนเกิน 3 "block" รวด
3. full_day             — กลุ่มนิสิตไม่เรียนเกิน 3 วิชา/วัน
   ยกเว้น: วิชา ELECTIVE ไม่ต้องเช็คข้อนี้ (ดู _check_full_day) เพราะนิสิตเป็น
   คนเลือกลงวิชาเลือกเสรีเองอยู่แล้ว รู้ตัวอยู่แล้วว่าวันนั้นจะแน่นแค่ไหน ไม่ควร
   ถูกบล็อกด้วยกฎที่ออกแบบมาป้องกันนิสิต "ไม่รู้ตัว" ว่าตารางจะแน่นเกินไป
4. lecture_lab_diff_day — LAB ต้องอยู่ "คนละวัน" กับ LECTURE ของวิชาเดียวกันเสมอ
   (แก้กลับเป็น hard แล้ว — เคยลองทำเป็น soft แต่พบว่าระบบยอมจัด LAB/LECTURE
   วิชาเดียวกันไปตกวันเดียวกันได้ ซึ่งผิดกฎจริง ยอมรับไม่ได้ ต้องคงเป็น hard เด็ดขาด)

Soft (อยากได้ แต่ไม่ใช่กฎตายตัว — เป็นคะแนนบวกเพื่อจัดอันดับเท่านั้น ไม่ filter ทิ้ง):
5. lab_after_lecture    — LAB อยู่ "วันหลัง" LECTURE ของวิชาเดียวกัน (แค่เรื่องลำดับ
   ความสวยงามของตาราง ไม่ใช่กฎตายตัว — คงเป็น soft เหมือนเดิม เพราะบังคับเรื่อง
   ลำดับก่อนหลังพร้อมกับคนละวันทั้งคู่ ทำให้ slot แคบเกินไปจนบางวิชาหา LAB ไม่เจอเลย)

สำคัญ: candidate ตอนนี้คือ "block" (2 timeslot ติดกัน ไม่คร่อมข้าม block_id)
ฟังก์ชันเช็คทุกตัวรับ timeslot_ids เป็น list (2 ตัว) แล้วเช็คทุก timeslot ใน
block นั้น — ต้องผ่านทั้งคู่ถึงจะนับว่า block นี้ผ่าน

หมายเหตุ: teacher_unavailability/room_unavailability ถูกกรองออกไปแล้วตั้งแต่ชั้น
slot_filter.py ไฟล์นี้ไม่ต้องเช็คซ้ำ — เช็คแค่ conflict ระหว่าง assignment กันเอง
"""

from .load_data import get_cached_data

DAY_SEQUENCE = ["MON", "TUE", "WED", "THU", "FRI"]
DAY_RANK = {day: i for i, day in enumerate(DAY_SEQUENCE)}

# น้ำหนักคะแนนของแต่ละ soft rule (ยิ่งมากยิ่งอยากได้) — ปรับได้อิสระในอนาคต
# ถ้าเพิ่ม soft rule ใหม่ ก็มาเพิ่มน้ำหนักตรงนี้ได้เลย ไม่ต้องแตะ hard logic
SOFT_WEIGHT_AFTER_LECTURE = 1
MAX_SOFT_SCORE = SOFT_WEIGHT_AFTER_LECTURE  # = 1 — เหลือ soft แค่ข้อเดียว (diff_day ย้ายไปเป็น hard แล้ว)

# subject_type ที่ยกเว้นจาก hard rule full_day (เกิน 3 วิชา/วันของกลุ่มนิสิต)
# เพราะนิสิตเลือกลงเองอยู่แล้ว ไม่ใช่ถูกจัดให้แบบวิชาบังคับ
FULL_DAY_EXEMPT_SUBJECT_TYPES = {"ELECTIVE"}


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


def _check_full_day(
    group_ids: list[str],
    subject_id: str,
    timeslot_ids: list[str],
    assignments: list[dict],
    day_order: dict,
    subject_type: str | None = None,
) -> bool:
    """True ถ้าไม่ทำให้กลุ่มไหนใน group_ids เรียนเกิน 3 วิชา/วัน (เช็คทุก timeslot ใน block)

    ยกเว้น: ถ้า subject_type อยู่ใน FULL_DAY_EXEMPT_SUBJECT_TYPES (เช่น "ELECTIVE")
    ข้ามการเช็คนี้ไปเลย คืน True เสมอ — เพราะนิสิตเป็นคนเลือกลงวิชาเลือกเสรีเอง
    รู้ตัวอยู่แล้วว่าวันนั้นจะแน่นแค่ไหน ไม่ควรถูกบล็อกด้วยกฎที่ออกแบบมาป้องกันนิสิต
    "ถูกจัดให้" เกินไปโดยไม่รู้ตัว (ซึ่งเป็นเคสของวิชาบังคับ ไม่ใช่วิชาเลือก)

    หมายเหตุ: การยกเว้นนี้มีผลแค่ "ไม่บล็อกตัวเอง" เท่านั้น วิชา ELECTIVE ที่ถูกจัด
    ไปแล้วยังคงถูกนับรวมอยู่ใน subjects_today ตามปกติ (นับจาก assignments จริง) —
    เพราะงั้นวิชาบังคับอื่นที่มาทีหลังยังโดนกฎ "ไม่เกิน 3 วิชา/วัน" ตามปกติ ไม่ได้
    รับผลกระทบจากการยกเว้นนี้แต่อย่างใด
    """
    if not group_ids:
        return True
    if subject_type in FULL_DAY_EXEMPT_SUBJECT_TYPES:
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
    """True ถ้า LAB อยู่คนละวันกับ LECTURE ของวิชาเดียวกัน — ตอนนี้เป็น SOFT แล้ว
    (ใช้ตอนคำนวณคะแนนบวก ไม่ใช่ filter ทิ้ง) ใช้ timeslot แรกของ block เป็นตัวแทนวัน
    """
    if session["session_type"] != "LAB" or not lecture_day:
        return True
    info = day_order.get(str(timeslot_ids[0]))
    lab_day = info[0] if info else None
    return lab_day != lecture_day


def _check_lab_after_lecture(session: dict, timeslot_ids: list[str], lecture_day: str | None, day_order: dict) -> bool:
    """True ถ้า LAB อยู่ "วันหลัง" LECTURE ของวิชาเดียวกัน — ตอนนี้เป็น SOFT แล้ว
    (ใช้ตอนคำนวณคะแนนบวก ไม่ใช่ filter ทิ้ง) ใช้ DAY_RANK (MON=0 ... FRI=4) เทียบลำดับวัน
    """
    if session["session_type"] != "LAB" or not lecture_day:
        return True
    info = day_order.get(str(timeslot_ids[0]))
    lab_day = info[0] if info else None
    if lab_day is None:
        return True
    return DAY_RANK.get(lab_day, -1) > DAY_RANK.get(lecture_day, -1)


def passes_hard_rules(
    session: dict,
    timeslot_ids: list[str],
    assignments: list[dict],
    lecture_day: str | None = None,
) -> bool:
    """True ถ้าผ่าน hard rule จริงทั้ง 4 ข้อครบ (section_clash, teacher_overload,
    full_day, lecture_lab_diff_day) — นี่คือเกณฑ์ขั้นต่ำที่ candidate ต้องผ่านเสมอ
    ไม่มีข้อยกเว้น ไม่งั้นถือว่าใช้ไม่ได้เลย (ยกเว้น full_day ที่มีเงื่อนไขยกเว้นเฉพาะ
    วิชา ELECTIVE ในตัวเอง — ดู _check_full_day)
    """
    timeslots = get_cached_data()["timeslots"]
    day_order = _build_day_order(timeslots)
    block_order = _build_block_order(timeslots)

    return (
        _check_section_clash(session, timeslot_ids, assignments)
        and _check_teacher_overload(session["teacher_ids"], timeslot_ids, assignments, block_order)
        and _check_full_day(
            session["group_ids"],
            session["subject_id"],
            timeslot_ids,
            assignments,
            day_order,
            session.get("subject_type"),
        )
        and _check_lecture_lab_diff_day(session, timeslot_ids, lecture_day, day_order)
    )


def passes_core_hard_rules(session: dict, timeslot_ids: list[str], assignments: list[dict]) -> bool:
    """เช็คเฉพาะ hard rule 3 ข้อที่ 'ชนที่นั่งจริง' เป็นไปไม่ได้ที่จะปล่อยให้ละเมิด
    (section_clash, teacher_overload, full_day) — ไม่รวม lecture_lab_diff_day
    เพราะข้อนั้นเป็นแค่กฎ 'ความเรียบร้อยของตาราง' (LAB/LECTURE ไม่ควรตกวันเดียวกัน)
    ไม่ใช่การชนที่นั่ง/เวลาจริงแบบ 3 ข้อแรก

    ใช้เป็น fallback สุดท้ายเมื่อไม่มี candidate ไหนผ่านครบทั้ง 4 ข้อเลยจริงๆ (เช่น
    อาจารย์ว่างแค่วันเดียวซึ่งดันชนกับวันที่ LECTURE จัดไปแล้วพอดี) — ดู
    pick_best_candidate ใน candidate_picker.py ที่เรียกใช้ฟังก์ชันนี้เป็นรอบสุดท้าย
    หลังจากลองแบบเข้มงวดครบทุกตัวแล้วไม่เจอเลย
    """
    timeslots = get_cached_data()["timeslots"]
    day_order = _build_day_order(timeslots)
    block_order = _build_block_order(timeslots)

    return (
        _check_section_clash(session, timeslot_ids, assignments)
        and _check_teacher_overload(session["teacher_ids"], timeslot_ids, assignments, block_order)
        and _check_full_day(
            session["group_ids"],
            session["subject_id"],
            timeslot_ids,
            assignments,
            day_order,
            session.get("subject_type"),
        )
    )


def soft_score(
    session: dict,
    timeslot_ids: list[str],
    lecture_day: str | None = None,
) -> int:
    """คะแนน soft rule รวม (0-1) — ยิ่งสูงยิ่งดี แต่ไม่ใช่เกณฑ์ตัดสิทธิ์ ใช้แค่จัดอันดับ
    ระหว่าง candidate ที่ผ่าน hard rule ครบแล้วเท่านั้น (LAB อยู่วันหลัง LECTURE ดีกว่า
    แต่ถ้าทำไม่ได้ ก็ยังใช้ slot อื่นที่คนละวันแต่ไม่ใช่วันหลังได้ปกติ ไม่ถูกตัดทิ้ง)
    """
    timeslots = get_cached_data()["timeslots"]
    day_order = _build_day_order(timeslots)

    return SOFT_WEIGHT_AFTER_LECTURE if _check_lab_after_lecture(session, timeslot_ids, lecture_day, day_order) else 0


# ─────────────────────────────────────────────────────────────────────────
# คงชื่อฟังก์ชันเดิมไว้เพื่อ backward-compat กับจุดที่เคยเรียกใช้ (ถ้ามีไฟล์อื่น
# นอกเหนือจาก candidate_picker.py ที่ import score_candidate/score_hard_only อยู่)
# score_hard_only ตอนนี้คืน 0-4 (hard จริงรวม diff_day) ไม่ใช่ 0-5 หรือ 0-3 แบบก่อนหน้า
# ─────────────────────────────────────────────────────────────────────────

HARD_RULE_COUNT = 4  # section_clash, teacher_overload, full_day, lecture_lab_diff_day


def score_hard_only(
    session: dict,
    timeslot_ids: list[str],
    assignments: list[dict],
    lecture_day: str | None = None,
) -> int:
    """คะแนน hard rule จริงเท่านั้น: คืน HARD_RULE_COUNT (4) ถ้าผ่านครบ (รวม diff_day
    ด้วยแล้ว ต้องส่ง lecture_day เข้ามาด้วยถึงจะเช็คข้อนี้ได้ถูกต้อง) ไม่งั้นคืน 0
    """
    return HARD_RULE_COUNT if passes_hard_rules(session, timeslot_ids, assignments, lecture_day) else 0


def score_candidate(
    session: dict,
    timeslot_ids: list[str],
    assignments: list[dict],
    lecture_day: str | None = None,
) -> int:
    """คะแนนรวม: hard ต้องผ่านครบก่อน (ไม่งั้นคืน -1 ไปเลย ไม่มีทางถูกเลือก) แล้วบวก
    soft_score (0-1) เข้าไป ใช้จัดอันดับว่า candidate ไหน 'ดีที่สุด' ในบรรดาตัวที่ใช้ได้
    """
    if not passes_hard_rules(session, timeslot_ids, assignments, lecture_day):
        return -1
    return HARD_RULE_COUNT + soft_score(session, timeslot_ids, lecture_day)