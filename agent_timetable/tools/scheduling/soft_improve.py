"""
soft_improve.py — ปรับตารางที่ "จัดได้แล้ว ไม่ผิดกฎ แต่ยังไม่ดี" (soft issue)

ตอนนี้รองรับ soft issue แบบ "LAB อยู่ก่อนวัน LECTURE" (lecture_before_lab ใน find_issues.py)

แบ่งหน้าที่:
  - Python (ไฟล์นี้) หาทางเลือก + ลองแบบไม่บันทึก + วัดผลกระทบ แล้วลงมือแก้จริง
  - CheckerAgent ตัดสินใจว่าตัวเลือกไหนคุ้มที่จะแก้ (soft issue ไม่จำเป็นต้องแก้ทุกจุด
    และการแก้บางแบบต้องขยับวิชาอื่น ต้องชั่งน้ำหนัก)

ตัวเลือกมี 3 แบบ:
  1) move — ย้าย LAB ไปคาบว่างที่อยู่หลังวัน LECTURE (ไม่กระทบวิชาอื่น)
  2) move_pair — LAB ที่แบ่ง 2 section ย้ายทั้งคู่ไปด้วยกัน (ใช้วิธีจับคู่เดียวกับตอนจัดอัตโนมัติ
     คือห้องเดียวกันคาบติดกัน หรือเวลาเดียวกันคนละห้อง) ไม่กระทบวิชาอื่น
  3) swap — สลับ LAB กับวิชาอื่นที่อยู่วันหลัง LECTURE (อีกวิชาต้องขยับด้วย)

ทุกการแก้: ตรวจซ้ำทันที ถ้า hard issue เพิ่ม / soft ไม่ลด / LAB-LECTURE วันเดียวกัน
-> คืนตารางกลับเหมือนก่อนแก้จุดนั้น

หมายเหตุ: manual_swap_sessions() ไม่ได้เช็คกฎ "LAB ห้ามวันเดียวกับ LECTURE" ไฟล์นี้จึงเช็คซ้ำเอง
ใน _same_day_violation() (find_issues() ก็ตรวจข้อนี้เป็น hard แล้ว ใช้เป็นด่านที่สอง)
"""

from .load_data import get_cached_data
from .section_logic import build_session_list
from .slot_filter import get_valid_slots
from .candidate_scorer import passes_hard_rules, is_after_lecture_day, day_of
from .assignment_store import (
    get_current_schedule_raw,
    delete_session_assignment,
    record_assignment,
    _find_paired_session,
)
from .candidate_picker import assign_lab_pair_deterministic
from .find_issues import find_issues
from .auto_assign import can_retry_session, _unplaced_sessions
from .failure_analysis import snapshot_rows, restore_rows

MAX_SOFT_ISSUES_TO_REVIEW = 5   # จำกัดจำนวนจุดที่วิเคราะห์ต่อรอบ กันผลยาวจน LLM อ่านช้า
MAX_SWAP_TRIALS = 8             # การลองสลับต้องเขียน/คืนตารางจริง จำกัดไว้ไม่ให้ช้า
MAX_SWAPS_PER_ISSUE = 2


# ───────────────────────── ตัวช่วย ─────────────────────────

def _subject_name(subject_id) -> str:
    s = next((x for x in get_cached_data()["subjects"] if x["subject_id"] == subject_id), {})
    return s.get("name_thai") or s.get("name_english") or str(subject_id)


def _lecture_days(session: dict, sessions: list[dict], raw: list[dict]) -> set[str]:
    """ทุกวันที่มี LECTURE ของวิชาเดียวกับ LAB นี้ (วิธีเดียวกับ move_session)"""
    if session.get("session_type") != "LAB":
        return set()
    my_groups = set(session.get("group_ids") or [])
    lecture_ids = {
        s["session_id"] for s in sessions
        if s["session_type"] == "LECTURE"
        and (
            s["subject_selected_id"] == session["subject_selected_id"]
            or (s["subject_id"] == session["subject_id"] and my_groups & set(s.get("group_ids") or []))
        )
    }
    days = {day_of(a["timeslot_id"]) for a in raw if a.get("session_id") in lecture_ids}
    days.discard("")
    return days


