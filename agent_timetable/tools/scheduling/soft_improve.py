"""
soft_improve.py — ปรับตารางที่ "จัดได้แล้ว ไม่ผิดกฎ แต่ยังไม่ดี" (soft issue)
อัลกอริทึม: Local Search แบบ Hill Climbing — ลองขยับทีละจุด เก็บเฉพาะแบบที่ไม่ผิดกฎและดีขึ้น

soft issue ที่รองรับ (จาก find_issues.py):
  - lecture_before_lab  LAB อยู่ก่อนวัน LECTURE
  - lab_pair_split      LAB 2 section อาจารย์เดียวกันไม่ได้เรียนต่อกัน / คนละอาจารย์ไม่ได้เรียนเวลาเดียวกัน

วิธีแก้ (ลองตามลำดับจากขยับน้อยไปมาก หยุดเมื่อเจอวิธีที่แก้ครบทุกจุดของวิชานั้น
ไม่งั้นเลือกวิธีที่ลด soft issue ได้มากที่สุด — ทุกวิธีไม่กระทบวิชาอื่น):
  LAB section เดียว
    move          ย้าย LAB ไปคาบว่างหลังวัน LECTURE
    swap_lec_lab  สลับคาบ LECTURE กับ LAB ของวิชาเดียวกัน (ห้องใช้ประเภทเดิม)
  LAB 2 section
    move_pair     จัด LAB ทั้งคู่ใหม่ (วิธีจับคู่เดียวกับตอนจัดอัตโนมัติ) หลังวัน LECTURE
  ทั้งสองแบบ (จำเป็นเมื่อ LECTURE อยู่วันศุกร์ — ไม่มีวันหลังจากนั้นให้ LAB ย้ายไป)
    move_lecture  เลื่อน LECTURE ไปวันก่อน LAB ทุกตัวของวิชานั้น (LAB อยู่ที่เดิม)
    replan        ยก LECTURE + LAB ทุกตัวของวิชานั้นออก วาง LECTURE วันเร็วสุดที่ว่าง แล้ววาง LAB หลังวันนั้น
                  (ครอบคลุม LECTURE เรียนรวมหลายกลุ่มที่มี LAB หลายตัว)

แบ่งหน้าที่:
  - Python (ไฟล์นี้) ลองแต่ละวิธีแบบไม่บันทึก (เขียนจริง วัดผล แล้วคืนกลับ) -> ตัวเลือกที่ผ่าน
  - CheckerAgent เลือกว่าจะใช้ตัวเลือกไหน -> AssignerAgent เรียก apply_soft_fixes() ลงมือจริง
เกณฑ์ผ่าน: hard issue ไม่เพิ่ม, LAB ไม่อยู่วันเดียวกับ LECTURE, soft issue ลดลง
(ทุกวิธีใช้ฟังก์ชันเดียวกันทั้งตอนลองและตอนลงมือจริง)
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

SOFT_TYPES = {"lecture_before_lab", "lab_pair_split"}
DAY_RANK = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
MAX_SOFT_ISSUES_TO_REVIEW = 5     # จำกัดจำนวนจุดที่วิเคราะห์ต่อรอบ กันผลยาวจน LLM อ่านช้า
MAX_TRIALS = 20                   # จำนวนครั้งที่ลองแบบเขียนจริงแล้วคืนกลับ (ทุกจุดรวมกัน)
MAX_REPLAN_LECTURE_SLOTS = 8      # replan: ลองเวลา LECTURE กี่แบบ (วันเร็วสุดก่อน)

KIND_LABEL = {
    "move": "ย้าย LAB", "swap_lec_lab": "สลับคาบ LECTURE-LAB",
    "move_pair": "จัด LAB 2 section ใหม่", "move_lecture": "เลื่อน LECTURE",
    "replan": "จัด LECTURE+LAB ใหม่ทั้งชุด",
}
TYPE_LABEL = {
    "lecture_before_lab": "LAB อยู่ก่อนวัน LECTURE",
    "lab_pair_split": "LAB 2 section ไม่ได้เรียนต่อกัน/เวลาเดียวกัน",
}


# ───────────────────────── ตัวช่วย ─────────────────────────

def _name(session: dict) -> str:
    s = next((x for x in get_cached_data()["subjects"] if x["subject_id"] == session["subject_id"]), {})
    return s.get("name_thai") or s.get("name_english") or str(session["subject_id"])


def _where(c: dict) -> str:
    return f"{c['timeslot_label']} ห้อง {c['room_name']}"


def _session_days(sid: str, raw: list[dict]) -> set[str]:
    return {day_of(a["timeslot_id"]) for a in raw if a.get("session_id") == sid} - {""}


def _session_slots(sid: str, raw: list[dict]) -> set[str]:
    return {str(a["timeslot_id"]) for a in raw if a.get("session_id") == sid}


def _session_room(sid: str, raw: list[dict]):
    return next((a.get("room_id") for a in raw if a.get("session_id") == sid), None)


def _slots_of(c: dict) -> set[str]:
    return {str(t) for t in c["timeslot_ids"]}


def _lecture_sessions(lab: dict, sessions: list[dict]) -> list[dict]:
    """LECTURE ของวิชาเดียวกับ LAB นี้ (subject_selected เดียวกัน หรือ วิชา+กลุ่มทับกัน = เรียนรวม)"""
    groups = set(lab.get("group_ids") or [])
    return [s for s in sessions if s["session_type"] == "LECTURE"
            and (s["subject_selected_id"] == lab["subject_selected_id"]
                 or (s["subject_id"] == lab["subject_id"] and groups & set(s.get("group_ids") or [])))]


def _lecture_days(lab: dict, sessions: list[dict], raw: list[dict]) -> set[str]:
    if lab.get("session_type") != "LAB":
        return set()
    ids = {s["session_id"] for s in _lecture_sessions(lab, sessions)}
    return {day_of(a["timeslot_id"]) for a in raw if a.get("session_id") in ids} - {""}


def _labs_of_lecture(lec: dict, sessions: list[dict]) -> list[str]:
    """LAB ทุกตัวที่ผูกกับ LECTURE นี้ (รวมกลุ่มอื่นที่เรียน LECTURE รวม) — ต้องเช็ควันชน LECTURE ทุกตัว"""
    groups = set(lec.get("group_ids") or [])
    return [s["session_id"] for s in sessions if s["session_type"] == "LAB"
            and (s["subject_selected_id"] == lec["subject_selected_id"]
                 or (s["subject_id"] == lec["subject_id"] and groups & set(s.get("group_ids") or [])))]


def _single_lecture(lab: dict, sessions: list[dict], raw: list[dict]) -> dict | None:
    """LECTURE ของ LAB นี้ ถ้ามี session เดียวที่วางอยู่และระบบย้ายเองได้"""
    lecs = [s for s in _lecture_sessions(lab, sessions) if _session_days(s["session_id"], raw)]
    return lecs[0] if len(lecs) == 1 and _can_touch(lecs[0]) else None


def _can_touch(session: dict | None) -> bool:
    """session ที่ระบบปรับเองได้ — ไม่รวม section คู่ที่ต้องย้ายพร้อมกัน"""
    if not session or not can_retry_session(session):
        return False
    return not (session.get("section") and _find_paired_session(build_session_list(), session))


def _pair_for(lab: dict, sessions: list[dict]) -> list[dict] | None:
    """[section 1, section 2] ถ้าเป็น LAB 2 section ที่ระบบย้ายพร้อมกันได้ ไม่งั้น None"""
    if lab.get("session_type") != "LAB" or not lab.get("section"):
        return None
    key = (lab["subject_id"], tuple(sorted(lab.get("group_ids") or [])), "LAB")
    sibs = sorted((s for s in sessions if s.get("section") and
                   (s["subject_id"], tuple(sorted(s.get("group_ids") or [])), s["session_type"]) == key),
                  key=lambda s: (str(s["section"]), s["session_id"]))
    return sibs if len(sibs) == 2 and all(can_retry_session(s) for s in sibs) else None


def _same_day_violation(session_ids: list[str]) -> bool:
    """True ถ้ามี LAB ใน session_ids อยู่วันเดียวกับ LECTURE ของวิชาตัวเอง (ผิดกฎบังคับ)
    manual/การย้ายบางทางไม่ได้เช็คข้อนี้ จึงเช็คซ้ำที่นี่ (find_issues ก็ตรวจเป็น hard อีกชั้น)
    """
    sessions = build_session_list()
    by_id = {s["session_id"]: s for s in sessions}
    raw = get_current_schedule_raw()
    return any(by_id.get(sid) and _session_days(sid, raw) & _lecture_days(by_id[sid], sessions, raw)
               for sid in session_ids)


def _issue_counts() -> tuple[int, int]:
    issues = find_issues()
    return (sum(1 for i in issues if i.get("severity") == "hard"),
            sum(1 for i in issues if i.get("severity") == "soft"))


def _place(session: dict, ok, lec_days: set[str], prefer: dict | None = None, prefer_room=None) -> dict | None:
    """วาง session (ที่ถูกลบไว้แล้ว) ลงคาบที่ ok(candidate) และผ่านกฎบังคับครบ
    เลือก prefer (คาบที่เคยเสนอไว้) > ห้องเดิม > ห้องอื่น คืน candidate หรือ None
    """
    res = get_valid_slots(session["session_id"], limit=None)
    if res.get("error"):
        return None
    others = get_current_schedule_raw()
    cands = [c for c in res.get("valid_slots", [])
             if ok(c) and passes_hard_rules(session, c["timeslot_ids"], others, lec_days)]
    if not cands:
        return None
    cands.sort(key=lambda c: (0 if prefer and _slots_of(c) == _slots_of(prefer) and c["room_id"] == prefer["room_id"]
                              else 1, 0 if c["room_id"] == prefer_room else 1))
    record_assignment(session, cands[0])
    return cands[0]


def _place_pair(pair: list[dict], lec_days: set[str]) -> tuple[dict, dict] | None:
    """วาง LAB คู่ (ที่ถูกลบไว้แล้ว) หลังวัน LECTURE ด้วยวิธีจับคู่เดียวกับตอนจัดอัตโนมัติ
    (อาจารย์เดียวกัน = ห้องเดียวกันคาบติดกัน / คนละอาจารย์ = เวลาเดียวกันคนละห้อง)
    """
    a, b = pair
    ra = get_valid_slots(a["session_id"], limit=None)
    rb = get_valid_slots(b["session_id"], limit=None)
    if ra.get("error") or rb.get("error"):
        return None
    ok = (lambda c: is_after_lecture_day(c["day"], lec_days)) if lec_days else (lambda c: True)
    ca, cb = [c for c in ra["valid_slots"] if ok(c)], [c for c in rb["valid_slots"] if ok(c)]
    if not ca or not cb:
        return None
    same_teacher = bool(set(a.get("teacher_ids") or []) & set(b.get("teacher_ids") or []))
    # อาจารย์เดียวกัน: หาคู่ที่ "ต่อกันจริง" เอง (จบ = เริ่มพอดี) ก่อน — ตัวจับคู่ของตอนจัดอัตโนมัติ
    # ยอมรับคู่ที่ไม่ต่อกันได้เมื่อหาไม่เจอ (เช่น 10-12 / 15-17) ถ้าใช้ตัวนั้นอย่างเดียวจะได้คู่เดิมกลับมา
    chosen = _consecutive_pair(ca, cb) if same_teacher else None
    chosen = chosen or assign_lab_pair_deterministic(a, b, ca, cb, get_current_schedule_raw(),
                                                     same_teacher=same_teacher, lecture_day=lec_days)
    if not chosen:
        return None
    record_assignment(a, chosen[0])
    record_assignment(b, chosen[1])
    return chosen


def _consecutive_pair(ca: list[dict], cb: list[dict]) -> tuple[dict, dict] | None:
    """คู่คาบที่วันเดียวกันและต่อกันพอดี (เงื่อนไขเดียวกับ check_schedule หมวด 8) ห้องเดียวกันก่อน
    วันเร็วก่อน (LAB ควรใกล้ LECTURE) — คืน (คาบ a, คาบ b) หรือ None
    """
    ts = {str(t["timeslot_id"]): t for t in get_cached_data()["timeslots"]}

    def span(c):
        rows = sorted((ts[str(t)] for t in c["timeslot_ids"] if str(t) in ts), key=lambda t: t["start_time"])
        return (rows[0]["day"], str(rows[0]["start_time"]), str(rows[-1]["end_time"])) if rows else None

    best = None
    for x in ca:
        sx = span(x)
        for y in cb:
            sy = span(y)
            if not sx or not sy or sx[0] != sy[0] or not (sx[2] == sy[1] or sy[2] == sx[1]):
                continue
            key = (0 if x["room_id"] == y["room_id"] else 1, DAY_RANK.get(sx[0], 99), min(sx[1], sy[1]))
            if best is None or key < best[0]:
                best = (key, x, y)
    return (best[1], best[2]) if best else None


# ─────────────── วิธีแก้ (ใช้ทั้งตอนลองและตอนลงมือจริง) ───────────────
# ทุกวิธี "เขียนตารางจริง" ผู้เรียกต้อง snapshot/restore เอง
# คืน {"touched": LAB ที่ต้องเช็ควันชน LECTURE, "prefer": คาบที่เลือก (ใช้ซ้ำตอนลงมือจริง), "advice": ข้อความ}
# หรือ None ถ้าทำไม่ได้

def _run_move(lab: dict, sessions: list[dict], prefer: dict) -> dict | None:
    sid, raw = lab["session_id"], get_current_schedule_raw()
    lec_days, room = _lecture_days(lab, sessions, raw), _session_room(sid, raw)
    delete_session_assignment(sid)
    c = _place(lab, lambda c: is_after_lecture_day(c["day"], lec_days), lec_days, prefer.get("lab"), room)
    return c and {"touched": [sid], "prefer": {"lab": c},
                  "advice": f"ย้าย LAB ของ {_name(lab)} ไป {_where(c)}"}


def _run_swap_lec_lab(lab: dict, sessions: list[dict], prefer: dict) -> dict | None:
    """LECTURE ไปเวลาเดิมของ LAB, LAB ไปเวลาเดิมของ LECTURE (ต้องยาวเท่ากัน)"""
    raw = get_current_schedule_raw()
    lec = _single_lecture(lab, sessions, raw)
    if not lec:
        return None
    lab_slots, lec_slots = _session_slots(lab["session_id"], raw), _session_slots(lec["session_id"], raw)
    if not lab_slots or len(lab_slots) != len(lec_slots):
        return None
    lab_room, lec_room = _session_room(lab["session_id"], raw), _session_room(lec["session_id"], raw)
    delete_session_assignment(lab["session_id"])
    delete_session_assignment(lec["session_id"])
    lec_c = _place(lec, lambda c: _slots_of(c) == lab_slots, set(), prefer.get("lec"), lec_room)
    if not lec_c:
        return None
    new_days = _lecture_days(lab, sessions, get_current_schedule_raw())
    lab_c = _place(lab, lambda c: _slots_of(c) == lec_slots, new_days, prefer.get("lab"), lab_room)
    return lab_c and {"touched": _labs_of_lecture(lec, sessions), "prefer": {"lec": lec_c, "lab": lab_c},
                      "advice": f"สลับคาบ LECTURE กับ LAB ของ {_name(lab)}: LECTURE ไป {_where(lec_c)}, "
                                f"LAB ไป {_where(lab_c)}"}


def _run_move_pair(lab: dict, sessions: list[dict], prefer: dict) -> dict | None:
    pair = _pair_for(lab, sessions)
    if not pair:
        return None
    lec_days = _lecture_days(pair[0], sessions, get_current_schedule_raw())
    for p in pair:
        delete_session_assignment(p["session_id"])
    chosen = _place_pair(pair, lec_days)
    return chosen and {"touched": [p["session_id"] for p in pair], "prefer": {},
                       "advice": f"จัด LAB 2 section ของ {_name(lab)} ใหม่: "
                                 f"{_where(chosen[0])} และ {_where(chosen[1])}"}


def _lab_units(lec: dict, sessions: list[dict], raw: list[dict]) -> list[list[dict]] | None:
    """LAB ทุกตัวที่ผูกกับ LECTURE นี้ (ที่วางอยู่) จัดเป็นหน่วยที่ต้องย้ายด้วยกัน
    [LAB เดี่ยว] หรือ [section 1, section 2] — ถ้ามีตัวไหนระบบย้ายเองไม่ได้ คืน None
    """
    by_id = {s["session_id"]: s for s in sessions}
    units, seen = [], set()
    for sid in _labs_of_lecture(lec, sessions):
        if sid in seen or not _session_days(sid, raw):
            continue
        lab = by_id[sid]
        pair = _pair_for(lab, sessions)
        unit = pair or ([lab] if _can_touch(lab) else None)
        if not unit:
            return None
        seen.update(s["session_id"] for s in unit)
        units.append(unit)
    return units or None


def _run_move_lecture(lab: dict, sessions: list[dict], prefer: dict) -> dict | None:
    """เลื่อน LECTURE ไปวันก่อน LAB ทุกตัวของวิชานั้น (LAB อยู่ที่เดิม)
    จำเป็นเมื่อ LECTURE อยู่วันศุกร์ — ไม่มีวันหลังจากนั้นให้ย้าย LAB ไป
    """
    raw = get_current_schedule_raw()
    lec = _single_lecture(lab, sessions, raw)
    if not lec:
        return None
    lab_ids = _labs_of_lecture(lec, sessions)
    lab_days = set().union(*(_session_days(x, raw) for x in lab_ids))
    if not lab_days:
        return None
    first_lab = min(DAY_RANK.get(d, 99) for d in lab_days)
    room = _session_room(lec["session_id"], raw)
    delete_session_assignment(lec["session_id"])
    c = _place(lec, lambda c: DAY_RANK.get(c["day"], 99) < first_lab, set(), prefer.get("lec"), room)
    return c and {"touched": lab_ids, "prefer": {"lec": c},
                  "advice": f"เลื่อน LECTURE ของ {_name(lab)} ไป {_where(c)} (ให้มาก่อน LAB)"}


def _run_replan(lab: dict, sessions: list[dict], prefer: dict) -> dict | None:
    """ยก LECTURE + LAB ทุกตัวของวิชานั้นออก -> LECTURE วันเร็วสุดที่ว่าง -> LAB ทุกตัวหลังวันนั้น
    ใช้เมื่อขยับฝั่งเดียวไม่ได้ เช่น LAB อยู่วันจันทร์ หรือ LECTURE อยู่วันศุกร์และไม่มีคาบว่างก่อน LAB
    รองรับ LAB เดี่ยว, LAB 2 section และ LECTURE เรียนรวมที่มี LAB หลายกลุ่ม
    """
    raw = get_current_schedule_raw()
    lec = _single_lecture(lab, sessions, raw)
    units = _lab_units(lec, sessions, raw) if lec else None
    if not units:
        return None
    rooms = {s["session_id"]: _session_room(s["session_id"], raw) for u in units for s in u}
    for s in (lec, *(s for u in units for s in u)):
        delete_session_assignment(s["session_id"])

    # LECTURE ลงวันสุดท้ายของสัปดาห์ไม่ได้ (LAB ต้องอยู่วันหลังจากนั้น) / เวลาละ 1 ห้องพอ จะได้ลองเวลาหลากหลาย
    last_day = max((DAY_RANK.get(t.get("day"), -1) for t in get_cached_data()["timeslots"]), default=4)
    res = get_valid_slots(lec["session_id"], limit=None)
    by_time: dict = {}
    for c in res.get("valid_slots", []) if not res.get("error") else []:
        if DAY_RANK.get(c["day"], 99) < last_day:
            by_time.setdefault(tuple(sorted(_slots_of(c))), c)
    want = prefer.get("lec")
    ordered = sorted(by_time.values(), key=lambda c: (
        0 if want and _slots_of(c) == _slots_of(want) else 1, DAY_RANK.get(c["day"], 99), sorted(_slots_of(c))))

    for lec_c in ordered[:MAX_REPLAN_LECTURE_SLOTS]:
        if not _place(lec, lambda c, t=_slots_of(lec_c): _slots_of(c) == t, set(), want):
            continue
        placed, where = [], []
        for unit in units:
            lec_days = _lecture_days(unit[0], sessions, get_current_schedule_raw())
            if len(unit) == 2:
                got = _place_pair(unit, lec_days)
                where += [_where(got[0]), _where(got[1])] if got else []
            else:
                got = _place(unit[0], lambda c, d=lec_days: is_after_lecture_day(c["day"], d), lec_days,
                             prefer_room=rooms[unit[0]["session_id"]])
                where += [_where(got)] if got else []
            if not got:
                break
            placed.append(unit)
        else:
            return {"touched": _labs_of_lecture(lec, sessions), "prefer": {"lec": lec_c},
                    "advice": f"จัด {_name(lab)} ใหม่ทั้งชุด: LECTURE ไป {_where(lec_c)}, "
                              f"LAB ไป {' และ '.join(where)}"}
        for s in (lec, *(s for u in placed for s in u)):   # เวลานี้ไม่ได้ คืนแล้วลองเวลาถัดไป
            delete_session_assignment(s["session_id"])
    return None


METHODS = {
    "move": _run_move,
    "swap_lec_lab": _run_swap_lec_lab,
    "move_pair": _run_move_pair,
    "move_lecture": _run_move_lecture,
    "replan": _run_replan,
}


def _kinds_for(lab: dict, sessions: list[dict]) -> list[str]:
    """วิธีที่ใช้ได้กับ LAB นี้ เรียงตามลำดับที่ลอง (กระทบน้อยก่อน)"""
    if _pair_for(lab, sessions):
        return ["move_pair", "move_lecture", "replan"]
    if _can_touch(lab):
        return ["move", "swap_lec_lab", "move_lecture", "replan"]
    return []


# ───────────────────────── 1. วิเคราะห์ (ให้ Agent อ่าน) ─────────────────────────

def review_soft_issues() -> dict:
    """ลองแต่ละวิธีแบบไม่บันทึก คืนตัวเลือกที่ผ่านเกณฑ์
    คืน {"issues": [...], "_option_map": {...}} — _option_map เก็บใน state ไม่ส่งให้ LLM
    """
    sessions = build_session_list()
    by_id = {s["session_id"]: s for s in sessions}
    hard0, soft0 = _issue_counts()
    all_soft = [i for i in find_issues() if i.get("type") in SOFT_TYPES]
    issues, option_map, done, trials = [], {}, set(), 0

    for issue in all_soft:
        if len(issues) >= MAX_SOFT_ISSUES_TO_REVIEW:
            break
        lab = by_id.get(issue.get("session_id"))
        if not lab or lab["session_id"] in done:
            continue
        pair = _pair_for(lab, sessions)
        lab = pair[0] if pair else lab
        done.update(p["session_id"] for p in (pair or [lab]))   # LAB คู่โผล่ 2 รายการ ดูครั้งเดียวพอ

        base = {"subject": _name(lab), "problem": TYPE_LABEL[issue["type"]]}
        kinds = _kinds_for(lab, sessions)
        if not kinds:
            issues.append({**base, "verdict": "needs_manual",
                           "why": "LAB แบ่ง 3 section ขึ้นไป/เรียนรวด ระบบย้ายเองไม่ได้ ให้ผู้ใช้ลากวางเอง"})
            continue

        # soft issue ทั้งหมดของวิชานี้ — วิธีที่แก้ได้ครบทุกจุดถือว่าดีที่สุด หยุดหาได้เลย
        subject_soft = sum(1 for i in all_soft
                           if (by_id.get(i.get("session_id")) or {}).get("subject_id") == lab["subject_id"])
        best = None                    # (soft ที่ลดลง, kind, res) — ลองตามลำดับ เก็บตัวที่ลดได้มากที่สุด
        for kind in kinds:
            if trials >= MAX_TRIALS:
                break
            trials += 1
            before = snapshot_rows()
            try:
                res = METHODS[kind](lab, sessions, {})
                if not res or _same_day_violation(res["touched"]):
                    continue
                hard1, soft1 = _issue_counts()
                if hard1 > hard0 or soft1 >= soft0:
                    continue
            finally:
                restore_rows(before)
            if not best or soft0 - soft1 > best[0]:
                best = (soft0 - soft1, kind, res)
            if best[0] >= subject_soft:
                break                  # แก้ครบทุกจุดของวิชานี้แล้ว ไม่ต้องลองวิธีที่กระทบมากกว่า

        option = None
        if best:
            gained, kind, res = best
            oid = f"S{len(option_map) + 1}"
            option_map[oid] = {"kind": kind, "session_id": lab["session_id"], "prefer": res["prefer"]}
            done.update(res["touched"])   # LAB อื่นที่วิธีนี้แก้ไปด้วย (เช่น LECTURE เรียนรวม) ไม่ต้องดูซ้ำ
            option = {"option_id": oid, "advice": res["advice"],
                      "impact": f"ไม่กระทบวิชาอื่น, soft issue ลดลง {gained} จุด"}

        if option:
            issues.append({**base, "verdict": "can_improve", "options": [option]})
        else:
            issues.append({**base, "verdict": "keep",
                           "why": f"ลองแล้ว: {' / '.join(KIND_LABEL[k] for k in kinds)} — ไม่มีทางไหนผ่านกฎ"})

    print(f"[soft] ตรวจ {len(issues)} จุด, ลองแบบไม่บันทึก {trials} ครั้ง, "
          f"มีทางแก้ {sum(1 for i in issues if i['verdict'] == 'can_improve')} จุด"
          f" (วิธีที่เจอ: {', '.join(e['kind'] for e in option_map.values()) or '-'})")
    return {"soft_issue_count": soft0, "reviewed": len(issues), "issues": issues, "_option_map": option_map}


# ───────────────────────── 2. ลงมือแก้ ─────────────────────────

def apply_soft_fixes(fixes: list[dict], previous_failed: list[dict]) -> dict:
    """ทำตามตัวเลือกที่ Agent เลือก ทีละจุด ตรวจซ้ำทุกจุด ไม่ดีขึ้นก็คืนกลับ
    คืนผลหน้าตาเดียวกับ auto_assign_all() + "moves"
    """
    sessions = build_session_list()
    by_id = {s["session_id"]: s for s in sessions}
    log = []

    for fx in fixes:
        kind, sid = fx.get("kind"), fx.get("session_id")
        lab, run = by_id.get(sid), METHODS.get(kind)
        hard0, soft0 = _issue_counts()
        before = snapshot_rows()

        res = run(lab, sessions, fx.get("prefer") or {}) if lab and run else None
        error = None if res else "ทำไม่ได้แล้ว (ตารางเปลี่ยนไปจากตอนที่ลอง)"
        if not error:
            hard1, soft1 = _issue_counts()
            if _same_day_violation(res["touched"]):
                error = "LAB ไปอยู่วันเดียวกับ LECTURE"
            elif hard1 > hard0:
                error = "ทำให้เกิดปัญหาชนกันใหม่"
            elif soft1 >= soft0:
                error = "แก้แล้วไม่ดีขึ้น"

        entry = {"kind": kind, "session_id": sid, "success": not error}
        if error:
            restore_rows(before)
            entry["reason"] = error
        log.append(entry)
        print(f"[soft] ลงมือแก้ {kind} ({sid}): {'สำเร็จ' if not error else 'ไม่สำเร็จ — ' + error}")

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