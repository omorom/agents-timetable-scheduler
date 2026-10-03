"""
test_stability.py
รันจัดตารางทั้งระบบซ้ำหลายรอบ (Python ล้วน ไม่เรียก LLM) แล้วสรุปว่า "น่าเชื่อถือแค่ไหน"
เพราะตัวจัดตารางมีการสุ่ม ผลรอบเดียวไม่บอกอะไรมาก — รอบนึงอาจโชคดี อีกรอบอาจโชคร้าย

ในแต่ละรอบเช็ก:
  1. failed = 0 (ไม่มีวิชาตกหล่น)
  2. ไม่มีการชนจริง ห้อง/อาจารย์/กลุ่มนิสิต ในตารางที่ AI จัด
       - ห้อง: ห้องเดียวกัน คาบเดียวกัน ต่าง session
       - อาจารย์: อาจารย์คนเดียวกัน คาบเดียวกัน ต่าง session
       - กลุ่มนิสิต: กลุ่มเดียวกัน คาบเดียวกัน ต่างวิชา (section คู่ขนานของวิชาเดียวกันไม่นับ)
  3. SYNC_LECTURE_GROUPS: LECTURE คาบเดียวกัน คนละห้อง และอยู่ในช่วงเวลาที่กำหนด
  4. (แค่รายงาน ไม่นับผ่าน/ไม่ผ่าน) จำนวน hard issue จาก find_issues

วิธีรัน (จาก root โปรเจค):
    py test_stability.py                 # 5 รอบ
    py test_stability.py --repeat 10
    py test_stability.py --repeat 3 --show-clashes

คำเตือน: auto_assign_all() ลบตาราง timetable_ai บน Supabase แล้วจัดใหม่ทุกรอบ
ตารางที่ค้างอยู่หลังรันจบคือผลของ "รอบสุดท้าย" — ถ้าหน้าเว็บใช้ฐานข้อมูลเดียวกัน
ควรรันเทสก่อนวันพรีเซนต์ แล้วกด "สร้างตาราง" อีกครั้งเพื่อได้ตารางที่ต้องการ

exit code: 0 = ผ่านทุกรอบ, 1 = มีรอบที่ไม่ผ่าน
"""

import argparse
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

# .env อยู่ใน agent_timetable/.env ไม่ใช่ที่ root
load_dotenv(Path(__file__).parent / "agent_timetable" / ".env")

from agent_timetable.tools.scheduling.load_data import get_cached_data
from agent_timetable.tools.scheduling.auto_assign import (
    auto_assign_all,
    _slot_in_window,
    SYNC_LECTURE_GROUPS,
)
from agent_timetable.tools.scheduling.find_issues import find_issues
from agent_timetable.tools.scheduling.assignment_store import get_current_schedule


def find_clashes(schedule: list[dict]) -> list[str]:
    """หาการชนจริงในตารางที่จัดแล้ว (ห้อง / อาจารย์ / กลุ่มนิสิต)"""
    room_at: dict = {}
    teacher_at: dict = {}
    group_at: dict = {}

    for item in schedule:
        sid = item.get("session_id") or f"NOID-{item.get('subject_id')}"
        for ts in item.get("timeslot_ids") or []:
            ts = str(ts)
            if item.get("room_id") is not None:
                room_at.setdefault((item["room_id"], ts), set()).add(sid)
            for t in item.get("teacher_ids") or []:
                teacher_at.setdefault((t, ts), set()).add(sid)
            for g in item.get("group_ids") or []:
                group_at.setdefault((g, ts), []).append(item)

    clashes = []
    for (room, ts), sids in room_at.items():
        if len(sids) > 1:
            clashes.append(f"ห้อง {room} คาบ {ts} ถูกใช้พร้อมกัน: {sorted(sids)}")
    for (teacher, ts), sids in teacher_at.items():
        if len(sids) > 1:
            clashes.append(f"อาจารย์ {teacher} คาบ {ts} สอนพร้อมกัน: {sorted(sids)}")
    for (group, ts), items in group_at.items():
        subjects = {i.get("subject_id") for i in items}
        if len(subjects) > 1:  # section คู่ขนานของวิชาเดียวกันไม่นับเป็นการชน
            clashes.append(f"กลุ่ม {group} คาบ {ts} เรียนพร้อมกันหลายวิชา: {sorted(str(s) for s in subjects)}")
    return clashes


