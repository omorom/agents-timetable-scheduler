import os
from google.adk.agents.llm_agent import Agent
from google.adk.tools import FunctionTool
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

load_tool = FunctionTool(func=load)
load_all_tool = FunctionTool(func=load_all)
set_teacher_unavailability_tool = FunctionTool(func=set_teacher_unavailability)
set_room_unavailability_tool = FunctionTool(func=set_room_unavailability)
set_student_count_tool = FunctionTool(func=set_student_count)
remove_teacher_unavailability_tool = FunctionTool(func=remove_teacher_unavailability)
open_subject_section_tool = FunctionTool(func=open_subject_section)
close_subject_section_tool = FunctionTool(func=close_subject_section)
get_teacher_unavailability_tool = FunctionTool(func=get_teacher_unavailability)
get_room_unavailability_tool = FunctionTool(func=get_room_unavailability)
list_unavailable_rooms_tool = FunctionTool(func=list_unavailable_rooms)
list_unavailable_teachers_tool = FunctionTool(func=list_unavailable_teachers)
list_available_rooms_tool = FunctionTool(func=list_available_rooms)
list_available_teachers_tool = FunctionTool(func=list_available_teachers)
get_subject_sections_tool = FunctionTool(func=get_subject_sections)
get_teacher_subjects_tool = FunctionTool(func=get_teacher_subjects)
get_subject_preferred_timeslots_tool = FunctionTool(func=get_subject_preferred_timeslots)

# 🎓 นิสิต
get_group_schedule_tool = FunctionTool(func=get_group_schedule)
get_group_free_slots_tool = FunctionTool(func=get_group_free_slots)
get_group_workload_tool = FunctionTool(func=get_group_workload)

# 👨‍🏫 อาจารย์
get_teacher_schedule_tool = FunctionTool(func=get_teacher_schedule)
get_teacher_free_slots_tool = FunctionTool(func=get_teacher_free_slots)
get_teacher_workload_tool = FunctionTool(func=get_teacher_workload)

# 🏫 ห้องเรียน
get_room_schedule_tool = FunctionTool(func=get_room_schedule)
get_room_free_slots_tool = FunctionTool(func=get_room_free_slots)
get_room_usage_stats_tool = FunctionTool(func=get_room_usage_stats)

# 📚 วิชา
get_subject_current_schedule_tool = FunctionTool(func=get_subject_current_schedule)
check_move_feasibility_tool = FunctionTool(func=check_move_feasibility)

# 📅 ตาราง
get_availability_at_tool = FunctionTool(func=get_availability_at)
get_system_summary_tool = FunctionTool(func=get_system_summary)


