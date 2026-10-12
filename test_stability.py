"""
test_stability.py — จัดตารางซ้ำหลายรอบกับข้อมูลจริง แล้วสรุปว่าระบบ "น่าเชื่อถือแค่ไหน"
ตัวจัดตารางมีการสุ่ม ผลรอบเดียวไม่บอกอะไรมาก (รอบนึงอาจโชคดี อีกรอบอาจโชคร้าย)

ทุกรอบตรวจด้วย check_schedule.run_checks() ตัวเดียวกับที่ใช้ตรวจตารางจริง (8 หมวด)
รอบที่ "ผ่าน" = จัดครบทุกวิชา และไม่มีหมวดไหนผิดกฎ (❌)

วิธีรัน (จาก root โปรเจกต์ เปิด venv ก่อน):
    python test_stability.py                  # 5 รอบ เฉพาะอัลกอริทึม (Greedy + ซ่อมอัตโนมัติ) ไม่เรียก LLM
    python test_stability.py --repeat 10
    python test_stability.py --agent          # ทั้งระบบแบบกดปุ่ม "สร้างตาราง" (มี Agent / เสียค่า LLM เล็กน้อย)
    python test_stability.py --details        # แสดงรายการที่ไม่ผ่านทุกรอบ

คำเตือน: ทุกรอบจะลบตารางที่ AI จัดไว้ในฐานข้อมูลจริงแล้วจัดใหม่ ตารางที่ค้างหลังรันจบคือรอบสุดท้าย
(ไม่แตะวิชาศึกษาทั่วไปที่ล็อกไว้) ควรรันตอนไม่มีใครใช้ระบบ

exit code: 0 = ผ่านทุกรอบ, 1 = มีรอบที่ไม่ผ่าน
"""

import argparse
import asyncio
import io
import sys
import time
import traceback
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path


def run_once(use_agent: bool) -> dict:
    from agent_timetable.tools.scheduling.load_data import refresh_cache
    from agent_timetable.tools.scheduling.auto_assign import auto_assign_all
    import check_schedule

    log = io.StringIO()
    with redirect_stdout(log):
        if use_agent:
            from generate_service import run_generate
            message = asyncio.run(run_generate()).get("message", "")
        else:
            auto_assign_all()
            message = ""
    refresh_cache()
    checks = check_schedule.run_checks()
    cost_lines = [ln for ln in log.getvalue().splitlines() if ln.startswith("[cost] รวมครั้งนี้")]
    return {"checks": checks, "message": message, "cost": cost_lines[-1] if cost_lines else ""}


def main() -> int:
    parser = argparse.ArgumentParser(description="จัดตารางซ้ำหลายรอบแล้วสรุปความน่าเชื่อถือ")
    parser.add_argument("--repeat", type=int, default=5, help="จำนวนรอบ (ค่าเริ่มต้น 5)")
    parser.add_argument("--agent", action="store_true", help="รันทั้งระบบผ่าน Agent (เหมือนกดปุ่มสร้างตาราง)")
    parser.add_argument("--details", action="store_true", help="แสดงรายการที่ไม่ผ่านทุกรอบ")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / "agent_timetable" / ".env")
    import check_schedule

    mode = "ทั้งระบบ (มี Agent)" if args.agent else "อัลกอริทึมอย่างเดียว (ไม่เรียก LLM)"
    print(f"⚠️  จะลบและจัดตาราง AI ใหม่บนฐานข้อมูลจริง {args.repeat} รอบ — โหมด: {mode}")

    runs, unplaced, errors_by_cat, warn_by_cat, durations = [], Counter(), Counter(), Counter(), []
    for n in range(1, args.repeat + 1):
        print(f"\n--- รอบที่ {n}/{args.repeat} ---")
        started = time.time()
        try:
            r = run_once(args.agent)
        except Exception:
            print("  💥 error ระหว่างรัน:")
            traceback.print_exc()
            runs.append(None)
            continue
        took = time.time() - started
        durations.append(took)

        checks = r["checks"]
        missing = next(c for c in checks if c["title"].startswith("1."))["items"]
        fails = [c for c in checks if c["level"] == check_schedule.FAIL]
        warns = [c for c in checks if c["level"] == check_schedule.WARN and not c["title"].startswith("1.")]
        ok = not missing and not fails
        runs.append(ok)
        unplaced.update(missing)
        errors_by_cat.update(c["title"] for c in fails)
        warn_by_cat.update({c["title"]: len(c["items"]) for c in warns})

        print(f"  {'✅ ผ่าน' if ok else '❌ ไม่ผ่าน'} ({took:.0f} วินาที) | จัดไม่ได้ {len(missing)} | "
              f"หมวดที่ผิดกฎ {len(fails)} | เรื่องควรดู {sum(len(c['items']) for c in warns)}")
        for item in missing[:5]:
            print(f"     ✗ จัดไม่ได้: {item}")
        for c in fails:
            print(f"     ✗ {c['title']}: {len(c['items'])} รายการ")
            for item in (c["items"] if args.details else c["items"][:2]):
                print(f"         • {item}")
        if r["cost"]:
            print(f"  {r['cost']}")
        if args.details and r["message"]:
            print("  สรุปจากระบบ: " + r["message"].replace("\n", "\n               "))

    finished = [x for x in runs if x is not None]
    print(f"\n{'=' * 10} สรุป {args.repeat} รอบ ({mode}) {'=' * 10}")
    print(f"ผ่านครบ (จัดครบทุกวิชา + ไม่ผิดกฎ): {sum(finished)}/{args.repeat} รอบ")
    if len(finished) < args.repeat:
        print(f"รันไม่สำเร็จ (error): {args.repeat - len(finished)} รอบ")
    if durations:
        print(f"เวลาต่อรอบ: เฉลี่ย {sum(durations) / len(durations):.0f} วินาที "
              f"(เร็วสุด {min(durations):.0f} / ช้าสุด {max(durations):.0f})")
    if unplaced:
        print("\nวิชาที่จัดไม่ได้บ่อย:")
        for item, cnt in unplaced.most_common(10):
            print(f"  - {item}: {cnt}/{len(finished)} รอบ")
    else:
        print("ไม่มีวิชาตกเลยในทุกรอบ")
    if errors_by_cat:
        print("\nหมวดที่ผิดกฎ (กี่รอบ):")
        for title, cnt in errors_by_cat.most_common():
            print(f"  - {title}: {cnt} รอบ")
    else:
        print("ไม่มีรอบไหนผิดกฎเลย")
    if warn_by_cat:
        print("\nเรื่องควรดู (รวมทุกรอบ):")
        for title, cnt in warn_by_cat.most_common():
            print(f"  - {title}: {cnt} รายการ")

    return 0 if finished and all(finished) and len(finished) == args.repeat else 1


if __name__ == "__main__":
    sys.exit(main())