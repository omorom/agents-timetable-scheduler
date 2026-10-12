"""
check_schedule.py — ตรวจตารางที่จัดเสร็จแล้วใน Supabase ว่า "ถูกต้องจริงไหม" (อ่านอย่างเดียว ไม่แก้ข้อมูล)

ใช้หลังกด "สร้างตาราง" บนหน้าเว็บ (หรือหลังลากย้าย/วางวิชาเอง) เพื่อตอบคำถามว่า ระบบโอเคยัง
ตรวจแยกจาก find_issues() ของระบบ (เขียนการตรวจใหม่เอง) จะได้จับได้ถ้าตัวตรวจของระบบเองพลาด

หมวดที่ตรวจ:
  1. ความครบ        วิชา/session ที่ควรมีแต่ไม่อยู่ในตาราง
  2. ชนกัน          ห้อง / อาจารย์ / กลุ่มนิสิต อยู่ 2 ที่ในคาบเดียวกัน (รวมวิชาศึกษาทั่วไปที่ล็อกไว้)
  3. เวลาไม่ว่าง      วางทับคาบที่ตั้งว่าอาจารย์/ห้องไม่ว่าง
  4. ห้อง           ประเภทห้องถูก, จุนิสิตพอ, ห้องที่ล็อกไว้ (fixed_room_id)
  5. ความยาวคาบ      ชั่วโมงครบ, วิชาเรียนรวดต่อเนื่องจริง
  6. กฎตาราง        LAB ห้ามวันเดียวกับ LECTURE, นิสิตเรียนไม่เกิน 3 วิชา/วัน, อาจารย์สอนรวดไม่เกิน 3 คาบ
  7. วิชาที่ต้องเรียนพร้อมกัน (SYNC_LECTURE_GROUPS) เวลาเดียวกัน คนละห้อง ในช่วงเวลาที่กำหนด
  8. คุณภาพ (ไม่ถือว่าผิด)  LAB อยู่ก่อน LECTURE, LAB 2 section ของอาจารย์คนเดียวกันเรียนไม่ต่อกัน

วิธีรัน (จาก root โปรเจกต์):
    python check_schedule.py              # ตรวจตารางปัจจุบัน
    python check_schedule.py --details    # แสดงทุกรายการ (ปกติแสดงหมวดละ 5 รายการ)

exit code: 0 = ไม่มีข้อผิด (❌), 1 = มีข้อผิด
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

# ── ฟังก์ชันตรวจ (เรียกจากเทสต์ได้โดยไม่ต้องต่อ Supabase) ──────────────────────

OK, WARN, FAIL = "✅", "⚠️ ", "❌"
MAX_SUBJECTS_PER_DAY = 3
MAX_TEACHER_STREAK = 3


def run_checks() -> list[dict]:
    """คืน list ของหมวด: {"title", "level": OK/WARN/FAIL, "items": [ข้อความ...], "note"}"""
    from agent_timetable.tools.scheduling.load_data import get_cached_data
    from agent_timetable.tools.scheduling.section_logic import build_session_list
    from agent_timetable.tools.scheduling.candidate_scorer import (
        _build_day_order, _build_block_order, DAY_SEQUENCE, FULL_DAY_EXEMPT_SUBJECT_TYPES,
    )
    from agent_timetable.tools.scheduling import auto_assign

    data = get_cached_data()
    rows = data["assignments"]
    locked = data["existing"]
    sessions = {s["session_id"]: s for s in build_session_list()}
    ts_by_id = {str(t["timeslot_id"]): t for t in data["timeslots"]}
    rooms = {r["room_id"]: r for r in data["rooms"]}
    groups_size = {g["group_id"]: g["total_students"] for g in data["groups"]}
    subj = {s["subject_id"]: s for s in data["subjects"]}
    day_order = _build_day_order(data["timeslots"])
    block_order = _build_block_order(data["timeslots"])
    rank = {d: i for i, d in enumerate(DAY_SEQUENCE)}

    def name(subject_id):
        s = subj.get(subject_id, {})
        return f"{subject_id} {s.get('name_thai') or s.get('name_english') or ''}".strip()

    def label(sid):
        s = sessions.get(sid, {})
        sec = f" sec {s['section']}" if s.get("section") else ""
        return f"{name(s.get('subject_id'))} [{s.get('session_type', '?')}{sec}] ({','.join(s.get('group_ids') or [])})"

    def when(ts_ids):
        rs = sorted((ts_by_id[t] for t in ts_ids if t in ts_by_id), key=lambda t: (rank.get(t["day"], 9), t["start_time"]))
        return f"{rs[0]['day']} {str(rs[0]['start_time'])[:5]}-{str(rs[-1]['end_time'])[:5]}" if rs else "-"

    # รวมแถวดิบเป็นต่อ session
    placed: dict[str, dict] = {}
    for r in rows:
        sid = r.get("session_id")
        if not sid:
            continue
        p = placed.setdefault(sid, {"ts": set(), "rooms": set(), "teachers": set(), "groups": set(),
                                    "subject_id": r.get("subject_id"), "type": r.get("session_type")})
        p["ts"].add(str(r["timeslot_id"]))
        if r.get("room_id"):
            p["rooms"].add(r["room_id"])
        if r.get("teacher_id"):
            p["teachers"].add(r["teacher_id"])
        if r.get("group_id"):
            p["groups"].add(r["group_id"])
    days_of = {sid: {day_order[t][0] for t in p["ts"] if t in day_order} for sid, p in placed.items()}

    results = []

    def add(title, items, level_if_any, note=""):
        results.append({"title": title, "level": level_if_any if items else OK, "items": items, "note": note})

    # 1) ความครบ
    missing = [label(sid) for sid in sessions if sid not in placed]
    unknown = [sid for sid in placed if sid not in sessions]
    add("1. ความครบ: วิชาที่ยังไม่อยู่ในตาราง", missing, WARN,
        f"จัดแล้ว {len(set(placed) & set(sessions))}/{len(sessions)} session")
    if unknown:
        add("1b. session ในตารางที่ไม่ตรงกับวิชาที่เปิดสอน (ข้อมูลเก่าค้าง)", unknown, WARN)

    # 2) ชนกัน
    by_slot: dict[str, dict[str, set]] = defaultdict(lambda: {"room": defaultdict(set), "teacher": defaultdict(set),
                                                               "group": defaultdict(set)})
    for sid, p in placed.items():
        for t in p["ts"]:
            for room in p["rooms"]:
                by_slot[t]["room"][room].add(sid)
            for te in p["teachers"]:
                by_slot[t]["teacher"][te].add(sid)
            for g in p["groups"]:
                by_slot[t]["group"][g].add(sid)
    def parallel_sections(sids) -> bool:
        """วิชาเดียวกัน ประเภทเดียวกัน กลุ่มเดียวกัน แต่คนละ section (แบ่งนิสิตเป็นส่วนๆ คนละอาจารย์)
        เรียนเวลาเดียวกันคนละห้อง = ตั้งใจออกแบบไว้ (นิสิตแต่ละคนเข้าแค่ section เดียว) ไม่ใช่นิสิตชนกัน"""
        ss = [sessions.get(x) or {} for x in sids]
        if not all(x.get("section") for x in ss):
            return False
        if len({(x.get("subject_id"), x.get("session_type"), tuple(sorted(x.get("group_ids") or []))) for x in ss}) != 1:
            return False
        if len({x["section"] for x in ss}) != len(ss):
            return False
        used_rooms = [r for x in sids for r in placed[x]["rooms"]]
        return len(used_rooms) == len(set(used_rooms))

    clashes = set()
    for t, kinds in by_slot.items():
        for kind, mp in kinds.items():
            for who, sids in mp.items():
                if len(sids) > 1 and not (kind == "group" and parallel_sections(sids)):
                    clashes.add(f"{kind} {who} @ {when([t])}: " + " / ".join(sorted(label(s) for s in sids)))
    locked_groups = defaultdict(set)
    for e in locked:
        if e.get("group_id"):
            locked_groups[(str(e["timeslot_id"]), e["group_id"])].add(e.get("subject_id"))
    for sid, p in placed.items():
        for t in p["ts"]:
            for g in p["groups"]:
                if (t, g) in locked_groups:
                    clashes.add(f"group {g} @ {when([t])}: {label(sid)} ทับวิชาที่ล็อกไว้ "
                                f"{', '.join(name(x) for x in locked_groups[(t, g)])}")
    add("2. ชนกัน (ห้อง/อาจารย์/นิสิต)", sorted(clashes), FAIL)

    # 3) เวลาไม่ว่าง
    t_un = {(u["teacher_id"], str(u["timeslot_id"])) for u in data["teacher_unavailability"]}
    r_un = {(u["room_id"], str(u["timeslot_id"])) for u in data["room_unavailability"]}
    bad_un = []
    for sid, p in placed.items():
        for t in sorted(p["ts"]):
            bad_un += [f"อาจารย์ {te} ตั้งไม่ว่าง แต่มี {label(sid)} @ {when([t])}" for te in p["teachers"] if (te, t) in t_un]
            bad_un += [f"ห้อง {r} ตั้งไม่ว่าง แต่มี {label(sid)} @ {when([t])}" for r in p["rooms"] if (r, t) in r_un]
    add("3. วางทับเวลาที่ตั้งว่าไม่ว่าง", bad_un, FAIL)

    # 4) ห้อง
    bad_room = []
    for sid, p in placed.items():
        s = sessions.get(sid)
        if not s:
            continue
        if len(p["rooms"]) != 1:
            bad_room.append(f"{label(sid)} ใช้ {len(p['rooms'])} ห้อง: {sorted(p['rooms'])}")
            continue
        room = rooms.get(next(iter(p["rooms"])))
        if not room:
            bad_room.append(f"{label(sid)} อยู่ห้องที่ไม่มีในระบบ: {p['rooms']}")
            continue
        students = s.get("max_capacity") or sum(groups_size.get(g, 0) for g in s.get("group_ids") or [])
        if s.get("fixed_room_id") and room["room_id"] != s["fixed_room_id"]:
            bad_room.append(f"{label(sid)} ล็อกห้อง {s['fixed_room_id']} แต่อยู่ {room['room_id']}")
        elif not s.get("fixed_room_id") and room["room_type"] != s["room_type"]:
            bad_room.append(f"{label(sid)} ต้องใช้ห้อง {s['room_type']} แต่อยู่ {room['room_id']} ({room['room_type']})")
        if room["capacity"] < students:
            bad_room.append(f"{label(sid)} มี {students} คน แต่ห้อง {room['room_id']} จุ {room['capacity']}")
    add("4. ห้อง (ประเภท/ความจุ/ห้องที่ล็อก)", bad_room, FAIL)

    # 5) ความยาวคาบ
    bad_len = []
    for sid, p in placed.items():
        s = sessions.get(sid)
        if not s:
            continue
        need = s.get("continuous_size") or 2
        if len(p["ts"]) != need:
            bad_len.append(f"{label(sid)} ต้องเรียน {need} ชม. แต่ได้ {len(p['ts'])} ชม. ({when(p['ts'])})")
            continue
        rs = sorted((ts_by_id[t] for t in p["ts"]), key=lambda t: t["start_time"])
        if len({t["day"] for t in rs}) > 1 or any(rs[i]["end_time"] != rs[i + 1]["start_time"] for i in range(len(rs) - 1)):
            bad_len.append(f"{label(sid)} คาบไม่ต่อเนื่อง ({when(p['ts'])})")
    add("5. ความยาวคาบ / เรียนรวดต่อเนื่อง", bad_len, FAIL)

    # 6) กฎตาราง
    bad_rule = []
    # 6a LAB ห้ามวันเดียวกับ LECTURE (วิชาเดียวกัน กลุ่มนิสิตทับกัน)
    lec_days = defaultdict(set)
    for sid, p in placed.items():
        if p["type"] == "LECTURE":
            for g in p["groups"]:
                lec_days[(p["subject_id"], g)] |= days_of[sid]
    for sid, p in placed.items():
        if p["type"] == "LAB":
            same = {d for g in p["groups"] for d in lec_days[(p["subject_id"], g)]} & days_of[sid]
            if same:
                bad_rule.append(f"LAB วันเดียวกับ LECTURE: {label(sid)} วัน {', '.join(sorted(same))}")
    # 6b นิสิตเรียนไม่เกิน 3 วิชา/วัน (ไม่นับวิชาเลือก)
    per_day = defaultdict(set)
    for sid, p in placed.items():
        if subj.get(p["subject_id"], {}).get("subject_type") in FULL_DAY_EXEMPT_SUBJECT_TYPES:
            continue
        for g in p["groups"]:
            for d in days_of[sid]:
                per_day[(g, d)].add(p["subject_id"])
    for (g, d), subs in sorted(per_day.items()):
        if len(subs) > MAX_SUBJECTS_PER_DAY:
            bad_rule.append(f"กลุ่ม {g} วัน {d} เรียน {len(subs)} วิชา: {', '.join(sorted(subs))}")
    # 6c อาจารย์สอนรวดไม่เกิน 3 คาบ (นับเป็น block)
    t_blocks = defaultdict(set)
    for r in rows:
        if r.get("teacher_id") and str(r["timeslot_id"]) in block_order:
            t_blocks[r["teacher_id"]].add(block_order[str(r["timeslot_id"])])
    for te, blocks in t_blocks.items():
        for d in DAY_SEQUENCE:
            idx = sorted(i for (day, i) in blocks if day == d)
            streak = best = 1 if idx else 0
            for a, b in zip(idx, idx[1:]):
                streak = streak + 1 if b == a + 1 else 1
                best = max(best, streak)
            if best > MAX_TEACHER_STREAK:
                bad_rule.append(f"อาจารย์ {te} สอนรวด {best} คาบ วัน {d}")
    add("6. กฎตาราง (LAB/LECTURE, เกิน 3 วิชา/วัน, สอนรวด)", bad_rule, FAIL)

    # 7) วิชาที่ต้องเรียนพร้อมกัน
    sync_groups = getattr(auto_assign, "SYNC_LECTURE_GROUPS", [])
    windows = getattr(auto_assign, "SYNC_TIME_WINDOWS", None)
    old_window = getattr(auto_assign, "SYNC_TIME_WINDOW", None)
    bad_sync = []
    for grp in sync_groups:
        window = windows.get(tuple(grp)) if windows is not None else old_window
        lecs = [sid for sid, p in placed.items() if p["type"] == "LECTURE" and p["subject_id"] in grp]
        if len(grp) == 1:
            units = defaultdict(list)
            for sid in lecs:
                units[tuple(sorted(placed[sid]["groups"]))].append(sid)
        else:
            units = defaultdict(list)
            for sid in lecs:
                units[placed[sid]["subject_id"]].append(sid)
        if len(units) < 2:
            continue
        lists = [sorted(v, key=lambda s: sorted(placed[s]["ts"])) for _, v in sorted(units.items())]
        for i in range(min(len(x) for x in lists)):
            block = [x[i] for x in lists]
            times = {frozenset(placed[s]["ts"]) for s in block}
            rooms_used = [next(iter(placed[s]["rooms"]), None) for s in block]
            if len(times) > 1:
                bad_sync.append("ไม่ตรงเวลากัน: " + " / ".join(f"{label(s)} {when(placed[s]['ts'])}" for s in block))
            elif len(set(rooms_used)) < len(rooms_used):
                bad_sync.append("ห้องเดียวกัน: " + " / ".join(label(s) for s in block))
            if window:
                lo, hi = window
                for s in block:
                    rs = [ts_by_id[t] for t in placed[s]["ts"]]
                    if min(str(t["start_time"])[:5] for t in rs) < lo or max(str(t["end_time"])[:5] for t in rs) > hi:
                        bad_sync.append(f"นอกช่วง {lo}-{hi}: {label(s)} {when(placed[s]['ts'])}")
    add("7. วิชาที่ต้องเรียนพร้อมกัน (SYNC)", bad_sync, FAIL,
        f"{len(sync_groups)} กลุ่มที่ตั้งไว้: {', '.join('/'.join(g) for g in sync_groups)}")

    # 8) คุณภาพ (ไม่ผิดกฎ)
    soft = []
    for sid, p in placed.items():
        if p["type"] != "LAB":
            continue
        ld = {d for g in p["groups"] for d in lec_days[(p["subject_id"], g)]}
        if ld and days_of[sid] and max(rank[d] for d in days_of[sid]) <= max(rank[d] for d in ld):
            soft.append(f"LAB อยู่ก่อน LECTURE: {label(sid)} LAB {', '.join(sorted(days_of[sid]))} / "
                        f"LECTURE {', '.join(sorted(ld))}")
    pairs = defaultdict(list)
    for sid, s in sessions.items():
        if s["session_type"] == "LAB" and s.get("section") and sid in placed:
            pairs[(s["subject_id"], tuple(sorted(s["group_ids"] or [])), sid.split("-B")[-1] if "-B" in sid else "")].append(sid)
    for key, sids in pairs.items():
        if len(sids) != 2:
            continue
        a, b = sids
        same_teacher = bool(placed[a]["teachers"] & placed[b]["teachers"])
        ta, tb = sorted(placed[a]["ts"]), sorted(placed[b]["ts"])
        if same_teacher:
            ra = sorted((ts_by_id[t] for t in ta), key=lambda t: t["start_time"])
            rb = sorted((ts_by_id[t] for t in tb), key=lambda t: t["start_time"])
            touching = ra[0]["day"] == rb[0]["day"] and (ra[-1]["end_time"] == rb[0]["start_time"] or rb[-1]["end_time"] == ra[0]["start_time"])
            if not touching:
                soft.append(f"LAB 2 section อาจารย์คนเดียวกันไม่ได้เรียนต่อกัน: {label(a)} {when(ta)} / {when(tb)}")
        elif ta != tb:
            soft.append(f"LAB 2 section คนละอาจารย์ไม่ได้เรียนเวลาเดียวกัน: {label(a)} {when(ta)} / {when(tb)}")
    add("8. คุณภาพตาราง (ไม่ผิดกฎ แต่ควรดู)", soft, WARN)

    return results


def print_report(results: list[dict], details: bool = False) -> int:
    print("=" * 72)
    print("ผลตรวจตาราง (check_schedule.py)")
    print("=" * 72)
    for r in results:
        note = f"  — {r['note']}" if r.get("note") else ""
        count = f" ({len(r['items'])})" if r["items"] else ""
        print(f"{r['level']} {r['title']}{count}{note}")
        shown = r["items"] if details else r["items"][:5]
        for item in shown:
            print(f"     • {item}")
        if len(r["items"]) > len(shown):
            print(f"     … และอีก {len(r['items']) - len(shown)} รายการ (ใช้ --details เพื่อดูทั้งหมด)")
    fails = sum(1 for r in results if r["level"] == FAIL)
    warns = sum(1 for r in results if r["level"] == WARN)
    print("-" * 72)
    if fails:
        print(f"สรุป: ❌ มีข้อผิด {fails} หมวด — ต้องแก้")
    elif warns:
        print(f"สรุป: ✅ ไม่มีข้อผิดกฎ  ⚠️ มีเรื่องควรดู {warns} หมวด")
    else:
        print("สรุป: ✅ ตารางถูกต้องครบทุกหมวด")
    return 1 if fails else 0


def main():
    parser = argparse.ArgumentParser(description="ตรวจตารางที่จัดแล้วใน Supabase (อ่านอย่างเดียว)")
    parser.add_argument("--details", action="store_true", help="แสดงทุกรายการ")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / "agent_timetable" / ".env")
    from agent_timetable.tools.scheduling.load_data import refresh_cache
    refresh_cache()   # อ่านข้อมูลล่าสุดจาก Supabase (อ่านอย่างเดียว)

    sys.exit(print_report(run_checks(), args.details))


if __name__ == "__main__":
    main()