"""
failure_analysis.py — วิเคราะห์ว่าวิชาไหนจัดไม่ได้เพราะอะไร แล้วเตรียมข้อมูลให้ CheckerAgent ตัดสินใจ

Python ล้วน ไม่ใช้ token ทำ 2 อย่าง:

1) diagnose()  — วิเคราะห์วิชาที่ Greedy จัดไม่ได้ ว่าแต่ละคาบที่เป็นไปได้ถูกขวางด้วยอะไร
   - ขวางด้วย "ข้อมูล" (อาจารย์ตั้งไม่ว่าง / ไม่มีห้องที่จุพอ / วิชา GENERAL ล็อกไว้)
     -> จัดใหม่กี่รอบก็ไม่ช่วย ต้องให้คนแก้ข้อมูล
   - ขวางด้วย "วิชาอื่นที่ Greedy วางไว้ก่อน" -> แก้ได้ โดยย้ายเฉพาะวิชาที่ขวางออก
     สร้างเป็น "ตัวเลือก" (option_id) ให้ Agent เลือก เช่น
       O1: ห้าม 'วิชา X' ลง พุธ 08:00-10:00 (เปิดคาบให้วิชา Y)
     Agent เลือกด้วย option_id เท่านั้น ไม่ต้องพิมพ์ session_id/timeslot_id เอง (กันเดาผิด)

2) เก็บ "รอบที่ดีที่สุด" — ทุกรอบที่จัดเสร็จ ให้คะแนนตาราง ถ้าดีกว่าเดิมเก็บ snapshot ไว้
   ถ้าแย่กว่า คืนตารางกลับเป็นรอบที่ดีที่สุด -> ตารางในระบบมีแต่ดีขึ้นหรือเท่าเดิม
"""

import copy

from agent_timetable.tools.get_data import supabase
from .load_data import get_cached_data, refresh_cache
from .section_logic import build_session_list
from .slot_filter import _build_blocks
from .assignment_store import get_current_schedule_raw
from .auto_assign import can_retry_session

MAX_SESSIONS_TO_DIAGNOSE = 8   # จำกัดจำนวนวิชาที่วิเคราะห์ กันผลยาวจน LLM อ่านช้า
MAX_OPTIONS_PER_SESSION = 3


# ───────────────────────── 1. วิเคราะห์ ─────────────────────────

def _block_label(ts_ids: list[str], timeslots_by_id: dict) -> str:
    rows = sorted((timeslots_by_id[t] for t in ts_ids if t in timeslots_by_id), key=lambda t: t["start_time"])
    if not rows:
        return "-"
    return f"{rows[0]['day']} {str(rows[0]['start_time'])[:5]}-{str(rows[-1]['end_time'])[:5]}"


def _subject_name(subjects_by_id: dict, subject_id) -> str:
    s = subjects_by_id.get(subject_id, {})
    return s.get("name_thai") or s.get("name_english") or str(subject_id)


