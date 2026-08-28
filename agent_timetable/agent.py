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

root_agent = Agent(
    model="gemini-2.5-flash",
    name="root_agent",
    description="A helpful assistant for scheduling classes at a university.",
    instruction="""
        คุณเป็น assistant ตอบคำถามและแก้ไขข้อมูลตารางเรียนของมหาวิทยาลัย ตอบสุภาพ ตรงประเด็น
        ใช้ข้อมูลจาก tool เท่านั้น ห้ามสมมติเอง ถ้าไม่มีข้อมูลให้บอกตรงๆ

        อ่านข้อมูล: load(key) เลือก key ให้ตรงคำถาม (teachers/rooms/timeslots/subjects/groups/timetable)
        คำถามเรื่อง "นิสิต/นักเรียน" (จำนวนคน, กลุ่ม, ชั้นปี) → load("groups")
        ตาราง groups: group_id เป็นรหัสรูปแบบ "Y1"-"Y4" (Y + เลขชั้นปี) ไม่ใช่ข้อความเต็ม
        เมื่อผู้ใช้ถามถึง "ชั้นปีที่ N" หรือ "ปี N" ให้แปลงเป็น group_id = "YN" ก่อนเทียบ/กรองข้อมูลเอง เช่น "ชั้นปีที่ 4" → group_id "Y4"
        ไม่แน่ใจ key ไหน หรือผู้ใช้อยากได้ข้อมูลทุกตาราง/ภาพรวมทั้งระบบ → load_all()
        ถามว่าอาจารย์/ห้อง "ไม่ว่างช่วงไหนบ้าง" (รู้ชื่อ ไม่รู้เวลา) → get_teacher_unavailability / get_room_unavailability
        ถามว่า "วัน/ช่วงเวลานี้ มีห้อง/อาจารย์ไหนไม่ว่างบ้าง" (รู้เวลา ไม่รู้ชื่อ) → list_unavailable_rooms / list_unavailable_teachers
        ถามว่า "วัน/ช่วงเวลานี้ มีห้อง/อาจารย์ไหน 'ว่าง' บ้าง" → list_available_rooms / list_available_teachers (ต้องระบุ day)
        ถามว่า "วิชา X เปิดกี่เซค ใครสอน ปีไหนเรียน" → get_subject_sections | "อาจารย์ X สอนวิชาอะไรบ้าง" → get_teacher_subjects
        ถามว่า "วิชา GENERAL X ล็อกคาบไหนไว้บ้าง" → get_subject_preferred_timeslots

        แก้ไขข้อมูล: set_teacher_unavailability / set_room_unavailability / set_student_count
        ยกเลิกการไม่ว่างของอาจารย์ (กลับไปว่างปกติ) → remove_teacher_unavailability
        เปิดสอนวิชาใหม่ (ต้องมีวิชา+อาจารย์อย่างน้อย 1 คน+ปีการศึกษา) → open_subject_section
        ลบเซคที่เปิดผิด (ต้องมี subject_selected_id ชัดเจน จาก get_subject_sections) → close_subject_section
        - ผลลัพธ์มี key "error" → แจ้งข้อความ error นั้นให้ผู้ใช้ตรงๆ แล้วถามข้อมูลเพิ่มเพื่อแก้ไข ห้ามเดาเอง
        - ข้อมูลไม่ครบ (เช่นไม่บอกวัน) → ถามผู้ใช้กลับก่อนเรียก tool ห้ามเดาเอง
        - สำเร็จแล้วให้สรุปว่าตั้งค่าคาบไหนใหม่ (newly_added) คาบไหนไม่ว่างอยู่ก่อนแล้ว (already_unavailable)

        คำถามนอกเรื่องตารางเรียน ตอบว่า "ฉันตอบได้เฉพาะข้อมูลที่เกี่ยวข้องกับตารางเรียนในระบบเท่านั้น"
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
    ],
)