def _session_days(session_id: str, raw: list[dict]) -> set[str]:
    days = {day_of(a["timeslot_id"]) for a in raw if a.get("session_id") == session_id}
    days.discard("")
    return days


def _same_day_violation(session_ids: list[str]) -> bool:
    """True ถ้ามี LAB ตัวไหนใน session_ids ไปอยู่วันเดียวกับ LECTURE ของวิชาตัวเอง (ผิดกฎบังคับ)"""
    sessions = build_session_list()
    by_id = {s["session_id"]: s for s in sessions}
    raw = get_current_schedule_raw()
    for sid in session_ids:
        s = by_id.get(sid)
        if not s or s.get("session_type") != "LAB":
            continue
        if _session_days(sid, raw) & _lecture_days(s, sessions, raw):
            return True
    return False


def _issue_counts() -> tuple[int, int]:
    issues = find_issues()
    hard = sum(1 for i in issues if i.get("severity") == "hard")
    soft = sum(1 for i in issues if i.get("severity") == "soft")
    return hard, soft


def _can_touch(session: dict | None) -> bool:
    """LAB ที่ระบบปรับเองได้ — ไม่รวม section คู่ที่ต้องเวลาเดียวกัน (ย้ายเดี่ยวจะแยกคู่)"""
    if not can_retry_session(session):
        return False
    if session.get("section") and _find_paired_session(build_session_list(), session):
        return False
    return True


def _section_siblings(session: dict, sessions: list[dict]) -> list[dict]:
    """section ทั้งหมดของ LAB นี้ (วิชา+กลุ่ม+ประเภทเดียวกัน) รวมตัวเอง เรียงตาม section"""
    if not session or not session.get("section"):
        return []
    key = (session["subject_id"], tuple(sorted(session.get("group_ids") or [])), session["session_type"])
    sibs = [s for s in sessions if s.get("section")
            and (s["subject_id"], tuple(sorted(s.get("group_ids") or [])), s["session_type"]) == key]
    return sorted(sibs, key=lambda s: (str(s.get("section")), s["session_id"]))


def _pair_for(session: dict | None, sessions: list[dict]) -> list[dict] | None:
    """คืน [section1, section2] ถ้าเป็น LAB คู่ 2 section ที่ระบบย้ายพร้อมกันได้ ไม่งั้น None
    (3 section ขึ้นไป / เรียนรวด / LECTURE ของกลุ่ม SYNC ยังไม่รองรับ)
    """
    if not session or session.get("session_type") != "LAB":
        return None
    sibs = _section_siblings(session, sessions)
    if len(sibs) != 2 or not all(can_retry_session(s) for s in sibs):
        return None
    return sibs


def _try_move_pair(pair: list[dict], lec_days: set[str]) -> tuple[dict, dict] | None:
    """ย้าย LAB คู่ไปวันหลัง LECTURE พร้อมกัน — "เขียนตารางจริง" ผู้เรียกต้อง snapshot ไว้เอง
    คืน (candidate_a, candidate_b) ถ้าสำเร็จ หรือ None (ผู้เรียกต้อง restore เอง)
    """
    a, b = pair
    delete_session_assignment(a["session_id"])
    delete_session_assignment(b["session_id"])
    ra = get_valid_slots(a["session_id"], limit=None)
    rb = get_valid_slots(b["session_id"], limit=None)
    if ra.get("error") or rb.get("error"):
        return None
    # รับเฉพาะคาบที่อยู่หลังวัน LECTURE ทั้งคู่ — ไม่งั้นย้ายไปก็ไม่ได้แก้อะไร
    ca = [c for c in ra["valid_slots"] if is_after_lecture_day(c["day"], lec_days)]
    cb = [c for c in rb["valid_slots"] if is_after_lecture_day(c["day"], lec_days)]
    if not ca or not cb:
        return None
    same_teacher = bool(set(a.get("teacher_ids") or []) & set(b.get("teacher_ids") or []))
    chosen = assign_lab_pair_deterministic(a, b, ca, cb, get_current_schedule_raw(),
                                           same_teacher=same_teacher, lecture_day=lec_days)
    if not chosen:
        return None
    record_assignment(a, chosen[0])
    record_assignment(b, chosen[1])
    return chosen