def _diagnose_session(session: dict, data: dict, sessions_by_id: dict, option_counter: list) -> dict:
    timeslots = data["timeslots"]
    timeslots_by_id = {str(t["timeslot_id"]): t for t in timeslots}
    subjects_by_id = {s["subject_id"]: s for s in data["subjects"]}
    groups_map = {g["group_id"]: g["total_students"] for g in data["groups"]}

    teacher_ids = set(session.get("teacher_ids") or [])
    group_ids = set(session.get("group_ids") or [])
    student_count = session.get("max_capacity") or sum(groups_map.get(g, 0) for g in group_ids)

    if session.get("fixed_room_id"):
        rooms = [r for r in data["rooms"] if r["room_id"] == session["fixed_room_id"]]
    else:
        rooms = [r for r in data["rooms"]
                 if r["room_type"] == session["room_type"] and r["capacity"] >= student_count]

    base = {
        "session_id": session["session_id"],
        "subject": _subject_name(subjects_by_id, session["subject_id"]),
        "subject_id": session["subject_id"],
        "session_type": session["session_type"],
        "section": session.get("section"),
    }
    if not can_retry_session(session):
        return {**base, "verdict": "needs_manual",
                "why": "วิชาเรียนรวดหลายชั่วโมง หรือต้องเรียนเวลาเดียวกับวิชาอื่น ให้ผู้ใช้ลากวางเอง"}
    if not rooms:
        return {**base, "verdict": "data_problem",
                "why": f"ไม่มีห้องประเภท {session['room_type']} ที่จุได้ {student_count} คน"}

    teacher_unavail = {str(r["timeslot_id"]) for r in data["teacher_unavailability"] if r["teacher_id"] in teacher_ids}
    room_unavail: dict[str, set] = {}
    for r in data["room_unavailability"]:
        room_unavail.setdefault(r["room_id"], set()).add(str(r["timeslot_id"]))

    # ใครอยู่คาบไหนบ้าง (ไม่นับตัวเอง)
    rows_at: dict[str, list] = {}
    for a in data["existing"] + data["assignments"]:
        if a.get("session_id") == session["session_id"]:
            continue
        rows_at.setdefault(str(a["timeslot_id"]), []).append(a)

    count = {"teacher_unavailable": 0, "locked_general": 0, "room_unavailable": 0,
             "blocked_by_other_sessions": 0, "free_but_rule": 0}
    single_blockers: list[dict] = []   # คาบที่มีวิชาเดียวขวาง = ย้ายวิชานั้นออกก็ลงได้เลย

    for block in _build_blocks(timeslots):
        ts_ids = block["timeslot_ids"]
        if teacher_ids and any(t in teacher_unavail for t in ts_ids):
            count["teacher_unavailable"] += 1
            continue
        usable_rooms = [r for r in rooms
                        if not any(t in room_unavail.get(r["room_id"], set()) for t in ts_ids)]
        if not usable_rooms:
            count["room_unavailable"] += 1
            continue

        rows = [a for t in ts_ids for a in rows_at.get(t, [])]
        usable_room_ids = {r["room_id"] for r in usable_rooms}

        def _conflicts(rs):
            """คืน (ติดวิชาที่ล็อกไว้ไหม, ชุดวิชาที่ขวาง {session_id: เรื่องที่ขวาง})"""
            locked, found = False, {}
            for x in rs:
                kind = None
                if teacher_ids and x.get("teacher_id") in teacher_ids:
                    kind = "อาจารย์ไม่ว่าง"
                elif group_ids and x.get("group_id") in group_ids:
                    kind = "นิสิตกลุ่มนี้ติดเรียน"
                if kind:
                    if x.get("session_id"):
                        found.setdefault(x["session_id"], kind)
                    else:
                        locked = True   # วิชา GENERAL ที่ล็อกไว้ ย้ายไม่ได้
            busy = {x.get("room_id") for x in rs if x.get("room_id")}
            if usable_room_ids <= busy:
                for x in rs:
                    if x.get("room_id") in usable_room_ids and x.get("session_id"):
                        found.setdefault(x["session_id"], "ห้องไม่ว่าง")
            return locked, found

        locked, blockers = _conflicts(rows)
        if locked:
            count["locked_general"] += 1
        elif blockers:
            count["blocked_by_other_sessions"] += 1
            # หาวิชาที่ "ย้ายออกวิชาเดียวแล้วคาบนี้ว่างพอ" (ทั้งอาจารย์ นิสิต และห้อง)
            for sid, kind in blockers.items():
                _, left = _conflicts([x for x in rows if x.get("session_id") != sid])
                if not left:
                    single_blockers.append({"blocker": sid, "kind": kind, "timeslot_ids": ts_ids})
        else:
            # คาบว่างครบ แต่ติดกฎ hard (เรียนเกิน 3 วิชา/วัน, สอนรวดเกิน 3, LAB วันเดียวกับ LECTURE ฯลฯ)
            count["free_but_rule"] += 1

    options = []
    for sb in single_blockers:
        if len(options) >= MAX_OPTIONS_PER_SESSION:
            break
        blocker = sessions_by_id.get(sb["blocker"])
        if not can_retry_session(blocker):
            continue   # วิชาที่ระบบย้ายเองไม่ได้ ไม่เสนอ
        option_counter[0] += 1
        options.append({
            "option_id": f"O{option_counter[0]}",
            "advice": (
                f"ห้าม {_subject_name(subjects_by_id, blocker['subject_id'])} "
                f"[{blocker['session_type']}] ลง {_block_label(sb['timeslot_ids'], timeslots_by_id)} "
                f"({sb['kind']}) เพื่อเปิดคาบให้วิชานี้"
            ),
            "_forbid_session_id": sb["blocker"],
            "_forbid_timeslot_ids": sb["timeslot_ids"],
            "_for_session_id": session["session_id"],
        })

    retry_helps = count["blocked_by_other_sessions"] > 0 or count["free_but_rule"] > 0
    return {
        **base,
        "verdict": "retry_may_help" if retry_helps else "data_problem",
        "blocks": count,
        "options": options,
    }


