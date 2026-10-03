"""
test_pairing.py
ทดสอบ scheduler (Python ล้วน ไม่ผ่าน LLM/ADK agent ไม่เปลือง API quota)

สิ่งที่เช็ค (ต่อวิชาที่ระบุ):
  1. session ที่ build_session_list() สร้างขึ้น  -> เห็นว่ามี LAB โผล่มาผิดไหม
  2. เหตุผลที่ "จัดไม่ได้" (failed) ของวิชานั้น
  3. LECTURE ห้องเดียวกันไหม / LAB คนละห้องไหม
  4. วิชาที่ระบุว่า "ไม่ควรมี LAB" (--no-lab) ต้องไม่มี LAB session เลย
  5. fixed_room_id ถูกจัดไปห้องที่ล็อกจริงไหม
  6. SYNC: วิชาใน SYNC_LECTURE_GROUPS ต้อง LECTURE วัน/คาบเดียวกัน คนละห้อง
     และอยู่ในช่วง SYNC_TIME_WINDOW
  7. DIAGNOSE: ทำไมจัดไม่ได้ — นับ slot ว่างทั้งหมด / ในช่วงเวลา / คาบที่ว่างตรงกัน
     (รวมมาจาก debug_sync.py แล้ว ไม่ต้องสร้างไฟล์แยก)
  8. find_issues() (ปริมาณ hard/soft)

วิธีรัน (จาก root โปรเจค):
    python test_pairing.py                          # default: 254391 273391
    python test_pairing.py 254391                   # เฉพาะวิชาเดียว
    python test_pairing.py 254391 273391 --no-lab 254391
    python test_pairing.py --skip-refresh           # ใช้ cache เดิม ไม่ดึง Supabase ใหม่
    python test_pairing.py --show-raw               # dump session dict ดิบๆ
    python test_pairing.py --sessions-only          # ดู session ที่ build ได้ ไม่รัน auto_assign
    python test_pairing.py --no-diagnose            # ข้ามส่วน DIAGNOSE

หมายเหตุ: ส่วน DIAGNOSE รันหลัง auto_assign_all() จึงเห็น slot ที่ "ยังว่างจริง" หลังวิชาอื่น
จัดเสร็จแล้ว (ถ้าวิชานั้นถูกจัดลงตารางไปแล้ว slot ของมันเองจะไม่นับเป็นว่าง)

exit code: 0 = ผ่านทุกข้อ, 1 = มีข้อที่ FAIL
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

# .env อยู่ใน agent_timetable/.env ไม่ใช่ที่ root ต้องชี้ path ตรงๆ
load_dotenv(Path(__file__).parent / "agent_timetable" / ".env")

from agent_timetable.tools.scheduling.load_data import refresh_cache, get_cached_data
from agent_timetable.tools.scheduling.auto_assign import (
    auto_assign_all,
    _slot_in_window,
    _lookup_timeslot,
    SYNC_LECTURE_GROUPS,
    SYNC_STRICT,
    SYNC_TIME_WINDOW,
)
from agent_timetable.tools.scheduling.find_issues import find_issues
from agent_timetable.tools.scheduling.assignment_store import get_current_schedule
from agent_timetable.tools.scheduling.section_logic import build_session_list
from agent_timetable.tools.scheduling.slot_filter import get_valid_slots
from agent_timetable.tools.scheduling.candidate_scorer import day_of

DEFAULT_SUBJECTS = ["254391", "273391"]

# เก็บผลเช็คทั้งหมดไว้สรุปตอนท้าย
RESULTS = []  # list of (ok: bool, message: str)


def check(ok, message):
    RESULTS.append((ok, message))
    print(f"  {'✅' if ok else '❌'} {message}")
    return ok


def header(title):
    print(f"\n{'=' * 8} {title} {'=' * 8}")


def belongs_to(item, subject_id):
    """session/schedule item นี้เป็นของวิชานี้ไหม (เผื่อ key ไม่ใช่ subject_id ตรงๆ)"""
    if str(item.get("subject_id", "")) == subject_id:
        return True
    return subject_id in str(item.get("session_id", ""))


def show_sessions(subject_id, sessions, show_raw):
    """ดู session ที่ build_session_list() สร้างให้วิชานี้"""
    mine = [s for s in sessions if belongs_to(s, subject_id)]
    print(f"  พบ {len(mine)} session")
    for s in mine:
        if show_raw:
            print(f"    {s}")
        else:
            print(
                f"    - {s.get('session_id')} | type={s.get('session_type')} "
                f"| group={s.get('group_ids', s.get('group_id'))} "
                f"| hours={s.get('hours', s.get('duration'))} "
                f"| teacher={s.get('teacher_ids', s.get('teacher_id'))} "
                f"| fixed_room={s.get('fixed_room_id')}"
            )
    return mine


def test_subject(subject_id, sessions, schedule, failed, no_lab, show_raw):
    header(f"วิชา {subject_id}")

    # 1) session ที่ถูกสร้าง
    print("[1] session ที่ build_session_list() สร้างให้")
    my_sessions = show_sessions(subject_id, sessions, show_raw)
    if not my_sessions:
        check(False, "ไม่มี session ถูกสร้างเลย (ตรวจ lecture/lab_hours, subject_selected, อาจารย์ผู้สอน)")

    # 2) ผลการจัด
    print("\n[2] ผลการจัดลงตาราง")
    my_failed = [f for f in failed if belongs_to(f, subject_id)]
    my_rows = [r for r in schedule if belongs_to(r, subject_id)]
    print(f"  จัดได้ {len(my_rows)} session | จัดไม่ได้ {len(my_failed)} session")
    for f in my_failed:
        print(f"    ✗ {f['session_id']} ({f.get('session_type')}): {f.get('reason')}")
    for r in my_rows:
        print(f"    ✓ {r}")
    check(not my_failed, f"{subject_id}: ไม่มี session ที่จัดไม่ได้")

    # 3) LECTURE / LAB
    lectures = [r for r in my_rows if r.get("session_type") == "LECTURE"]
    labs = [r for r in my_rows if r.get("session_type") == "LAB"]

    print("\n[3] LECTURE / LAB")
    lecture_rooms = {r.get("room_id") for r in lectures}
    if lectures:
        check(len(lecture_rooms) <= 1, f"LECTURE อยู่ห้องเดียวกัน (ห้อง: {lecture_rooms})")
    if len(labs) > 1:
        lab_rooms = [r.get("room_id") for r in labs]
        check(len(set(lab_rooms)) == len(labs), f"LAB แยกคนละห้อง (ห้อง: {lab_rooms})")

    # 4) ไม่ควรมี LAB
    if subject_id in no_lab:
        print("\n[4] วิชานี้ไม่ควรมี LAB")
        lab_sessions = [s for s in my_sessions if s.get("session_type") == "LAB"]
        check(not lab_sessions, f"ไม่มี LAB session ถูกสร้าง (พบ {len(lab_sessions)})")
        check(not labs, f"ไม่มี LAB ในตารางที่จัด (พบ {len(labs)})")

    # 5) fixed_room_id
    locked = [s for s in my_sessions if s.get("fixed_room_id")]
    if locked:
        print("\n[5] fixed_room_id")
        by_id = {r["session_id"]: r for r in my_rows}
        for s in locked:
            actual = by_id.get(s["session_id"])
            if not actual:
                check(False, f"{s['session_id']}: ล็อกห้อง {s['fixed_room_id']} แต่ไม่ถูกจัดเลย")
            else:
                check(
                    actual.get("room_id") == s["fixed_room_id"],
                    f"{s['session_id']}: ล็อก {s['fixed_room_id']} -> จริง {actual.get('room_id')}",
                )


def cross_contamination_check(subjects, sessions):
    """เช็คว่า session ของวิชาหนึ่งไปติดชั่วโมง/ประเภทของอีกวิชาไหม"""
    if len(subjects) < 2:
        return
    header("ตรวจการปนกันระหว่างวิชา")
    seen = {}
    for sid in subjects:
        for s in sessions:
            if belongs_to(s, sid):
                seen.setdefault(s.get("session_id"), []).append(sid)
    dup = {k: v for k, v in seen.items() if len(v) > 1}
    check(not dup, f"ไม่มี session ที่ถูกนับเป็นของหลายวิชาพร้อมกัน {dup if dup else ''}")


def _slot_label(schedule_item, timeslots_by_id):
    """คืน (day, timeslot_ids) ของ item ในตาราง — รองรับทั้งกรณีมี/ไม่มี key day"""
    tids = tuple(schedule_item.get("timeslot_ids") or [])
    day = schedule_item.get("day") or (day_of(tids[0]) if tids else None)
    return day, tids


def check_sync_groups(subjects, schedule):
    """เช็คผลของ SYNC_LECTURE_GROUPS: LECTURE วัน/คาบเดียวกัน คนละห้อง อยู่ในช่วงเวลา"""
    groups = [g for g in SYNC_LECTURE_GROUPS if any(sid in subjects for sid in g)]
    if not groups:
        return

    header("SYNC: เวลาเดียวกัน คนละห้อง")
    print(f"  SYNC_STRICT={SYNC_STRICT}  SYNC_TIME_WINDOW={SYNC_TIME_WINDOW}")
    timeslots_by_id = {t["timeslot_id"]: t for t in get_cached_data()["timeslots"]}

    for group in groups:
        print(f"\n  กลุ่ม {group}")
        rows = {}
        for sid in group:
            lec = [r for r in schedule if belongs_to(r, sid) and r.get("session_type") == "LECTURE"]
            rows[sid] = lec
            if not lec:
                check(False, f"{sid}: ไม่มี LECTURE ในตาราง (ไม่ได้ถูกจัด)")
        if any(not v for v in rows.values()):
            continue

        # จับคู่ตามลำดับ block
        n = min(len(v) for v in rows.values())
        for idx in range(n):
            block = {sid: sorted(rows[sid], key=lambda r: r["session_id"])[idx] for sid in group}
            slots = {sid: _slot_label(r, timeslots_by_id) for sid, r in block.items()}
            rooms = [r.get("room_id") for r in block.values()]

            check(len(set(slots.values())) == 1, f"block {idx + 1}: วัน/คาบตรงกัน {slots}")
            check(len(set(rooms)) == len(rooms), f"block {idx + 1}: คนละห้อง {rooms}")

            if SYNC_TIME_WINDOW is not None:
                in_win = all(
                    _slot_in_window({"timeslot_ids": list(tids)}, timeslots_by_id)
                    for _, tids in slots.values()
                )
                check(in_win, f"block {idx + 1}: อยู่ในช่วง {SYNC_TIME_WINDOW}")


def diagnose_sync(subjects, sessions):
    """ไล่หาสาเหตุที่ LECTURE ของกลุ่ม sync จัดไม่ได้:
    ต่อ session -> slot ว่างทั้งหมด / ในช่วงเวลา, ต่อกลุ่ม -> คาบที่ว่างตรงกัน + จำนวนห้อง
    """
    header("DIAGNOSE: ทำไมจัดไม่ได้")
    timeslots_by_id = {t["timeslot_id"]: t for t in get_cached_data()["timeslots"]}

    # slot_map[subject_id] = {(day, tids): set(room_id)} เฉพาะที่อยู่ในช่วงเวลา
    slot_map: dict[str, dict] = {}

    for sid in subjects:
        lectures = [s for s in sessions if belongs_to(s, sid) and s.get("session_type") == "LECTURE"]
        if not lectures:
            print(f"\n{sid}: ไม่มี LECTURE session ให้ตรวจ")
            continue

        for s in lectures:
            print(
                f"\n{sid} | {s['session_id']} | teacher={s.get('teacher_ids')} "
                f"| group={s.get('group_ids')} | hours={s.get('hours', s.get('duration'))}"
            )
            r = get_valid_slots(s["session_id"], limit=None)
            if r.get("error"):
                print(f"  ❌ get_valid_slots ERROR: {r['error']}")
                continue

            valid = r["valid_slots"]
            in_win = [c for c in valid if _slot_in_window(c, timeslots_by_id)]
            print(f"  slot ว่างทั้งหมด: {len(valid)} | อยู่ในช่วง {SYNC_TIME_WINDOW}: {len(in_win)}")

            # --- debug: ดูว่า slot ว่างจริงๆ ตกวัน/เวลาไหน และชนิดของ id ตรงกันไหม ---
            if valid:
                print(
                    f"  [debug] ชนิด id ใน candidate: {type(valid[0]['timeslot_ids'][0]).__name__} "
                    f"| ชนิด key ของ timeslots_by_id: {type(next(iter(timeslots_by_id))).__name__}"
                )

            def _start(c):
                t = _lookup_timeslot(timeslots_by_id, c["timeslot_ids"][0])
                return str(t["start_time"])[:5] if t else "?"

            starts = sorted({(day_of(c["timeslot_ids"][0]), _start(c)) for c in valid})
            print(f"  [debug] วัน/เวลาเริ่มของ slot ว่างทั้งหมด: {starts}")
            wed = [c for c in valid if sorted(int(x) for x in c["timeslot_ids"]) == [23, 24]]
            print(f"  [debug] candidate WED 15:00-17:00 (timeslot 23,24): {len(wed)}")

            per_slot: dict = {}
            for c in in_win:
                key = (day_of(c["timeslot_ids"][0]), tuple(c["timeslot_ids"]))
                per_slot.setdefault(key, set()).add(c["room_id"])
            for key, rooms in sorted(per_slot.items())[:10]:
                print(f"    {key[0]} timeslot={list(key[1])} ห้องว่าง {len(rooms)}: {sorted(rooms)}")

            slot_map.setdefault(sid, {}).update(per_slot)

            if not valid:
                print("  → ไม่มี slot ว่างเลย: ปัญหาอยู่ที่ตัววิชา/ข้อมูล (lab_hours NULL? ไม่มีอาจารย์? group_id?)")
            elif not in_win:
                print("  → มี slot แต่ไม่มีเลยในช่วงเวลาที่กำหนด: ลองขยาย SYNC_TIME_WINDOW")

    # หาคาบที่ว่างตรงกันของแต่ละกลุ่ม
    for group in SYNC_LECTURE_GROUPS:
        if not all(sid in slot_map for sid in group):
            continue
        common = set.intersection(*(set(slot_map[sid].keys()) for sid in group))
        print(f"\nกลุ่ม {group}: คาบที่ว่างตรงกัน (ในช่วงเวลา) = {len(common)}")
        for key in sorted(common)[:10]:
            all_rooms = set().union(*(slot_map[sid][key] for sid in group))
            enough = len(all_rooms) >= len(group)
            print(f"    {key[0]} timeslot={list(key[1])} | ห้องรวม {len(all_rooms)} "
                  f"({'พอสำหรับ ' + str(len(group)) + ' ห้อง' if enough else 'ไม่พอ'})")
        if not common:
            print("  → ไม่มีคาบไหนที่ทั้งสองกลุ่มนิสิตว่างพร้อมกันในช่วงเวลานี้ ต้องขยายช่วงเวลา")


def main():
    parser = argparse.ArgumentParser(description="ทดสอบการจัดตารางของวิชาที่ระบุ")
    parser.add_argument("subjects", nargs="*", default=DEFAULT_SUBJECTS, help="รหัสวิชาที่ต้องการเทส")
    parser.add_argument("--no-lab", nargs="*", default=["254391", "273391"], help="วิชาที่ต้องไม่มี LAB")
    parser.add_argument("--skip-refresh", action="store_true", help="ไม่ดึงข้อมูลจาก Supabase ใหม่")
    parser.add_argument("--sessions-only", action="store_true", help="ดูเฉพาะ session ที่ build ได้ ไม่รัน auto_assign")
    parser.add_argument("--show-raw", action="store_true", help="dump session dict ดิบ")
    parser.add_argument("--show-issues", action="store_true", help="พิมพ์รายละเอียด find_issues ทั้งหมด")
    parser.add_argument("--no-diagnose", action="store_true", help="ข้ามส่วน DIAGNOSE")
    args = parser.parse_args()

    if not args.skip_refresh:
        header("รีเฟรชข้อมูลจาก Supabase")
        refresh_cache()

    sessions = build_session_list()

    if args.sessions_only:
        header("session ที่ build ได้ (ไม่รัน auto_assign)")
        for sid in args.subjects:
            print(f"\nวิชา {sid}")
            show_sessions(sid, sessions, args.show_raw)
        return 0

    header("จัดตารางใหม่ทั้งหมด (auto_assign_all)")
    result = auto_assign_all()
    print(f"assigned: {result['assigned_count']}  failed: {result['failed_count']}")
    failed = result.get("failed", [])
    if failed:
        print("  --- session ที่จัดไม่ได้ทั้งหมด (ทุกวิชา) ---")
        for f in failed:
            print(f"  ✗ {f.get('subject_id')} {f.get('session_id')} ({f.get('session_type')}) "
                  f"group={f.get('group_ids')}: {f.get('reason')}")
    schedule = get_current_schedule()

    for sid in args.subjects:
        test_subject(sid, sessions, schedule, failed, set(args.no_lab), args.show_raw)

    cross_contamination_check(args.subjects, sessions)
    check_sync_groups(set(args.subjects), schedule)

    if not args.no_diagnose:
        unplaced = [sid for sid in args.subjects if not any(belongs_to(r, sid) for r in schedule)]
        if unplaced:
            diagnose_sync(unplaced, sessions)
        else:
            header("DIAGNOSE")
            print("  ทุกวิชาที่เทสถูกจัดลงตารางแล้ว ข้ามส่วนนี้ (ตัวเลข slot ว่างหลังจัดจะทำให้เข้าใจผิด)")

    header("find_issues")
    issues = find_issues()
    hard = [i for i in issues if i.get("severity") == "hard"]
    soft = [i for i in issues if i.get("severity") == "soft"]
    print(f"hard: {len(hard)}  soft: {len(soft)}")
    # แสดง hard เสมอ, soft แสดงเมื่อสั่ง --show-issues
    for i in (issues if args.show_issues else hard):
        print(f"  - [{i['severity']}] {i['type']}: {i['detail']}")

    tested_ids = {
        s["session_id"] for s in sessions
        if any(belongs_to(s, sid) for sid in args.subjects)
    }

    def _related(i):
        return (
            i.get("fix_session_id") in tested_ids
            or i.get("session_id") in tested_ids
            or bool(set(i.get("session_ids") or []) & tested_ids)
        )

    related = [i for i in hard if _related(i)]
    print(f"  hard ที่เกี่ยวกับวิชาที่เทส: {len(related)} จากทั้งหมด {len(hard)} "
          "(ที่เหลือเป็นของวิชาอื่น ไม่นับเป็น FAIL ของเทสนี้)")
    check(not related, "ไม่มี hard issue ที่เกี่ยวกับวิชาที่เทส")

    header("สรุป")
    failed_checks = [m for ok, m in RESULTS if not ok]
    print(f"ผ่าน {len(RESULTS) - len(failed_checks)}/{len(RESULTS)} ข้อ")
    for m in failed_checks:
        print(f"  ❌ {m}")
    return 1 if failed_checks else 0


if __name__ == "__main__":
    sys.exit(main())