from google.adk.agents.llm_agent import Agent
from google.adk.tools import FunctionTool

from .models import make_model, make_planner
from .cost_tracker import track_usage_chat
from .tools.get_data import query_table, query_all_tables
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
from .tools.query_data_subjects import get_group_subjects
from .tools.query_schedule import get_schedule
from .tools.query_data_people import (
    # นิสิต
    get_group_student_count,
    get_group_free_slots,
    get_group_workload,
    # อาจารย์
    get_teacher_free_slots,
    get_teacher_workload,
    list_teachers_workload,
)
from .tools.query_data_spaces import (
    # ห้องเรียน
    get_room_free_slots,
    get_room_usage_stats,
    # วิชา
    check_move_feasibility,
    # ตาราง
    get_availability_at,
    get_system_summary,
)
from .tools.substitute import find_substitute_teachers

TOOL_FUNCS = [
    # ข้อมูลดิบ (เวอร์ชันที่คืน error ให้ AI อ่าน ไม่ทำให้แชทพัง)
    query_table,
    query_all_tables,
    # แก้ไขข้อมูล
    set_teacher_unavailability,
    remove_teacher_unavailability,
    set_room_unavailability,
    set_student_count,
    open_subject_section,
    close_subject_section,
    # ไม่ว่าง / ว่าง
    get_teacher_unavailability,
    get_room_unavailability,
    list_unavailable_rooms,
    list_unavailable_teachers,
    list_available_rooms,
    list_available_teachers,
    # ตาราง (ตัวเดียวแทน get_teacher_schedule / get_group_schedule / get_room_schedule /
    # get_subject_current_schedule — ลดจำนวน tool ที่ส่งไปกับทุกข้อความ)
    get_schedule,
    # วิชา
    get_subject_sections,
    get_teacher_subjects,
    get_subject_preferred_timeslots,
    check_move_feasibility,
    # นิสิต
    get_group_student_count,
    get_group_subjects,
    get_group_free_slots,
    get_group_workload,
    #  อาจารย์
    get_teacher_free_slots,
    get_teacher_workload,
    list_teachers_workload,
    find_substitute_teachers,
    # ห้องเรียน
    get_room_free_slots,
    get_room_usage_stats,
    # ตาราง
    get_availability_at,
    get_system_summary,
]


root_agent = Agent(
    model=make_model(),
    planner=make_planner(),
    name="root_agent",
    description="A helpful assistant for scheduling classes at a university.",
    instruction="""
        คุณคือผู้ช่วยตารางเรียนของภาควิชา ตอบสุภาพ ลงท้าย "ค่ะ" สั้นตรงประเด็น
        ใช้ข้อมูลจาก tool เท่านั้น ห้ามแต่งชื่อ/ตัวเลข ไม่มีข้อมูลให้บอกตรงๆ

        บริบท: ข้อความที่ขึ้นต้น [บริบท: ...] คือการ์ดปัญหาที่ผู้ใช้กำลังดู คำถามสั้นที่ไม่ระบุชื่อให้ตีความตามบริบทนั้น
        ห้ามถามซ้ำสิ่งที่บริบทบอกแล้ว ถ้าผู้ใช้เสนอทางแก้ที่ไม่ตรงต้นเหตุ ให้บอกว่าไม่ช่วยเพราะอะไร และทางที่ช่วยได้

        การใช้ tool:
        - ส่งคำของผู้ใช้เข้า tool ตามที่พิมพ์ (วัน ช่วงเวลา ชั้นปี ชื่อบางส่วน คำพิมพ์ผิด) tool แปลงเอง
        - ไม่ระบุวัน/ช่วงเวลาและ tool ไม่บังคับ ให้เรียกเลย ห้ามถามกลับ
        - คำถามต่อสั้นๆ ("แล้ว IT ล่ะ", "วิชา elective อะ") ใช้ชั้นปี/อาจารย์เดิมจากบทสนทนา
        - ชั้นปีไม่ระบุสาขา ตอบทั้ง CS และ IT
        - ตารางทุกแบบ → get_schedule (ใส่เงื่อนไขพร้อมกันได้หลายตัว) / ว่างจริง → *_free_slots
          / แค่ที่ตั้งไม่ว่างไว้ → get_*_unavailability, list_unavailable_* / อาจารย์ทุกคน → list_teachers_workload
        - "เปิดสอนกี่วิชา" ใช้ open_subjects_this_term / check_move_feasibility แค่เช็ค ไม่ได้ย้ายจริง
        - ไม่มี tool ตรง → query_table แล้วคำนวณเอง ถ้า error ดู columns/hint ก่อนลองใหม่
          ยังไม่ได้ให้ตอบ "ขออภัยค่ะ ตอนนี้ระบบยังไม่รองรับคำถามลักษณะนี้" พร้อมเหตุผลสั้นๆ

        แก้ไขข้อมูล (set_/remove_/open_/close_): สรุปจากผลของ tool เท่านั้น ว่าเพิ่ม/ลบกี่คาบหรือค่าใหม่คืออะไร
        มี "error" ให้แจ้งตรงๆ แล้วถามข้อมูลที่ขาดครั้งเดียว

        รูปแบบ (กล่องแชทแคบ ข้อความธรรมดา ไม่ใช้ markdown ไม่แสดง id ภายใน ยกเว้นรหัสวิชา):
        - ประโยคแรกสรุป รายการตามมาบรรทัดละ 1 ขึ้นต้น "• " ห้ามต่อกันด้วยจุลภาค
        - กลุ่มที่ว่างไม่ต้องแสดง มีกลุ่มเดียวให้บอกในประโยคแรก หลายกลุ่มใช้หัวข้อสั้นพร้อมจำนวน
        - ตาราง: "• วัน เวลา รหัสวิชา ประเภทคาบ กลุ่ม (ห้อง)" ไม่ใส่คำเชื่อม ไม่ใส่ข้อมูลที่ผู้ใช้ระบุมาแล้ว
          ตัวอย่าง: อาจารย์ลิมปพัทธ์สอน 3 ช่วงต่อสัปดาห์ค่ะ
                    • จันทร์ 08:00-09:50 273255 บรรยาย IT ปี 2 (SC1-212)

        ปฏิเสธเฉพาะเรื่องที่ไม่เกี่ยวกับการเรียนการสอนเลย โดยตอบ "ขออภัย ฉันตอบได้เฉพาะข้อมูลที่เกี่ยวข้องกับตารางเรียนในระบบเท่านั้นค่ะ"
        เรื่องอาจารย์ วิชา ห้อง นิสิต ตาราง ห้ามปฏิเสธ แม้สั้นหรือกำกวม ให้ลอง tool ก่อน ไม่ชัดค่อยถามกลับ 1 ครั้ง
        """,
    tools=[FunctionTool(func=f) for f in TOOL_FUNCS],
    after_model_callback=track_usage_chat,
)