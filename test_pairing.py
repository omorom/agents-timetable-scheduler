"""
test_pairing.py
ทดสอบว่า scheduler (Python ล้วน ไม่ผ่าน LLM/ADK agent) จับคู่ section ที่คนละอาจารย์/
team-teaching ถูกต้องไหม โดยเฉพาะ:
  - LECTURE ของ parallel group (คนละแถว subject_selected) รวมเป็นห้องเดียวกัน
    capacity รวมกันถูกไหม
  - LAB แยกคนละห้องต่ออาจารย์ เวลาเดียวกัน ถูกไหม
  - find_issues() ไม่ฟ้อง section_clash ผิดๆ (คาบเดียวกันแต่คนละห้อง ไม่ควรฟ้อง)
  - session ที่ล็อก fixed_room_id ไว้ ถูกจัดไปห้องที่ล็อกจริงไหม

วิธีรัน (จาก root โปรเจค เช่น D:\\thesis\\course-timetable):
    python test_pairing.py

ไม่เรียก Gemini/ADK agent เลย ไม่เปลือง API quota
"""

from pathlib import Path
from dotenv import load_dotenv
# .env อยู่ใน agent_timetable/.env ไม่ใช่ที่ root ต้องชี้ path ตรงๆ
load_dotenv(Path(__file__).parent / "agent_timetable" / ".env")

from agent_timetable.tools.scheduling.load_data import refresh_cache
from agent_timetable.tools.scheduling.auto_assign import auto_assign_all
from agent_timetable.tools.scheduling.find_issues import find_issues
from agent_timetable.tools.scheduling.assignment_store import get_current_schedule
from agent_timetable.tools.scheduling.section_logic import build_session_list


def main():
    print("=== รีเฟรชข้อมูลจาก Supabase ===")
    refresh_cache()

    print("\n=== จัดตารางใหม่ทั้งหมด (auto_assign_all) ===")
    result = auto_assign_all()
    print(f"assigned: {result['assigned_count']}  failed: {result['failed_count']}")
    if result["failed"]:
        print("\n--- session ที่จัดไม่ได้ ---")
        for f in result["failed"]:
            print(f"  - {f['session_id']}: {f['reason']}")

    print("\n=== ตรวจสอบปัญหา (find_issues) ===")
    issues = find_issues()
    hard = [i for i in issues if i.get("severity") == "hard"]
    soft = [i for i in issues if i.get("severity") == "soft"]
    print(f"hard issues: {len(hard)}  soft issues: {len(soft)}")
    for i in issues:
        print(f"  - [{i['severity']}] {i['type']}: {i['detail']}")

    print("\n=== ตารางทั้งหมดของวิชา 254171 (แก้ subject_id ตรงนี้ถ้าอยากดูวิชาอื่น) ===")
    target_subject_id = "254171"
    rows = [item for item in get_current_schedule() if item["subject_id"] == target_subject_id]
    if not rows:
        print(f"  ไม่พบวิชา {target_subject_id} ในตารางที่จัดได้ (เช็คว่าพิมพ์รหัสวิชาถูกไหม)")
    for item in rows:
        print(f"  {item}")

    print("\n=== เช็คด่วน: LECTURE ห้องเดียวกันไหม / LAB คนละห้องไหม ===")
    lectures = [r for r in rows if r.get("session_type") == "LECTURE"]
    labs = [r for r in rows if r.get("session_type") == "LAB"]

    lecture_rooms = {r.get("room_id") for r in lectures}
    print(f"LECTURE ใช้ห้อง: {lecture_rooms} "
          f"({'✅ ห้องเดียวกัน' if len(lecture_rooms) <= 1 else '❌ ห้องไม่ตรงกัน — ผิด'})")

    lab_rooms = [r.get("room_id") for r in labs]
    unique_lab_rooms = set(lab_rooms)
    print(f"LAB ใช้ห้อง: {lab_rooms}")
    if len(labs) > 1:
        rooms_differ = len(unique_lab_rooms) == len(labs)
        print(f"  {'✅ คนละห้องกันหมด' if rooms_differ else '❌ มีห้องซ้ำกัน — ผิด ถ้าตั้งใจให้แยกห้อง'}")

    # --- เช็ค fixed_room_id: session ไหนล็อกห้องไว้ ต้องถูกจัดไปห้องนั้นจริงเท่านั้น ---
    print("\n=== เช็ค fixed_room_id (ห้องล็อกตายตัว) ===")
    sessions_by_id = {s["session_id"]: s for s in build_session_list()}
    locked_sessions = {sid: s for sid, s in sessions_by_id.items() if s.get("fixed_room_id")}

    if not locked_sessions:
        print("  ไม่มี session ไหนตั้งค่า fixed_room_id ไว้เลย (ยังไม่ได้ล็อกห้องให้วิชาไหน)")
    else:
        schedule_by_id = {r["session_id"]: r for r in get_current_schedule()}
        for sid, sess in locked_sessions.items():
            expected_room = sess["fixed_room_id"]
            actual = schedule_by_id.get(sid)
            if not actual:
                print(f"  ⚠️  {sid}: ล็อกห้อง {expected_room} ไว้ แต่ไม่ถูกจัดเลย (ดู failed ด้านบน)")
                continue
            actual_room = actual.get("room_id")
            ok = actual_room == expected_room
            mark = "✅" if ok else "❌"
            print(f"  {mark} {sid}: ล็อกห้อง {expected_room} -> จัดจริงห้อง {actual_room}"
                  + ("" if ok else "  <<< ผิดพลาด ห้องไม่ตรงกับที่ล็อกไว้!"))


if __name__ == "__main__":
    main()