def diagnose(failed_sessions: list[dict], hard_issues: list[dict]) -> dict:
    """คืนผลวิเคราะห์ (ส่งให้ Agent อ่าน) + ตารางแปลง option_id -> คำแนะนำจริง (เก็บใน state)"""
    data = get_cached_data()
    sessions_by_id = {s["session_id"]: s for s in build_session_list()}

    seen, results, counter = set(), [], [0]
    for f in failed_sessions:
        sid = f.get("session_id")
        if not sid or sid in seen or sid not in sessions_by_id:
            continue
        seen.add(sid)
        if len(results) >= MAX_SESSIONS_TO_DIAGNOSE:
            break
        d = _diagnose_session(sessions_by_id[sid], data, sessions_by_id, counter)
        d["greedy_reason"] = f.get("reason")
        results.append(d)

    option_map = {}
    for d in results:
        for o in d.get("options", []):
            option_map[o["option_id"]] = {
                "session_id": o.pop("_forbid_session_id"),
                "timeslot_ids": o.pop("_forbid_timeslot_ids"),
                "for_session_id": o.pop("_for_session_id"),
            }

    # hard issue ที่ Python แก้ไม่ได้แล้ว — แนะนำให้จัดวิชานั้นก่อนในรอบถัดไป
    subjects_by_id = {s["subject_id"]: s for s in data["subjects"]}
    issues = []
    for i in hard_issues:
        s = sessions_by_id.get(i.get("fix_session_id"))
        issues.append({
            "type": i.get("type"),
            "detail": i.get("detail"),
            "subject_id": s["subject_id"] if s else None,
            "subject": _subject_name(subjects_by_id, s["subject_id"]) if s else None,
        })

    return {
        "failed": results,
        "hard_issues": issues,
        # True = ไม่มีอะไรที่ระบบแก้เองได้แล้ว (ติดข้อมูล หรือต้องลากวางเอง ทั้งหมด)
        "retry_cannot_help": bool(results) and not issues and all(d["verdict"] != "retry_may_help" for d in results),
        "_option_map": option_map,
    }


# ───────────────────────── 2. เก็บรอบที่ดีที่สุด ─────────────────────────

_best: dict = {"score": None, "rows": None, "result": None}


def schedule_score(result: dict) -> tuple:
    """ยิ่งน้อยยิ่งดี: วิชาที่จัดไม่ได้ก่อน -> hard issue ที่เหลือ -> soft issue"""
    return (
        result.get("failed_count", 0),
        result.get("remaining_hard_issue_count", 0),
        result.get("remaining_soft_issue_count", 0),
    )


def reset_best() -> None:
    _best.update(score=None, rows=None, result=None)


def keep_if_best(result: dict) -> bool:
    """เรียกหลังจัดแต่ละรอบ คืน True ถ้ารอบนี้ดีกว่าเดิม (และเก็บไว้แล้ว)"""
    score = schedule_score(result)
    if _best["score"] is not None and score >= _best["score"]:
        return False
    _best.update(score=score, rows=copy.deepcopy(get_current_schedule_raw()), result=copy.deepcopy(result))
    return True


def snapshot_rows() -> list[dict]:
    """สำเนาตารางปัจจุบันทั้งหมด (ไว้คืนค่าถ้าการแก้ขั้นไหนไม่สำเร็จ)"""
    return copy.deepcopy(get_current_schedule_raw())


def restore_rows(rows: list[dict]) -> None:
    """คืนตารางให้เหมือน snapshot ทุกประการ"""
    supabase.table("timetable_ai").delete().neq("id", 0).execute()
    if rows:
        supabase.table("timetable_ai").insert(copy.deepcopy(rows)).execute()
    refresh_cache()


def best_result() -> dict | None:
    return copy.deepcopy(_best["result"])


def restore_best() -> dict | None:
    """คืนตารางในระบบกลับเป็นรอบที่ดีที่สุด คืน result ของรอบนั้น (None ถ้ายังไม่มี)"""
    if _best["rows"] is None:
        return None
    restore_rows(_best["rows"])
    return best_result()