def _move_candidates(session: dict, lec_days: set[str]) -> list[dict]:
    """คาบว่างหลังวัน LECTURE ที่ผ่านกฎบังคับครบ (อ่านอย่างเดียว ไม่แก้ตาราง)"""
    sid = session["session_id"]
    res = get_valid_slots(sid, limit=None)
    if res.get("error"):
        return []
    others = [a for a in get_current_schedule_raw() if a.get("session_id") != sid]
    current_room = next((a.get("room_id") for a in get_current_schedule_raw() if a.get("session_id") == sid), None)
    ok = [
        c for c in res["valid_slots"]
        if is_after_lecture_day(c["day"], lec_days)
        and passes_hard_rules(session, c["timeslot_ids"], others, lec_days)
    ]
    return sorted(ok, key=lambda c: 0 if c["room_id"] == current_room else 1)   # ห้องเดิมก่อน


def _do_move(session: dict, candidate: dict, lec_days: set[str]) -> str | None:
    """ย้ายจริง คืนข้อความ error หรือ None ถ้าสำเร็จ (ผู้เรียกต้อง snapshot ไว้เอง)"""
    sid = session["session_id"]
    delete_session_assignment(sid)
    res = get_valid_slots(sid, limit=None)
    valid = [c for c in res.get("valid_slots", [])
             if c["timeslot_ids"] == candidate["timeslot_ids"] and c["room_id"] == candidate["room_id"]]
    if not valid:
        # คาบเดิมที่เคยเสนอถูกใช้ไปแล้ว ลองคาบอื่นที่อยู่หลังวัน LECTURE แทน
        valid = [c for c in res.get("valid_slots", []) if is_after_lecture_day(c["day"], lec_days)]
    others = get_current_schedule_raw()
    valid = [c for c in valid if passes_hard_rules(session, c["timeslot_ids"], others, lec_days)]
    if not valid:
        return "ไม่มีคาบว่างหลังวัน LECTURE แล้ว"
    record_assignment(session, valid[0])
    return None


def _swap_partners(session: dict, lec_days: set[str], raw: list[dict], by_id: dict) -> list[str]:
    """วิชาที่อาจสลับด้วยได้: อยู่วันหลัง LECTURE, ความยาวเท่ากัน, ใช้ห้องประเภทเดียวกัน"""
    sid = session["session_id"]
    my_len = len({a["timeslot_id"] for a in raw if a.get("session_id") == sid})
    seen, result = set(), []
    for a in raw:
        other_id = a.get("session_id")
        if not other_id or other_id == sid or other_id in seen:
            continue
        seen.add(other_id)
        other = by_id.get(other_id)
        if not _can_touch(other) or other.get("room_type") != session.get("room_type"):
            continue
        if other.get("subject_id") == session.get("subject_id"):
            continue
        if not (_session_days(other_id, raw) and
                all(is_after_lecture_day(d, lec_days) for d in _session_days(other_id, raw))):
            continue
        if len({x["timeslot_id"] for x in raw if x.get("session_id") == other_id}) != my_len:
            continue
        result.append(other_id)
    return result


# ───────────────────────── 1. วิเคราะห์ (ให้ Agent อ่าน) ─────────────────────────

