"""
find_issues.py
เช็คตารางที่จัดไว้แล้ว หาปัญหา 4 อย่าง (3 hard + 1 soft) — Python ล้วน ไม่ใช้ token
ทุก issue ต้องมี key "fix_session_id" ที่ระบุชัดว่าถ้าจะแก้ ควรย้าย session ไหน
(เพิ่มจาก demo เดิม — demo เดิมให้ LLM เดาเอาเองว่าจะย้าย session ไหนจาก hard_issues
ซึ่งเสี่ยงมาก โดยเฉพาะ teacher_overload/full_day ที่ไม่มี session_id ตรงๆ ให้เดาง่ายๆ)
"""

from .load_data import get_cached_data
from .assignment_store import get_current_schedule_raw
from .candidate_scorer import _build_day_order, _build_block_order


def _slot_index_in_day(timeslot_id: str, timeslots: list[dict], day_order: dict) -> int:
    info = day_order.get(str(timeslot_id))
    return info[1] + 1 if info else 0


def find_issues() -> list[dict]:
    """คืน list ของปัญหาที่เจอ — ถ้า list ว่าง = ตารางโอเค ไม่ต้องเรียก agent"""
    data = get_cached_data()
    timeslots = data["timeslots"]
    day_order = _build_day_order(timeslots)
    block_order = _build_block_order(timeslots)  # ใช้เฉพาะเช็ค teacher_overload (นับเป็น block ไม่ใช่ timeslot รายชั่วโมง)

    schedule = get_current_schedule_raw()  # แถวดิบ (1 แถว = 1 teacher-group pair)
    issues = []

    by_subject = {}
    for a in schedule:
        by_subject.setdefault(a["subject_id"], []).append(a)

    # 1. Section 1/2 ของ subject_selected เดียวกันชนกัน (คาบเดียวกัน + ห้องเดียวกัน)
    # หมายเหตุ: คาบเดียวกันแต่ "คนละห้อง" ไม่ถือว่าชน — เป็นกรณีตั้งใจของ auto_assign.py
    # เอง (section คู่ 1/2 ที่มีอาจารย์คนละคน จะถูกจัดให้เวลาเดียวกัน คนละห้อง โดยตั้งใจ
    # ดู _assign_paired_group / assign_lab_pair_deterministic ใน auto_assign.py)
    # ต้องเช็คห้องด้วย ไม่ใช่แค่คาบเวลาอย่างเดียว ไม่งั้นจะฟ้อง conflict ผิดๆ ทุกครั้งที่
    # scheduler จัดถูกต้องตามที่ตั้งใจไว้แล้ว
    for subject_id, items in by_subject.items():
        sections = [a for a in items if a.get("session_id", "").endswith(("-1", "-2"))]
        timeslot_to_entries: dict = {}
        for a in sections:
            timeslot_to_entries.setdefault(a["timeslot_id"], []).append(a)
        for ts_id, entries in timeslot_to_entries.items():
            # group ต่อด้วย room_id — ชนกันจริงก็ต่อเมื่อคาบเดียวกัน "และ" ห้องเดียวกัน
            room_to_session_ids: dict = {}
            for a in entries:
                room_to_session_ids.setdefault(a.get("room_id"), set()).add(a["session_id"])
            for room_id, session_ids in room_to_session_ids.items():
                if len(session_ids) > 1:
                    session_ids = sorted(session_ids)
                    issues.append({
                        "type": "section_clash",
                        "severity": "hard",
                        "session_ids": session_ids,
                        "fix_session_id": session_ids[0],
                        "detail": f"section ชนกันที่คาบเดียวกันและห้องเดียวกัน ({room_id}) — {', '.join(session_ids)}",
                    })

    # 2. อาจารย์สอนติดกันเกิน 3 คาบรวด
    by_teacher = {}
    for a in schedule:
        if a.get("teacher_id"):
            by_teacher.setdefault(a["teacher_id"], []).append(a)

    for teacher_id, items in by_teacher.items():
        by_day = {}
        for a in items:
            day = block_order.get(str(a["timeslot_id"]), (None, None))[0]
            by_day.setdefault(day, []).append(a)

        for day, day_items in by_day.items():
            day_items_sorted = sorted(
                day_items, key=lambda a: block_order.get(str(a["timeslot_id"]), (None, 0))[1]
            )
            # ใช้ set ของ "block index" ไม่ใช่ timeslot index ตรงๆ — กันนับซ้ำ เพราะ
            # 1 session มี 2 timeslot ที่แม็พไป block index เดียวกัน (ดู _build_block_order)
            slot_indices = sorted({
                block_order.get(str(a["timeslot_id"]), (None, 0))[1] for a in day_items_sorted
            })
            streak = 1
            streak_start_idx = 0
            for i in range(1, len(slot_indices)):
                if slot_indices[i] == slot_indices[i - 1] + 1:
                    streak += 1
                    if streak > 3:
                        # หา session ตัวสุดท้ายของ streak นี้ ไปแก้ (ย้ายออกจาก streak)
                        last_slot_idx = slot_indices[i]
                        fix_target = next(
                            (a for a in day_items_sorted
                             if block_order.get(str(a["timeslot_id"]), (None, -1))[1] == last_slot_idx),
                            None,
                        )
                        issues.append({
                            "type": "teacher_overload",
                            "severity": "hard",
                            "teacher_id": teacher_id,
                            "day": day,
                            "fix_session_id": fix_target["session_id"] if fix_target else None,
                            "detail": f"อาจารย์ {teacher_id} สอนติดกัน {streak} คาบ (block) รวดในวัน {day} ไม่มีพัก",
                        })
                        break
                else:
                    streak = 1

    # 3. กลุ่มเรียนเกิน 3 session/วัน (นับ section 1/2 ของ LAB เดียวกันเป็น session เดียว)
    by_group = {}
    for a in schedule:
        if a.get("group_id"):
            by_group.setdefault(a["group_id"], []).append(a)

    for group_id, items in by_group.items():
        by_day = {}
        for a in items:
            day = day_order.get(str(a["timeslot_id"]), (None, None))[0]
            base_id = a["session_id"].rsplit("-", 1)[0] if a.get("session_id") else None
            by_day.setdefault(day, {}).setdefault(base_id, a)  # เก็บ 1 ตัวแทนต่อ base_id

        for day, base_id_map in by_day.items():
            base_id_map.pop(None, None)
            if len(base_id_map) > 3:
                # เลือกตัวใดตัวหนึ่งไปแก้ (ตัวสุดท้ายที่เจอ)
                fix_target = list(base_id_map.values())[-1]
                issues.append({
                    "type": "full_day",
                    "severity": "hard",
                    "group_id": group_id,
                    "day": day,
                    "fix_session_id": fix_target["session_id"],
                    "detail": f"กลุ่ม {group_id} เรียนเกิน 3 วิชาในวัน {day} ({len(base_id_map)} วิชา)",
                })

    # 4. LAB ควรอยู่วันที่มาหลัง LECTURE ของ subject_selected เดียวกัน (soft)
    sessions_by_subject_selected: dict = {}
    from .section_logic import build_session_list
    for s in build_session_list():
        sessions_by_subject_selected.setdefault(s["subject_selected_id"], []).append(s)

    by_subject_selected_assignment: dict = {}
    for a in schedule:
        base_id = a["session_id"].rsplit("-", 1)[0] if a.get("session_id") else a.get("session_id")
        # subject_selected_id ไม่ได้อยู่ใน assignment โดยตรงเสมอไป ใช้ subject_id+session_id แทนอ้างอิง
    # ใช้ schedule ตรงๆ จับคู่ LECTURE/LAB ผ่าน session_id prefix "SS{id}-..."
    lecture_day_by_prefix: dict[str, str] = {}
    for a in schedule:
        sid = a.get("session_id", "")
        if sid.endswith("-LEC"):
            prefix = sid[: -len("-LEC")]
            lecture_day_by_prefix[prefix] = day_order.get(str(a["timeslot_id"]), (None, None))[0]

    seen_lab_sessions = set()
    for a in schedule:
        sid = a.get("session_id", "")
        if "-LAB" not in sid or sid in seen_lab_sessions:
            continue
        seen_lab_sessions.add(sid)

        prefix = sid.split("-LAB")[0]
        lecture_day = lecture_day_by_prefix.get(prefix)
        if not lecture_day:
            continue

        lab_day = day_order.get(str(a["timeslot_id"]), (None, None))[0]
        day_rank = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4}
        if day_rank.get(lab_day, -1) <= day_rank.get(lecture_day, -1):
            issues.append({
                "type": "lecture_before_lab",
                # ทดลองเปลี่ยนจาก "soft" เป็น "hard" ตามที่ขอ เพื่อดูว่า failed
                # เพิ่มขึ้นเยอะไหม — ถ้าเยอะเกินไปค่อยเปลี่ยนกลับเป็น "soft"
                "severity": "hard",
                "session_id": sid,
                "fix_session_id": sid,
                "detail": f"{sid}: LAB ({lab_day}) ไม่ได้อยู่หลัง LECTURE ({lecture_day})",
            })

    return issues