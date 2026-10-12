"""
repair_unplaced.py — ซ่อมเฉพาะวิชาที่จัดไม่ได้ หลังจัดตารางรอบแรก (ข้อ 7 ในแผนภาพ)

Python ล้วน ไม่ใช้ LLM ไม่ใช้ token — ถูกเรียกจาก auto_assign_all() ตอนรอบแรกยังมีวิชาตก
(คนละตัวกับ retry_failed_sessions() ใน auto_assign.py ที่ซ่อมตามตัวเลือกที่ CheckerAgent เลือก)

ไม่ล้างตารางแล้วสุ่มใหม่ทั้งหมด คงวิชาที่จัดได้แล้วไว้ แตะเฉพาะวิชาที่ตกกับวิชาที่ขวางมันอยู่:
  1) ลองวางวิชาที่ตกตรงๆ ในช่องที่ยังว่าง
  2) ไม่ได้ -> หาคาบที่ติดแค่ 1-2 วิชาที่ย้ายได้ ถอดวิชาพวกนั้นออก วางวิชาที่ตกลงไป
     แล้วหาที่ใหม่ให้วิชาที่ถูกถอด (ห้ามกลับไปคาบเดิม ผ่าน retry_hints.forbidden)
  3) วิชาที่ถูกถอดหาที่ไม่ได้ -> ยอมให้มันถอดวิชาอื่นต่อได้อีก EJECT_DEPTH ทอด
  รับผลก็ต่อเมื่อ วิชาที่ตกลดลง + hard issue ไม่เพิ่ม + ไม่มีวิชาที่จัดได้แล้วหลุดออก
  ไม่งั้นคืนตารางเหมือนก่อนลอง
"""

import time

from .load_data import get_cached_data
from .section_logic import build_session_list
from .assignment_store import get_current_schedule_raw, move_session, delete_session_assignment
from .find_issues import find_issues
from .retry_hints import set_active, clear_active
from .failure_analysis import snapshot_rows, restore_rows
from .auto_assign import can_retry_session, _unplaced_sessions, _days_of_sessions
from .data_check import impossible_sessions

# ── ตั้งค่า ──
# REPAIR_ROUNDS: ซ่อมเฉพาะจุดได้กี่รอบ (1 รอบ = ไล่ทุกวิชาที่ตก 1 ครั้ง) หยุดเองเมื่อรอบไหนไม่ดีขึ้น
# MAX_BLOCKER_TRIES: ต่อ 1 วิชาที่ตก ลองถอดวิชาที่ขวางได้กี่แบบ (แต่ละแบบต้องเขียน/คืน DB จริง)
# MAX_EJECT: ยอมถอดวิชาที่ขวางพร้อมกันได้สูงสุดกี่วิชาต่อ 1 คาบ (2 = รองรับ LAB คู่ section ที่ขวางอยู่ด้วยกัน)
REPAIR_ROUNDS = 3
MAX_BLOCKER_TRIES = 4
MAX_EJECT = 2
# EJECT_DEPTH: วิชาที่ถูกถอดหาที่ใหม่ไม่ได้ ยอมให้ถอดวิชาอื่นต่อได้อีกกี่ทอด (1 = ถอดแค่ชั้นเดียว)
# MAX_CHAIN_STEPS: ต่อ 1 วิชาที่ตก ลองถอดได้รวมกี่ครั้งทั้งสาย (กันช้า — แต่ละครั้งเขียน/คืน DB จริง)
EJECT_DEPTH = 2
MAX_CHAIN_STEPS = 12
# REPAIR_TIME_LIMIT: เวลาสูงสุด (วินาที) ที่ยอมใช้ซ่อม ครบแล้วหยุด เก็บเท่าที่ซ่อมได้
# (กับ Supabase จริง 1 ครั้งที่ย้าย/คืนตาราง ~1 วินาที วิชาตก 2-5 วิชามักเสร็จใน 1-3 นาที)
REPAIR_TIME_LIMIT = 180
_deadline = [float("inf")]