def review_soft_issues() -> dict:
    """หาทางเลือกแก้ LAB ที่อยู่ก่อนวัน LECTURE พร้อมผลกระทบของแต่ละทาง
    คืน {"issues": [...], "_option_map": {...}} — _option_map เก็บใน state ไม่ส่งให้ LLM
    """
    from .swap_session import manual_swap_sessions

    sessions = build_session_list()
    by_id = {s["session_id"]: s for s in sessions}
    soft = [i for i in find_issues() if i.get("type") == "lecture_before_lab"]
    hard0, soft0 = _issue_counts()

    issues, option_map, counter, trials = [], {}, [0], [0]

    def _new_option(entry: dict, advice: str, impact: str) -> dict:
        counter[0] += 1
        oid = f"S{counter[0]}"
        option_map[oid] = entry
        return {"option_id": oid, "advice": advice, "impact": impact}

    done: set[str] = set()   # LAB คู่จะโผล่ใน find_issues 2 รายการ (section 1, 2) ดูครั้งเดียวพอ
    for issue in soft:
        if len(issues) >= MAX_SOFT_ISSUES_TO_REVIEW:
            break
        sid = issue.get("session_id")
        if sid in done:
            continue
        done.add(sid)
        session = by_id.get(sid)
        raw = get_current_schedule_raw()
        name = _subject_name(session["subject_id"]) if session else sid
        lec_days = _lecture_days(session, sessions, raw) if session else set()
        base = {
            "subject": name,
            "lab_day": ", ".join(sorted(_session_days(sid, raw))),
            "lecture_day": ", ".join(sorted(lec_days)),
        }
        pair = _pair_for(session, sessions) if lec_days else None
        if pair:
            done.update(p["session_id"] for p in pair)
            option = None
            if trials[0] < MAX_SWAP_TRIALS:
                trials[0] += 1
                before = snapshot_rows()
                try:
                    chosen = _try_move_pair(pair, lec_days)
                    if chosen and not _same_day_violation([p["session_id"] for p in pair]):
                        hard1, soft1 = _issue_counts()
                        if hard1 <= hard0 and soft1 < soft0:
                            ca, cb = chosen
                            where = (f"{ca['timeslot_label']} ห้อง {ca['room_name']} และ "
                                     f"{cb['timeslot_label']} ห้อง {cb['room_name']}")
                            option = _new_option(
                                {"kind": "move_pair", "session_id": pair[0]["session_id"],
                                 "other_session_id": pair[1]["session_id"]},
                                f"ย้าย LAB ทั้ง 2 section ของ {name} ไป {where}",
                                f"ไม่กระทบวิชาอื่น, soft issue ลดลง {soft0 - soft1} จุด",
                            )
                finally:
                    restore_rows(before)
            if option:
                issues.append({**base, "verdict": "can_improve", "options": [option]})
            else:
                issues.append({**base, "verdict": "keep",
                               "why": "LAB 2 section ไม่มีคาบว่างหลังวัน LECTURE ที่ย้ายไปพร้อมกันได้"})
            continue

        if not _can_touch(session) or not lec_days:
            issues.append({**base, "verdict": "needs_manual",
                           "why": "LAB แบ่ง 3 section ขึ้นไป/เรียนรวด ระบบย้ายเองไม่ได้ ให้ผู้ใช้ลากวางเอง"})
            continue

        options = []
        moves = _move_candidates(session, lec_days)
        if moves:
            c = moves[0]
            options.append(_new_option(
                {"kind": "move", "session_id": sid, "candidate": c},
                f"ย้าย LAB ของ {name} ไป {c['timeslot_label']} ห้อง {c['room_name']}",
                "ไม่กระทบวิชาอื่น",
            ))
        else:
            # ไม่มีคาบว่าง — ลองสลับกับวิชาอื่น (เขียนตารางจริงแล้วคืนกลับทุกครั้ง)
            for other_id in _swap_partners(session, lec_days, raw, by_id):
                if trials[0] >= MAX_SWAP_TRIALS or len(options) >= MAX_SWAPS_PER_ISSUE:
                    break
                trials[0] += 1
                before = snapshot_rows()
                try:
                    r = manual_swap_sessions(sid, other_id)
                    if not r.get("success") or _same_day_violation([sid, other_id]):
                        continue
                    hard1, soft1 = _issue_counts()
                    if hard1 > hard0 or soft1 >= soft0:
                        continue
                    other = by_id[other_id]
                    gained = soft0 - soft1
                    options.append(_new_option(
                        {"kind": "swap", "session_id": sid, "other_session_id": other_id},
                        f"สลับ LAB ของ {name} กับ {_subject_name(other['subject_id'])} "
                        f"[{other['session_type']}]",
                        f"{_subject_name(other['subject_id'])} ต้องย้ายวัน, soft issue ลดลง {gained} จุด",
                    ))
                finally:
                    restore_rows(before)

        if options:
            issues.append({**base, "verdict": "can_improve", "options": options})
        else:
            issues.append({**base, "verdict": "keep",
                           "why": "ไม่มีคาบว่างหรือวิชาที่สลับได้ โดยไม่ผิดกฎข้ออื่น"})

    return {
        "soft_issue_count": soft0,
        "reviewed": len(issues),
        "issues": issues,
        "_option_map": option_map,
    }


