"""
swap_session.py — สลับเวลาเรียนของ 2 session ที่ผู้ใช้ลากวิชาหนึ่งไปวางบนอีกวิชาหนึ่งในตาราง

หลักการ: A ไปอยู่เวลาของ B และ B ไปอยู่เวลาของ A "พร้อมกัน" (atomic)
  - ลบทั้งคู่ออกจาก timetable_ai ชั่วคราว
  - หา candidate ของ A ที่ตรงกับเวลาเดิมของ B เป๊ะ และของ B ที่ตรงกับเวลาเดิมของ A
    (ใช้ get_valid_slots ตัวเดียวกับการย้าย/จัดอัตโนมัติ — กฎอาจารย์/ห้อง/นิสิตชน,
    เวลาไม่ว่าง, ความจุ, ประเภทห้อง ถูกเช็คครบเหมือนกันทุกทาง)
  - เลือกห้อง: ใช้ห้องเดิมของตัวเองก่อน → ห้องของอีกฝ่าย (เพราะอีกฝ่ายย้ายออกแล้ว) → ห้องอื่นที่ว่าง
  - เช็ค hard rule ของ B โดยนับ A ที่ย้ายเข้าไปแล้วด้วย (เช่น บล็อกวิชาเดียวกันต้องคนละวัน)
  - ผ่านทั้งคู่ถึงบันทึก ถ้าไม่ผ่านอย่างใดอย่างหนึ่ง คืนค่าเดิมทั้งคู่ (ไม่มีค้างครึ่งๆ กลางๆ)

ยังไม่รองรับ (ตอบเหตุผลกลับไปให้ผู้ใช้ใช้การลากย้ายปกติแทน):
  - วิชาที่เรียนต่อเนื่องหลายชั่วโมง (continuous_size เช่น 273252 3 ชม.รวด)
  - LAB ที่แบ่ง 2 กลุ่มเรียนเวลาเดียวกันคนละห้อง (ต้องย้ายทั้งคู่ไปด้วยกัน
    manual_move_session จัดการให้อยู่แล้ว)
  - 2 session ที่ความยาวไม่เท่ากัน
"""

from agent_timetable.tools.get_data import supabase
from .load_data import get_cached_data, refresh_cache
from .candidate_scorer import passes_hard_rules as passes_hard_rules_check
from .assignment_store import (
    get_current_schedule_raw,
    delete_session_assignment,
    record_assignment,
    _find_paired_session,
    _diagnose_slot_failure,
    _double_check_still_free,
    _fake_assignment_for,
)


def _subject_name(subject_id: str | None) -> str:
    subj = next((s for s in get_cached_data()["subjects"] if s["subject_id"] == subject_id), {})
    return subj.get("name_thai") or subj.get("name_english") or subject_id or "วิชา"


def _slot_set(candidate: dict) -> set[str]:
    return {str(t) for t in candidate["timeslot_ids"]}


def _room_priority(candidates: list[dict], own_room, other_room) -> list[dict]:
    """ห้องเดิมของตัวเองก่อน → ห้องของอีกฝ่าย → ห้องอื่น"""
    def rank(c):
        if c["room_id"] == own_room:
            return 0
        if c["room_id"] == other_room:
            return 1
        return 2
    return sorted(candidates, key=rank)


