"""
routers/schedule.py — แทนที่ไฟล์เดิม (แก้ไขให้ครบทุก endpoint ที่เคยมี)

GET   /schedule                 ตารางที่ AI จัดล่าสุด (ใหม่ — ใช้ tools/scheduling)
GET   /existing                  ตารางเดิมแบบ flat list (ของเดิม ไม่เคยแก้ — คืนกลับมาแล้ว)
GET   /preferred-timeslots        คาบที่วิชา GENERAL ล็อกไว้ (ของเดิม ไม่เคยแก้ — คืนกลับมาแล้ว)
POST  /move                       ย้าย session (ลากบนกริด)
PATCH /schedule/{session_id}       แก้ไขห้อง/อาจารย์ (รองรับหลายอาจารย์ต่อ session แล้ว)
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent_timetable.tools.get_data import supabase, load
from agent_timetable.tools.scheduling.load_data import get_cached_data, refresh_cache
from agent_timetable.tools.scheduling.assignment_store import (
    get_current_schedule,
    manual_move_session,
    manual_edit_session,
)

router = APIRouter()


class MoveIn(BaseModel):
    session_id: str
    timeslot_id: str


class EditIn(BaseModel):
    room_id: str | None = None
    # รองรับหลายอาจารย์ต่อ session (team-teaching) — ไม่ระบุ = อาจารย์เดิมไม่เปลี่ยน
    # ระบุแล้ว = แทนที่อาจารย์เดิมทั้งหมดด้วยชุดนี้ (แม้จะระบุแค่คนเดียวก็ต้องส่งเป็น list)
    teacher_ids: list[str] | None = None


# ═══════════════════════════════════════════════════════════════
# GET /schedule — ตารางที่ AI จัดล่าสุด
# ═══════════════════════════════════════════════════════════════

@router.get("/schedule")
def get_schedule():
    try:
        refresh_cache()
        data = get_cached_data()
        schedule = get_current_schedule()

        subjects_by_id = {s["subject_id"]: s for s in data["subjects"]}
        rooms_by_id = {r["room_id"]: r["room_name"] for r in data["rooms"]}
        timeslots_by_id = {str(t["timeslot_id"]): t for t in data["timeslots"]}
        teachers_by_id = {t["teacher_id"]: t["teacher_name"] for t in data["teachers"]}

        result: dict[str, list] = {}
        for item in schedule:
            subject = subjects_by_id.get(item["subject_id"], {})
            teacher_ids = item.get("teacher_ids", [])
            teacher_names = [teachers_by_id.get(tid, tid) for tid in teacher_ids]

            # item["timeslot_ids"] มี 2 ตัวเสมอ (ทั้ง block) — หา timeslot object ของทั้งคู่
            # แล้วคำนวณช่วงเวลาเต็ม block (start ของตัวแรก ถึง end ของตัวสุดท้าย)
            ts_rows = [timeslots_by_id[str(tid)] for tid in item.get("timeslot_ids", []) if str(tid) in timeslots_by_id]
            ts_rows.sort(key=lambda t: t["start_time"])

            entry = {
                "session_id": item["session_id"],
                "subject_id": item["subject_id"],
                "subject_name": subject.get("name_thai") or subject.get("name_english") or item["subject_id"],
                # ─── field รายละเอียดวิชาเพิ่มเติม (สำหรับ modal ดูรายละเอียด/แก้ไข) ───
                "subject_name_english": subject.get("name_english"),
                "description_thai": subject.get("description_thai"),
                "description_english": subject.get("description_english"),
                "subject_type": subject.get("subject_type"),
                "semester": subject.get("semester"),
                "section": item.get("section"),
                # ────────────────────────────────────────────────────────────────
                "session_type": item["session_type"],
                "room_id": rooms_by_id.get(item["room_id"], item["room_id"]),
                "room_key": item["room_id"],
                "teacher_name": ", ".join(teacher_names) if teacher_names else "",
                # teacher_key: เก็บไว้เพื่อ backward-compat กับโค้ดเก่าที่อ้างอิงอาจารย์แค่คนเดียว
                "teacher_key": teacher_ids[0] if teacher_ids else None,
                # teacher_keys: รายชื่อ teacher_id ทุกคน — ใช้ prefill dropdown หลายอันในหน้าแก้ไข
                "teacher_keys": teacher_ids,
                "day": ts_rows[0]["day"] if ts_rows else None,
                "start_time": (ts_rows[0]["start_time"] if ts_rows else "")[:5],
                "end_time": (ts_rows[-1]["end_time"] if ts_rows else "")[:5],
            }

            for group_id in item.get("group_ids", []):
                result.setdefault(group_id, []).append(entry)

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════
# GET /existing — ตารางเดิมแบบ flat list (ของเดิม คืนกลับมาเหมือนเดิมทุกตัวอักษร)
# ═══════════════════════════════════════════════════════════════

@router.get("/existing")
def get_existing():
    """คืนตารางเรียนที่ AI จัดแล้วแบบ flat list (ใช้เป็น 'ช่วงไม่ว่างเดิม' ตอน generate ตารางรอบใหม่)"""
    try:
        return load("timetable")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════
# GET /preferred-timeslots — คาบที่วิชา GENERAL ล็อกไว้ (ของเดิม คืนกลับมาเหมือนเดิมทุกตัวอักษร)
# ═══════════════════════════════════════════════════════════════

@router.get("/preferred-timeslots")
def get_preferred_timeslots():
    """คืนคาบที่วิชา GENERAL แต่ละรอบ 'ล็อก' ไว้ พร้อม group_id และ subject_selected_id
    ให้ frontend เอาไป overlay บนกริด และเช็คตอนเลือกคาบใหม่ว่าชนกับที่ล็อกไว้แล้วหรือไม่
    """
    try:
        rows = (
            supabase.table("subject_selected_preferred_timeslots")
            .select(
                "timeslot_id, "
                "subject_selected(id, subjects(subject_id, name_thai, name_english, "
                "description_thai, description_english, subject_type, semester), "
                "subject_selected_groups(group_id))"
            )
            .execute()
            .data
        )
        timeslot_map = {t["timeslot_id"]: t for t in load("timeslots")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    result = []
    for row in rows:
        subject_selected = row.get("subject_selected") or {}
        subject = subject_selected.get("subjects") or {}
        groups = subject_selected.get("subject_selected_groups") or []
        timeslot = timeslot_map.get(row["timeslot_id"])
        if not timeslot:
            continue

        for group in groups:
            result.append(
                {
                    "subject_id": subject.get("subject_id"),
                    "subject_name": subject.get("name_thai"),
                    "subject_name_english": subject.get("name_english"),
                    "description_thai": subject.get("description_thai"),
                    "description_english": subject.get("description_english"),
                    "subject_type": subject.get("subject_type"),
                    "semester": subject.get("semester"),
                    "subject_selected_id": subject_selected.get("id"),
                    "group_id": group["group_id"],
                    "timeslot_id": row["timeslot_id"],
                    "day": timeslot["day"],
                    "start_time": timeslot["start_time"],
                    "end_time": timeslot["end_time"],
                }
            )
    return result


# ═══════════════════════════════════════════════════════════════
# POST /move — ย้าย session (ลากบนกริด)
# ═══════════════════════════════════════════════════════════════

@router.post("/move")
def move_schedule_item(body: MoveIn):
    try:
        result = manual_move_session(body.session_id, body.timeslot_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not result.get("success"):
        raise HTTPException(status_code=409, detail=result.get("reason", "ย้ายไม่สำเร็จ"))

    return result


# ═══════════════════════════════════════════════════════════════
# PATCH /schedule/{session_id} — แก้ไขห้อง/อาจารย์ (รองรับหลายอาจารย์)
# ═══════════════════════════════════════════════════════════════

@router.patch("/schedule/{session_id}")
def edit_schedule_item(session_id: str, body: EditIn):
    try:
        result = manual_edit_session(session_id, body.room_id, body.teacher_ids)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not result.get("success"):
        raise HTTPException(status_code=409, detail=result.get("reason", "แก้ไขไม่สำเร็จ"))

    return result


# ═══════════════════════════════════════════════════════════════
# POST /clear — ล้างตารางที่ AI จัดไว้ทั้งหมด (ไม่แตะ existing/GENERAL ที่ล็อกไว้)
# ═══════════════════════════════════════════════════════════════

@router.post("/clear")
def clear_schedule():
    try:
        from agent_timetable.tools.scheduling.auto_assign import reset_ai_schedule
        reset_ai_schedule()
        return {"status": "ok", "message": "ล้างตารางที่ AI จัดไว้เรียบร้อยแล้ว"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))