# ─────────────────────────────────────────────────────────────────────────
# ซ่อมเฉพาะวิชาที่ตก (ไม่ล้างตาราง) — Python ล้วน ไม่ใช้ token
#
# ต่อ 1 วิชาที่ตก:
#   ก) ลองวางตรงๆ ในช่องที่ยังว่าง
#   ข) ไม่ได้ -> หาคาบที่ "ติดแค่ 1-2 วิชาที่ย้ายได้" และถ้าถอดวิชาพวกนั้นออก วิชาที่ตก
#      จะผ่านกฎ hard ครบ -> ถอดวิชาที่ขวาง, วางวิชาที่ตก, หาที่ใหม่ให้วิชาที่ขวาง
#      (ห้ามวิชาที่ขวางกลับไปคาบเดิม ผ่าน retry_hints.forbidden)
#   รับผลก็ต่อเมื่อ "วิชาที่ตกลดลง และ hard issue ไม่เพิ่ม" ไม่งั้นคืนตารางเหมือนก่อนลอง
# ─────────────────────────────────────────────────────────────────────────

def _table_state() -> tuple[int, int, int]:
    """(วิชาที่ยังไม่อยู่ในตาราง, hard issue, soft issue) — ยิ่งน้อยยิ่งดี"""
    issues = find_issues()
    return (
        len(_unplaced_sessions([])),
        sum(1 for i in issues if i.get("severity") == "hard"),
        sum(1 for i in issues if i.get("severity") == "soft"),
    )


def _slots_by_session() -> dict[str, frozenset]:
    """session_id -> ชุดคาบทั้งหมดที่วางอยู่ (ใช้เทียบว่าวิชาไหนถูกย้าย/หลุด)"""
    out: dict[str, set] = {}
    for a in get_current_schedule_raw():
        if a.get("session_id"):
            out.setdefault(a["session_id"], set()).add(str(a["timeslot_id"]))
    return {k: frozenset(v) for k, v in out.items()}


def _is_better(new: tuple, base: tuple) -> bool:
    return new[0] < base[0] and new[1] <= base[1]


def _lecture_days_for(session: dict, sessions: list[dict]) -> set[str] | None:
    """วัน LECTURE ทั้งหมดของวิชาเดียวกับ LAB นี้ (วิธีเดียวกับ move_session) — None ถ้าไม่ใช่ LAB"""
    if session.get("session_type") != "LAB":
        return None
    my_groups = set(session.get("group_ids") or [])
    lecture_ids = {
        s["session_id"] for s in sessions
        if s["session_type"] == "LECTURE"
        and (s["subject_selected_id"] == session["subject_selected_id"]
             or (s["subject_id"] == session["subject_id"] and my_groups & set(s.get("group_ids") or [])))
    }
    return _days_of_sessions(lecture_ids) or None