def manual_swap_sessions(session_id_a: str, session_id_b: str) -> dict:
    from .section_logic import build_session_list
    from .slot_filter import get_valid_slots

    if session_id_a == session_id_b:
        return {"success": False, "reason": "เลือกวิชาเดียวกัน ไม่ต้องสลับ"}

    sessions = build_session_list()
    sa = next((s for s in sessions if s["session_id"] == session_id_a), None)
    sb = next((s for s in sessions if s["session_id"] == session_id_b), None)
    if not sa or not sb:
        return {"success": False, "reason": "ไม่พบวิชาที่ต้องการสลับ"}

    name_a, name_b = _subject_name(sa["subject_id"]), _subject_name(sb["subject_id"])

    if sa.get("continuous_size") or sb.get("continuous_size"):
        return {
            "success": False,
            "reason": "วิชาที่เรียนต่อเนื่องหลายชั่วโมงยังสลับไม่ได้ ให้ลากไปวางในช่องว่างแทน",
        }

    refresh_cache()
    current = get_current_schedule_raw()
    rows_a = [r for r in current if r.get("session_id") == session_id_a]
    rows_b = [r for r in current if r.get("session_id") == session_id_b]
    if not rows_a or not rows_b:
        return {"success": False, "reason": "ไม่พบวิชานี้ในตารางปัจจุบัน กรุณารีเฟรชหน้า"}

    slots_a = {str(r["timeslot_id"]) for r in rows_a}
    slots_b = {str(r["timeslot_id"]) for r in rows_b}

    if len(slots_a) != len(slots_b):
        return {
            "success": False,
            "reason": f"สลับไม่ได้ เพราะความยาวคาบไม่เท่ากัน ({name_a} {len(slots_a)} ชม. / {name_b} {len(slots_b)} ชม.)",
        }
    if slots_a & slots_b:
        return {"success": False, "reason": "สองวิชานี้อยู่ในช่วงเวลาเดียวกันอยู่แล้ว"}

    # LAB ที่แบ่ง 2 กลุ่มเรียนพร้อมกันคนละห้อง ต้องย้ายไปด้วยกันทั้งคู่ — สลับเดี่ยวจะทำให้คู่แยกเวลากัน
    for s, slots, name in ((sa, slots_a, name_a), (sb, slots_b, name_b)):
        partner = _find_paired_session(sessions, s)
        if not partner or partner["session_id"] in (session_id_a, session_id_b):
            continue
        partner_slots = {str(r["timeslot_id"]) for r in current if r.get("session_id") == partner["session_id"]}
        if partner_slots & slots:
            return {
                "success": False,
                "reason": f"{name} แบ่งเรียน 2 ห้องพร้อมกัน สลับเดี่ยวไม่ได้ ให้ลากไปวางในช่องว่างแทน (ระบบจะย้ายทั้งคู่ให้)",
            }

    room_a, room_b = rows_a[0]["room_id"], rows_b[0]["room_id"]

    def _rollback():
        supabase.table("timetable_ai").insert(rows_a + rows_b).execute()
        refresh_cache()

    delete_session_assignment(session_id_a)
    delete_session_assignment(session_id_b)

    try:
        res_a = get_valid_slots(session_id_a, limit=None)
        res_b = get_valid_slots(session_id_b, limit=None)
        if res_a.get("error") or res_b.get("error"):
            _rollback()
            return {"success": False, "reason": res_a.get("error") or res_b.get("error")}

        cand_a = [c for c in res_a["valid_slots"] if _slot_set(c) == slots_b]
        cand_b = [c for c in res_b["valid_slots"] if _slot_set(c) == slots_a]

        exclude = {session_id_a, session_id_b}
        if not cand_a:
            reason = _diagnose_slot_failure(sa, sorted(slots_b), None, exclude)
            _rollback()
            return {"success": False, "reason": f"ย้าย {name_a} ไปเวลาของ {name_b} ไม่ได้: {reason}"}
        if not cand_b:
            reason = _diagnose_slot_failure(sb, sorted(slots_a), None, exclude)
            _rollback()
            return {"success": False, "reason": f"ย้าย {name_b} ไปเวลาของ {name_a} ไม่ได้: {reason}"}

        # หาคู่ห้องที่ผ่าน hard rule พร้อมกัน — เช็ค B โดยนับ A ที่ย้ายเข้าไปแล้วด้วย
        base = get_current_schedule_raw()
        chosen = None
        for ca in _room_priority(cand_a, room_a, room_b):
            if not passes_hard_rules_check(sa, ca["timeslot_ids"], base):
                continue
            with_a = base + [_fake_assignment_for(sa, ca)]
            for cb in _room_priority(cand_b, room_b, room_a):
                if passes_hard_rules_check(sb, cb["timeslot_ids"], with_a):
                    chosen = (ca, cb)
                    break
            if chosen:
                break

        if not chosen:
            _rollback()
            return {
                "success": False,
                "reason": "สลับแล้วผิดเงื่อนไขของตาราง (เช่น วิชาเดียวกันอยู่วันเดียวกัน หรือเรียนเต็มวัน)",
            }

        ca, cb = chosen
        dcheck = _double_check_still_free(ca["room_id"], sa["teacher_ids"], sa["group_ids"], ca["timeslot_ids"], exclude) \
            or _double_check_still_free(cb["room_id"], sb["teacher_ids"], sb["group_ids"], cb["timeslot_ids"], exclude)
        if dcheck:
            _rollback()
            return {"success": False, "reason": dcheck}

        item_a = record_assignment(sa, ca)
        item_b = record_assignment(sb, cb)
        return {"success": True, "assignment_a": item_a, "assignment_b": item_b}

    except Exception:
        # มีอะไรพังกลางทาง (เช่น DB) ให้คืนตำแหน่งเดิมก่อน แล้วค่อยโยน error ต่อ
        current_ids = {r.get("session_id") for r in get_current_schedule_raw()}
        if session_id_a not in current_ids and session_id_b not in current_ids:
            _rollback()
        raise