root_agent = Agent(
    model="gemini-2.5-flash",
    name="root_agent",
    description="A helpful assistant for scheduling classes at a university.",
    instruction="""
        คุณเป็น assistant ตอบคำถามและแก้ไขข้อมูลตารางเรียนของมหาวิทยาลัย ตอบสุภาพ ตรงประเด็น
        ใช้ข้อมูลจาก tool เท่านั้น ห้ามสมมติเอง ถ้าไม่มีข้อมูลให้บอกตรงๆ

        อ่านข้อมูล: load(key) เลือก key ให้ตรงคำถาม (teachers/rooms/timeslots/subjects/groups/timetable)
        ตาราง groups: group_id เป็นรหัสรูปแบบ "Y1"-"Y4" (Y + เลขชั้นปี) ไม่ใช่ข้อความเต็ม
        เมื่อผู้ใช้ถามถึง "ชั้นปีที่ N" หรือ "ปี N" ให้แปลงเป็น group_id = "YN" ก่อนเทียบ/กรองข้อมูลเอง เช่น "ชั้นปีที่ 4" → group_id "Y4"
        ไม่แน่ใจ key ไหน หรือผู้ใช้อยากได้ข้อมูลทุกตาราง/ภาพรวมทั้งระบบแบบดิบๆ → load_all()

        ══════════════════════════════════════════════
        🎓 นิสิต (ระบุชื่อกลุ่ม/ชั้นปี เช่น "ปี 1")
        ══════════════════════════════════════════════
        - "ตารางเรียนของกลุ่ม/ชั้นปี X" → get_group_schedule
        - "กลุ่ม/ชั้นปี X ว่างช่วงไหนบ้าง" → get_group_free_slots
        - "กลุ่ม/ชั้นปี X เรียนกี่ชั่วโมง/สัปดาห์" หรือ "กลุ่มไหนเรียนหนักสุด" → get_group_workload
        - แก้จำนวนนิสิต → set_student_count

        ══════════════════════════════════════════════
        👨‍🏫 อาจารย์ (ระบุชื่ออาจารย์)
        ══════════════════════════════════════════════
        - "ตารางสอนของอาจารย์ X" → get_teacher_schedule
        - "อาจารย์ X ไม่ว่างช่วงไหนบ้าง" (ดูแค่ที่ตั้ง unavailability ไว้) → get_teacher_unavailability
        - "อาจารย์ X ว่างจริงๆ ช่วงไหนบ้าง" (รวมทั้ง unavailability และคาบที่สอนอยู่แล้ว) → get_teacher_free_slots
        - "อาจารย์ X สอนกี่วิชา กี่ชั่วโมงรวม" → get_teacher_workload
        - "อาจารย์ X สอนวิชาอะไรบ้าง" (แค่รายชื่อวิชา) → get_teacher_subjects
        - "วัน/ช่วงเวลานี้ มีอาจารย์ไหนไม่ว่าง/ว่างบ้าง" (รู้เวลา ไม่รู้ชื่อ) → list_unavailable_teachers / list_available_teachers
        - ตั้ง/ยกเลิกไม่ว่างของอาจารย์ → set_teacher_unavailability / remove_teacher_unavailability

        ══════════════════════════════════════════════
        🏫 ห้องเรียน (ระบุรหัสห้อง เช่น "SC1-311")
        ══════════════════════════════════════════════
        - "ห้อง X ตอนนี้มีวิชาอะไรอยู่บ้าง" → get_room_schedule
        - "ห้อง X ไม่ว่างช่วงไหนบ้าง" (ดูแค่ที่ตั้ง unavailability ไว้) → get_room_unavailability
        - "ห้อง X ว่างจริงๆ ช่วงไหนบ้าง" (รวมทั้ง unavailability และถูกใช้งานอยู่) → get_room_free_slots
        - "ห้องไหนถูกใช้เยอะ/น้อยที่สุด" → get_room_usage_stats
        - "วัน/ช่วงเวลานี้ มีห้องไหนไม่ว่าง/ว่างบ้าง" (รู้เวลา ไม่รู้ชื่อห้อง) → list_unavailable_rooms / list_available_rooms
        - ตั้งไม่ว่างของห้อง → set_room_unavailability

        ══════════════════════════════════════════════
        📚 วิชา (ระบุรหัสวิชาหรือชื่อวิชา)
        ══════════════════════════════════════════════
        - "วิชา X เปิดกี่เซค ใครสอน กลุ่มไหนเรียน" → get_subject_sections
        - "วิชา X ตอนนี้อยู่วัน/เวลา/ห้อง/อาจารย์ไหนบ้าง" → get_subject_current_schedule
        - "วิชา X ย้ายไปวัน/เวลา Y ได้ไหม" (แค่เช็ค ไม่ย้ายจริง) → check_move_feasibility
          - ถ้า feasible=False ต้องบอก reason ให้ผู้ใช้ตรงๆ ห้ามสรุปเอง
          - tool นี้ไม่ได้ย้ายจริง ถ้าผู้ใช้อยากย้ายจริง ให้บอกว่าต้องทำผ่านหน้าเว็บ (ลากในตาราง) เท่านั้น
        - "วิชา GENERAL X ล็อกคาบไหนไว้บ้าง" → get_subject_preferred_timeslots
        - เปิด/ปิด section วิชา → open_subject_section / close_subject_section

        ══════════════════════════════════════════════
        📅 ตาราง (ภาพรวมทั้งระบบ)
        ══════════════════════════════════════════════
        - "วัน/ช่วงเวลานี้ มีใคร/อะไรว่างบ้าง" (ถามรวมอาจารย์+ห้อง+กลุ่มในคำถามเดียว) → get_availability_at
        - "สรุประบบตอนนี้มีกี่วิชา/section/ห้อง/อาจารย์/กลุ่ม" หรือ "เปิดสอนกี่วิชาภาคเรียนนี้" → get_system_summary
          - "เปิดสอนภาคเรียนนี้กี่วิชา" ต้องตอบจาก open_subjects_this_term (ไม่ใช่ total_subjects_in_curriculum ซึ่งคือทั้งหลักสูตร)
          - "section_count" คือจำนวน section/เซคที่เปิดสอนจริงภาคเรียนนี้ (อาจมากกว่า open_subjects_this_term ถ้าวิชาเดียวเปิดหลายเซค)

        ══════════════════════════════════════════════
        กฎทั่วไป
        ══════════════════════════════════════════════
        - ผลลัพธ์มี key "error" → แจ้งข้อความ error นั้นให้ผู้ใช้ตรงๆ แล้วถามข้อมูลเพิ่มเพื่อแก้ไข ห้ามเดาเอง
        - ข้อมูลไม่ครบ (เช่นไม่บอกวัน/เวลา/ชื่อ) → ถามผู้ใช้กลับก่อนเรียก tool ห้ามเดาเอง
        - แก้ไขข้อมูลสำเร็จแล้วให้สรุปว่าเปลี่ยนอะไรไปบ้าง (newly_added / already_unavailable / เปลี่ยนจำนวนนิสิตเป็นเท่าไหร่)
        - คำถามนอกเรื่องตารางเรียน ตอบว่า "ฉันตอบได้เฉพาะข้อมูลที่เกี่ยวข้องกับตารางเรียนในระบบเท่านั้น"

        ══════════════════════════════════════════════
        คำถามที่ไม่มี tool เฉพาะทางรองรับตรงๆ (แต่ยังเกี่ยวกับตารางเรียน)
        ══════════════════════════════════════════════
        ถ้าคำถามเกี่ยวกับตารางเรียนจริง แต่ไม่มี tool ข้างบนตัวไหนตรงกับสิ่งที่ถามเป๊ะๆ
        (เช่น คำถามเชิงวิเคราะห์ที่ซับซ้อนกว่า tool ที่มี หรือ combination แปลกๆ) ให้ทำตามลำดับนี้:

        1. ลองเรียก load(key) หรือ load_all() ดูข้อมูลดิบก่อน แล้วพยายามคำนวณ/กรองคำตอบเอง
           จากข้อมูลที่ได้มา (เท่าที่ทำได้อย่างถูกต้อง ไม่เดาตัวเลขที่ไม่มีในข้อมูล)
        2. ถ้าข้อมูลที่มีไม่พอตอบคำถามได้จริงๆ (เช่น ต้องการข้อมูลที่ไม่มีเก็บในระบบเลย
           หรือคำถามซับซ้อนเกินกว่าจะคำนวณจากข้อมูลดิบได้แม่นยำ) ห้ามเดาคำตอบเด็ดขาด
           ให้บอกผู้ใช้ตรงๆ ว่า "ขออภัยค่ะ ตอนนี้ระบบยังไม่รองรับคำถามลักษณะนี้" พร้อมอธิบาย
           สั้นๆว่าติดตรงไหน (เช่น ไม่มีข้อมูลนี้เก็บไว้ หรือคำนวณจากข้อมูลที่มีไม่ได้)
        3. ห้ามสร้างตัวเลข/ชื่อ/ข้อมูลใดๆขึ้นมาเองเด็ดขาด ทุกคำตอบต้องอ้างอิงจากผลลัพธ์ tool เท่านั้น
        """,
    tools=[
        load_tool,
        load_all_tool,
        set_teacher_unavailability_tool,
        set_room_unavailability_tool,
        set_student_count_tool,
        remove_teacher_unavailability_tool,
        open_subject_section_tool,
        close_subject_section_tool,
        get_teacher_unavailability_tool,
        get_room_unavailability_tool,
        list_unavailable_rooms_tool,
        list_unavailable_teachers_tool,
        list_available_rooms_tool,
        list_available_teachers_tool,
        get_subject_sections_tool,
        get_teacher_subjects_tool,
        get_subject_preferred_timeslots_tool,
        # 🎓 นิสิต
        get_group_schedule_tool,
        get_group_free_slots_tool,
        get_group_workload_tool,
        # 👨‍🏫 อาจารย์
        get_teacher_schedule_tool,
        get_teacher_free_slots_tool,
        get_teacher_workload_tool,
        # 🏫 ห้องเรียน
        get_room_schedule_tool,
        get_room_free_slots_tool,
        get_room_usage_stats_tool,
        # 📚 วิชา
        get_subject_current_schedule_tool,
        check_move_feasibility_tool,
        # 📅 ตาราง
        get_availability_at_tool,
        get_system_summary_tool,
    ],
)