def _blocker_options(session: dict, sessions_by_id: dict) -> list[dict]:
    """หาคาบที่ถอดวิชาที่ขวาง (ไม่เกิน MAX_EJECT วิชา) ออกแล้ว session นี้ลงได้ทันที
    คืน [{"blockers": [session_id...], "timeslot_ids": [...]}] เรียงจากถอดน้อยวิชาก่อน
    """
    from .slot_filter import _build_blocks
    from .candidate_scorer import passes_hard_rules

    data = get_cached_data()
    groups_map = {g["group_id"]: g["total_students"] for g in data["groups"]}
    teacher_ids = set(session.get("teacher_ids") or [])
    group_ids = set(session.get("group_ids") or [])
    students = session.get("max_capacity") or sum(groups_map.get(g, 0) for g in group_ids)

    if session.get("fixed_room_id"):
        rooms = [r for r in data["rooms"] if r["room_id"] == session["fixed_room_id"]]
    else:
        rooms = [r for r in data["rooms"] if r["room_type"] == session["room_type"] and r["capacity"] >= students]
    if not rooms:
        return []

    teacher_unavail = {str(r["timeslot_id"]) for r in data["teacher_unavailability"] if r["teacher_id"] in teacher_ids}
    room_unavail: dict[str, set] = {}
    for r in data["room_unavailability"]:
        room_unavail.setdefault(r["room_id"], set()).add(str(r["timeslot_id"]))

    rows_at: dict[str, list] = {}
    for a in data["existing"] + data["assignments"]:
        rows_at.setdefault(str(a["timeslot_id"]), []).append(a)

    lecture_days = _lecture_days_for(session, list(sessions_by_id.values()))
    sibling_key = session.get("sibling_key")
    timeslot_day = {str(t["timeslot_id"]): t["day"] for t in data["timeslots"]}
    sibling_days = {
        timeslot_day.get(str(a["timeslot_id"])) for a in data["assignments"]
        if a.get("session_id") != session["session_id"]
        and sibling_key and (sessions_by_id.get(a.get("session_id")) or {}).get("sibling_key") == sibling_key
    }

    options = []
    for block in _build_blocks(data["timeslots"]):
        ts_ids = block["timeslot_ids"]
        if block["day"] in sibling_days:
            continue                                   # block อื่นของวิชาเดียวกันอยู่วันนี้แล้ว
        if teacher_ids and any(t in teacher_unavail for t in ts_ids):
            continue                                   # ติดข้อมูล ถอดใครก็ไม่ช่วย
        usable = [r for r in rooms if not any(t in room_unavail.get(r["room_id"], set()) for t in ts_ids)]
        if not usable:
            continue

        rows = [a for t in ts_ids for a in rows_at.get(t, [])]
        locked, blockers = False, set()
        for x in rows:
            hit = (teacher_ids and x.get("teacher_id") in teacher_ids) or (group_ids and x.get("group_id") in group_ids)
            if hit:
                if x.get("session_id"):
                    blockers.add(x["session_id"])
                else:
                    locked = True                      # วิชา GENERAL ที่ล็อกไว้ ถอดไม่ได้
        if locked:
            continue

        # ห้อง: ถ้าไม่เหลือห้องว่างเลย ต้องถอดคนที่ใช้ห้องใดห้องหนึ่งออก (เลือกห้องที่ถอดน้อยสุด)
        room_users = {r["room_id"]: {x["session_id"] for x in rows if x.get("room_id") == r["room_id"] and x.get("session_id")}
                      for r in usable}
        if all(room_users[r["room_id"]] - blockers for r in usable):
            best_room = min(usable, key=lambda r: len(room_users[r["room_id"]] - blockers))
            blockers |= room_users[best_room["room_id"]]

        if not blockers or len(blockers) > MAX_EJECT:
            continue                                   # คาบว่างอยู่แล้ว (ติดกฎอื่น) หรือต้องถอดเยอะเกิน
        if not all(can_retry_session(sessions_by_id.get(b)) for b in blockers):
            continue

        # จำลอง: ถอด blockers ออกแล้ว session นี้ผ่านกฎ hard ครบไหม (เช็คก่อนแตะ DB จริง)
        remaining = [a for a in data["assignments"] if a.get("session_id") not in blockers]
        if not passes_hard_rules(session, ts_ids, remaining, lecture_days):
            continue
        options.append({"blockers": sorted(blockers), "timeslot_ids": ts_ids})

    options.sort(key=lambda o: len(o["blockers"]))
    return options[:MAX_BLOCKER_TRIES]