def check_sync(schedule: list[dict]) -> list[str]:
    """เช็ก SYNC_LECTURE_GROUPS: คาบเดียวกัน คนละห้อง อยู่ในช่วงเวลา"""
    timeslots_by_id = {t["timeslot_id"]: t for t in get_cached_data()["timeslots"]}
    problems = []

    for group in SYNC_LECTURE_GROUPS:
        rows = {
            sid: sorted(
                (r for r in schedule if r.get("subject_id") == sid and r.get("session_type") == "LECTURE"),
                key=lambda r: r["session_id"],
            )
            for sid in group
        }
        missing = [sid for sid, v in rows.items() if not v]
        if missing:
            problems.append(f"{group}: ไม่มี LECTURE ในตาราง {missing}")
            continue

        for idx in range(min(len(v) for v in rows.values())):
            block = {sid: rows[sid][idx] for sid in group}
            slot_sets = {tuple(sorted(str(t) for t in r["timeslot_ids"])) for r in block.values()}
            rooms = [r.get("room_id") for r in block.values()]
            if len(slot_sets) != 1:
                problems.append(f"{group} block {idx + 1}: คาบไม่ตรงกัน {slot_sets}")
            if len(set(rooms)) != len(rooms):
                problems.append(f"{group} block {idx + 1}: ห้องซ้ำกัน {rooms}")
            for sid, r in block.items():
                if not _slot_in_window({"timeslot_ids": list(r["timeslot_ids"])}, timeslots_by_id):
                    problems.append(f"{sid} block {idx + 1}: อยู่นอกช่วงเวลาที่กำหนด")
    return problems


def run_once() -> dict:
    result = auto_assign_all()
    schedule = get_current_schedule()
    issues = find_issues()
    hard = [i for i in issues if i.get("severity") == "hard"]
    return {
        "failed": result.get("failed", []),
        "clashes": find_clashes(schedule),
        "sync_problems": check_sync(schedule),
        "hard_count": len(hard),
        "hard_types": Counter(i.get("type") for i in hard),
        "assigned": result.get("assigned_count"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="รันจัดตารางซ้ำหลายรอบแล้วสรุปความน่าเชื่อถือ")
    parser.add_argument("--repeat", type=int, default=5, help="จำนวนรอบ (ค่าเริ่มต้น 5)")
    parser.add_argument("--show-clashes", action="store_true", help="พิมพ์รายละเอียดการชนทุกรอบ")
    args = parser.parse_args()

    print("⚠️  แต่ละรอบจะลบและจัดตาราง AI ใหม่บนฐานข้อมูลจริง (ผลสุดท้ายคือรอบสุดท้าย)")

    runs = []
    for n in range(1, args.repeat + 1):
        start = time.time()
        print(f"\n--- รอบที่ {n}/{args.repeat} ---")
        try:
            r = run_once()
        except Exception:
            print("  💥 error ระหว่างรัน:")
            traceback.print_exc()
            runs.append({"error": True})
            continue

        r["error"] = False
        r["ok"] = not r["failed"] and not r["clashes"] and not r["sync_problems"]
        runs.append(r)

        print(f"  {'✅ ผ่าน' if r['ok'] else '❌ ไม่ผ่าน'} ({time.time() - start:.0f} วินาที) "
              f"| จัดได้ {r['assigned']} | ตก {len(r['failed'])} | ชน {len(r['clashes'])} "
              f"| sync ผิด {len(r['sync_problems'])} | hard issue {r['hard_count']}")
        for f in r["failed"]:
            print(f"     ✗ {f.get('subject_id')} ({f.get('session_type')}): {f.get('reason')}")
        for p in r["sync_problems"]:
            print(f"     ✗ SYNC: {p}")
        if args.show_clashes or r["clashes"]:
            for c in r["clashes"][:10]:
                print(f"     ✗ ชน: {c}")

    # ── สรุป ──
    finished = [r for r in runs if not r.get("error")]
    ok_runs = [r for r in finished if r["ok"]]

    print(f"\n{'=' * 8} สรุป {args.repeat} รอบ {'=' * 8}")
    print(f"ผ่านครบ (ไม่ตก + ไม่ชน + sync ถูก): {len(ok_runs)}/{args.repeat} รอบ")
    if len(finished) < args.repeat:
        print(f"รันไม่สำเร็จ (error): {args.repeat - len(finished)} รอบ")

    if finished:
        failed_counter = Counter(
            (f.get("subject_id"), f.get("session_type")) for r in finished for f in r["failed"]
        )
        if failed_counter:
            print("\nวิชาที่ตกบ่อย (จากกี่รอบ):")
            for (subject, stype), cnt in failed_counter.most_common():
                print(f"  - {subject} ({stype}): ตก {cnt}/{len(finished)} รอบ")
        else:
            print("\nไม่มีวิชาตกเลยในทุกรอบ")

        print(f"\nรอบที่เจอการชนจริง (ห้อง/อาจารย์/กลุ่ม): {sum(1 for r in finished if r['clashes'])}/{len(finished)}")
        print(f"รอบที่ SYNC ถูกต้อง: {sum(1 for r in finished if not r['sync_problems'])}/{len(finished)}")

        hard_counts = [r["hard_count"] for r in finished]
        print(f"hard issue จาก find_issues: ต่ำสุด {min(hard_counts)} | สูงสุด {max(hard_counts)} "
              f"| เฉลี่ย {sum(hard_counts) / len(hard_counts):.1f}  (รายงานเฉยๆ ไม่นับผ่าน/ไม่ผ่าน)")
        types = Counter()
        for r in finished:
            types.update(r["hard_types"])
        if types:
            print("  แยกตามประเภท (รวมทุกรอบ): " + ", ".join(f"{t}={c}" for t, c in types.most_common()))

    return 0 if len(ok_runs) == args.repeat else 1


if __name__ == "__main__":
    sys.exit(main())