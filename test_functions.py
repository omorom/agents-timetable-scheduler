"""
test_functions.py
สคริปต์ทดสอบฟังก์ชัน query/mutate โดยตรง — ไม่ผ่าน Gemini/agent เลย
ใช้ตอน debug logic (เช่น _find_group_id, set_student_count, get_system_summary)
เพื่อไม่ให้เสีย Gemini API quota โดยไม่จำเป็น

วิธีรัน (จาก root โปรเจกต์ ที่มี main.py อยู่):
    python test_functions.py
หรือถ้าใช้ uv:
    uv run python test_functions.py

แก้ค่าทดสอบในฟังก์ชันด้านล่างได้ตามต้องการ แล้วรันดูผลลัพธ์ที่ terminal ตรงๆ
"""

from dotenv import load_dotenv
load_dotenv(dotenv_path="agent_timetable/.env")

from agent_timetable.tools.query_data import (
    _find_group_id,
    _find_teacher_id,
    _find_subject_id,
    _find_room_id,
    get_subject_sections,
    get_teacher_subjects,
)
from agent_timetable.tools.query_data_people import (
    get_group_schedule,
    get_group_free_slots,
    get_group_workload,
    get_teacher_schedule,
    get_teacher_free_slots,
    get_teacher_workload,
)
from agent_timetable.tools.query_data_spaces import (
    get_room_schedule,
    get_room_free_slots,
    get_room_usage_stats,
    get_subject_current_schedule,
    check_move_feasibility,
    get_availability_at,
    get_system_summary,
)
from agent_timetable.tools.mutate_data import set_student_count


def section(title: str):
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def test_find_group_id():
    section("_find_group_id")
    for name in ["IT ปี 1", "IT ปี 2", "ปี 1", "COMSCI ปี 1", "ไม่มีจริง"]:
        try:
            gid = _find_group_id(name)
            print(f"  '{name}' -> {gid}")
        except ValueError as e:
            print(f"  '{name}' -> ERROR: {e}")


def test_set_student_count():
    section("set_student_count (เปลี่ยนจริงในฐานข้อมูล ระวัง!)")
    result = set_student_count("IT ปี 2", 99)
    print(f"  result: {result}")


def test_group_functions():
    section("get_group_schedule / free_slots / workload")
    print("schedule:", get_group_schedule("IT ปี 1"))
    print("free_slots:", get_group_free_slots("IT ปี 1"))
    print("workload:", get_group_workload("IT ปี 1"))


def test_teacher_functions():
    section("get_teacher_schedule / free_slots / workload")
    teacher_name = "ใส่ชื่ออาจารย์ตรงนี้"
    print("schedule:", get_teacher_schedule(teacher_name))
    print("free_slots:", get_teacher_free_slots(teacher_name))
    print("workload:", get_teacher_workload(teacher_name))


def test_room_functions():
    section("get_room_schedule / free_slots / usage_stats")
    room_name = "ใส่รหัสห้องตรงนี้ เช่น SC1-311"
    print("schedule:", get_room_schedule(room_name))
    print("free_slots:", get_room_free_slots(room_name))
    print("usage_stats:", get_room_usage_stats())


def test_subject_functions():
    section("get_subject_current_schedule / check_move_feasibility")
    subject_name = "273387"
    print("current_schedule:", get_subject_current_schedule(subject_name))
    print("move_feasibility:", check_move_feasibility(subject_name, "จันทร์", "15:00", "16:50"))


def test_overview_functions():
    section("get_availability_at / get_system_summary")
    print("availability_at:", get_availability_at("จันทร์", "15:00", "16:50"))
    print("system_summary:", get_system_summary())


if __name__ == "__main__":
    # เปิด/ปิดคอมเมนต์ทีละบรรทัดตามที่อยากทดสอบ — ไม่ต้องรันทุกอันพร้อมกันทุกครั้ง
    test_find_group_id()
    # test_set_student_count()   # ← เปลี่ยนข้อมูลจริง เปิดใช้ตอนพร้อมทดสอบจริงๆ เท่านั้น
    test_group_functions()
    # test_teacher_functions()   # ← ใส่ชื่ออาจารย์จริงก่อนเปิดใช้
    # test_room_functions()      # ← ใส่รหัสห้องจริงก่อนเปิดใช้
    test_subject_functions()
    test_overview_functions()