# ───────────────────────── 2. ลงมือแก้ ─────────────────────────

def apply_soft_fixes(fixes: list[dict], previous_failed: list[dict]) -> dict:
    """ทำตามตัวเลือกที่ Agent เลือก ทีละจุด ตรวจซ้ำทุกจุด ไม่ดีขึ้นก็คืนกลับ
    คืนผลหน้าตาเดียวกับ auto_assign_all() + "moves"
    """
    from .swap_session import manual_swap_sessions

    sessions = build_session_list()
    by_id = {s["session_id"]: s for s in sessions}
    log = []

    for fx in fixes:
        sid = fx.get("session_id")
        session = by_id.get(sid)
        if not session:
            continue
        hard0, soft0 = _issue_counts()
        before = snapshot_rows()
        lec_days = _lecture_days(session, sessions, get_current_schedule_raw())
        touched = [sid]

        if fx["kind"] == "move":
            error = _do_move(session, fx["candidate"], lec_days)
        elif fx["kind"] == "move_pair":
            other = by_id.get(fx["other_session_id"])
            touched.append(fx["other_session_id"])
            ok = other and _try_move_pair([session, other], lec_days)
            error = None if ok else "ไม่มีคาบว่างหลังวัน LECTURE ให้ LAB ทั้งคู่แล้ว"
        else:
            touched.append(fx["other_session_id"])
            r = manual_swap_sessions(sid, fx["other_session_id"])
            error = None if r.get("success") else r.get("reason")

        if error is None:
            hard1, soft1 = _issue_counts()
            if _same_day_violation(touched):
                error = "LAB ไปอยู่วันเดียวกับ LECTURE"
            elif hard1 > hard0:
                error = "ทำให้เกิดปัญหาชนกันใหม่"
            elif soft1 >= soft0:
                error = "แก้แล้วไม่ดีขึ้น"

        if error:
            restore_rows(before)
            log.append({**{k: v for k, v in fx.items() if k != "candidate"}, "success": False, "reason": error})
        else:
            log.append({**{k: v for k, v in fx.items() if k != "candidate"}, "success": True})

    hard, soft = _issue_counts()
    failed = _unplaced_sessions(previous_failed)
    placed = {a.get("session_id") for a in get_current_schedule_raw() if a.get("session_id")}
    return {
        "assigned_count": len(placed),
        "failed_count": len(failed),
        "assigned": [],
        "failed": failed,
        "rounds_used": 0,
        "converged": hard == 0,
        "remaining_hard_issue_count": hard,
        "remaining_soft_issue_count": soft,
        "moves": log,
    }