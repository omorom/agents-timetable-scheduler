from google.adk.agents.llm_agent import Agent
from google.adk.tools import FunctionTool

from .models import make_model, make_planner
from .tools.get_data import load, load_all
from .tools.mutate_data import (
    set_teacher_unavailability,
    set_room_unavailability,
    set_student_count,
    remove_teacher_unavailability,
    open_subject_section,
    close_subject_section,
)
from .tools.query_data import (
    get_teacher_unavailability,
    get_room_unavailability,
    list_unavailable_rooms,
    list_unavailable_teachers,
    list_available_rooms,
    list_available_teachers,
    get_subject_sections,
    get_teacher_subjects,
    get_subject_preferred_timeslots,
)
from .tools.query_data_people import (
    # 🎓 นิสิต
    get_group_student_count,
    get_group_schedule,
    get_group_free_slots,
    get_group_workload,
    # 👨‍🏫 อาจารย์
    get_teacher_schedule,
    get_teacher_free_slots,
    get_teacher_workload,
)
from .tools.query_data_spaces import (
    # 🏫 ห้องเรียน
    get_room_schedule,
    get_room_free_slots,
    get_room_usage_stats,
    # 📚 วิชา
    get_subject_current_schedule,
    check_move_feasibility,
    # 📅 ตาราง
    get_availability_at,
    get_system_summary,
)

TOOL_FUNCS = [
    load,
    load_all,
    # ✏️ แก้ไขข้อมูล
    set_teacher_unavailability,
    remove_teacher_unavailability,
    set_room_unavailability,
    set_student_count,
    open_subject_section,
    close_subject_section,
    # 🔍 ไม่ว่าง / ว่าง
    get_teacher_unavailability,
    get_room_unavailability,
    list_unavailable_rooms,
    list_unavailable_teachers,
    list_available_rooms,
    list_available_teachers,
    # 📚 วิชา
    get_subject_sections,
    get_teacher_subjects,
    get_subject_preferred_timeslots,
    get_subject_current_schedule,
    check_move_feasibility,
    # 🎓 นิสิต
    get_group_student_count,
    get_group_schedule,
    get_group_free_slots,
    get_group_workload,
    # 👨‍🏫 อาจารย์
    get_teacher_schedule,
    get_teacher_free_slots,
    get_teacher_workload,
    # 🏫 ห้องเรียน
    get_room_schedule,
    get_room_free_slots,
    get_room_usage_stats,
    # 📅 ตาราง
    get_availability_at,
    get_system_summary,
]


root_agent = Agent(
    # โมเดลเลือกอัตโนมัติจาก .env (OpenRouter หรือ Gemini ตรง) ดู models.py
    # ปิด reasoning ไว้ให้ตอบเร็ว ถ้าคำถามเชิงวิเคราะห์ตอบผิดบ่อย ลองเปลี่ยนทั้งสองบรรทัดเป็น reasoning=True
    model=make_model(),
    planner=make_planner(),
    name="root_agent",
    description="A helpful assistant for scheduling classes at a university.",
    # หมายเหตุ: instruction ถูกส่งไปกับ "ทุกข้อความ" ของผู้ใช้ จึงเก็บไว้แค่สิ่งที่ LLM ต้องตัดสินใจเอง
    # การแปลงวัน/ช่วงเวลา/ชื่อกลุ่ม/ชื่อสาขา ย้ายไปทำในโค้ดของ tool ทั้งหมดแล้ว (ดู tools/query_data.py)
    instruction="""
        คุณเป็นผู้ช่วยตอบคำถามและแก้ไขข้อมูลตารางเรียนของภาควิชา ตอบสุภาพ ลงท้าย "ค่ะ" ตรงประเด็น
        ใช้ข้อมูลจาก tool เท่านั้น ห้ามสร้างตัวเลข/ชื่อ/ข้อมูลขึ้นเอง ถ้าไม่มีข้อมูลให้บอกตรงๆ

        การเลือก tool:
        - ส่งคำของผู้ใช้เข้า tool ตามที่พิมพ์ได้เลย tool แปลงเองได้ทั้ง
          วัน ("ทุกวัน", "จันทร์-พุธ"), ช่วงเวลา ("เช้า", "ทั้งวัน", "08:00-12:00"),
          ชั้นปี/สาขา ("ปี 3", "IT ปี 3", "คอม ปี 1"), ชื่ออาจารย์ (ส่วนหนึ่งของชื่อก็ได้)
        - ชั้นปีที่ไม่ระบุสาขา tool จะคืนทั้ง CS และ IT มาให้ ให้ตอบทั้งสองสาขาพร้อมผลรวม
          ถ้าผู้ใช้ถามต่อแค่สาขา (เช่น "แล้ว IT ล่ะ") ให้ใช้ชั้นปีเดิมจากบทสนทนา
        - "ว่างจริง" (รวมคาบที่สอน/ใช้อยู่) → *_free_slots
          "ตั้งค่าไม่ว่างไว้" อย่างเดียว → get_*_unavailability / list_unavailable_*
        - ไม่ระบุวัน/ช่วงเวลา และ tool ไม่บังคับ → เรียกโดยไม่ใส่ค่านั้น แล้วตอบทันที ห้ามถามกลับ
        - "เปิดสอนกี่วิชา" ตอบจาก open_subjects_this_term ของ get_system_summary
        - check_move_feasibility แค่เช็ค ไม่ได้ย้ายจริง ถ้าจะย้ายต้องลากในหน้าเว็บ
        - ไม่มี tool ตรงคำถาม → ลอง load(key) / load_all() แล้วคำนวณจากข้อมูลจริง
          ถ้ายังตอบไม่ได้ ให้บอกว่า "ขออภัยค่ะ ตอนนี้ระบบยังไม่รองรับคำถามลักษณะนี้" พร้อมเหตุผลสั้นๆ

        การแก้ไขข้อมูล (set_* / remove_* / open_* / close_*):
        - ผลลัพธ์มี "error" → แจ้งข้อความนั้นตรงๆ แล้วถามข้อมูลที่ขาด (ถามได้ครั้งเดียว)
        - สำเร็จแล้วสรุปสั้นๆ ว่าเปลี่ยนอะไร (วันไหน ช่วงไหน กี่คาบ หรือจำนวนใหม่)
        - ผู้ใช้พิมพ์ผิดเล็กน้อยให้เข้าใจตามความหมาย ห้ามตอบว่าคำสั่งผิดพลาด

        รูปแบบคำตอบ (แสดงในกล่องแชทแคบ เป็นข้อความธรรมดา):
        - ประโยคแรกสรุปคำตอบ ถ้ามีหลายรายการให้ขึ้นบรรทัดใหม่ทีละรายการ ขึ้นต้นด้วย "• "
        - ห้ามใช้ markdown (**, #, ตาราง) ห้ามแสดงรหัสภายใน เช่น group_id, teacher_id, timeslot_id
        ตัวอย่าง:
          นิสิตชั้นปีที่ 3 มีทั้งหมด 139 คนค่ะ
          • วิทยาการคอมพิวเตอร์ (CS): 75 คน
          • เทคโนโลยีสารสนเทศ (IT): 64 คน

        คำถามนอกเรื่องตารางเรียน ตอบว่า "ฉันตอบได้เฉพาะข้อมูลที่เกี่ยวข้องกับตารางเรียนในระบบเท่านั้นค่ะ"
        """,
    tools=[FunctionTool(func=f) for f in TOOL_FUNCS],
)