def _place_chain(target_id: str, sessions_by_id: dict, depth: int, protected: set,
                 forbidden: dict, budget: list) -> bool:
    """วาง target ให้ได้ โดยถอดวิชาที่ขวางได้ และวิชาที่ถูกถอดก็ถอดคนอื่นต่อได้อีก depth ทอด
    - protected: วิชาที่เพิ่งวางในสายนี้ ห้ามถูกถอดซ้ำ (กันวนไปมา)
    - forbidden: {session_id: คาบ} วิชาที่ถูกถอด ห้ามกลับไปคาบเดิม
    - budget: [จำนวนครั้งที่ยังลองได้] ใช้ร่วมกันทั้งสาย กันช้า
    ทุกทางที่ลองแล้วไม่สำเร็จ คืนตารางกลับก่อนลองทางถัดไป (คืน False = ตารางเหมือนตอนเรียก)
    """
    if target_id in {a.get("session_id") for a in get_current_schedule_raw()}:
        return True                                    # ถูกวางไปแล้วพร้อมคู่ section
    set_active({"forbidden": forbidden})
    try:
        if move_session(target_id).get("success"):
            return True
    finally:
        clear_active()
    if depth <= 0 or budget[0] <= 0 or time.time() > _deadline[0]:
        return False

    session = sessions_by_id[target_id]
    for opt in _blocker_options(session, sessions_by_id):
        if budget[0] <= 0 or time.time() > _deadline[0]:
            return False
        if protected & set(opt["blockers"]):
            continue
        budget[0] -= 1
        snap = snapshot_rows()
        new_forbidden = {**forbidden}
        for b in opt["blockers"]:
            new_forbidden[b] = list(set(new_forbidden.get(b, [])) | set(opt["timeslot_ids"]))
            delete_session_assignment(b)

        set_active({"forbidden": new_forbidden})
        try:
            placed = move_session(target_id).get("success")
        finally:
            clear_active()

        ok = placed and all(
            _place_chain(b, sessions_by_id, depth - 1, protected | {target_id}, new_forbidden, budget)
            for b in opt["blockers"]
        )
        if ok:
            return True
        restore_rows(snap)
    return False


def repair_unplaced(first: dict) -> dict:
    """ซ่อมเฉพาะวิชาที่ตกจากรอบแรก คืนผลหน้าตาเดียวกับ _full_run() + "repair_log" """
    sessions_by_id = {s["session_id"]: s for s in build_session_list()}
    skip = impossible_sessions()          # จัดไม่ได้แน่ (ติดข้อมูล) — ไม่ต้องเสียเวลาซ่อม
    before_repair = _slots_by_session()
    log: list[dict] = []
    state = _table_state()
    _deadline[0] = time.time() + REPAIR_TIME_LIMIT

    for rnd in range(1, REPAIR_ROUNDS + 1):
        progress = False
        for f in _unplaced_sessions(first["failed"]):
            sid = f["session_id"]
            if time.time() > _deadline[0]:
                break
            if sid in {a.get("session_id") for a in get_current_schedule_raw()}:
                continue                               # ถูกวางไปแล้วพร้อมคู่ของมัน
            if sid in skip or not can_retry_session(sessions_by_id.get(sid)):
                continue

            # วางตรงๆ ก่อน ไม่ได้ค่อยถอดวิชาที่ขวาง (ต่อได้สูงสุด EJECT_DEPTH ทอด)
            snap = snapshot_rows()
            placed_before = _slots_by_session()
            ok = _place_chain(sid, sessions_by_id, EJECT_DEPTH, set(), {}, [MAX_CHAIN_STEPS])
            now = _slots_by_session() if ok else {}
            # ห้ามมีวิชาที่เคยจัดได้แล้วหลุดออกจากตาราง แม้ยอดรวมจะดีขึ้นก็ตาม
            kept_all = ok and all(s in now for s in placed_before)
            new = _table_state() if kept_all else None
            if kept_all and _is_better(new, state):
                state, progress = new, True
                shifted = sorted(s for s in placed_before if now[s] != placed_before[s])
                log.append({"round": rnd, "session_id": sid, "moved": shifted})
            elif ok:
                restore_rows(snap)   # วางได้แต่ทำให้ hard issue เพิ่ม -> คืนค่า (ถ้าไม่ได้ _place_chain คืนให้แล้ว)
        print(f"[repair] รอบ {rnd}: ยังตก {state[0]} | hard {state[1]} | soft {state[2]}")
        if not progress or state[0] == 0 or time.time() > _deadline[0]:
            break
    _deadline[0] = float("inf")

    after = _slots_by_session()
    moved = sorted(s for s in before_repair if s in after and after[s] != before_repair[s])
    failed = _unplaced_sessions(first["failed"])
    return {
        **first,
        "assigned_count": len(after),
        "failed_count": len(failed),
        "failed": failed,
        "converged": state[1] == 0,
        "remaining_hard_issue_count": state[1],
        "remaining_soft_issue_count": state[2],
        "repair_log": log,
        "repair_moved_sessions": moved,   # วิชาที่เคยจัดได้แล้ว แต่ถูกย้ายระหว่างซ่อม
    }