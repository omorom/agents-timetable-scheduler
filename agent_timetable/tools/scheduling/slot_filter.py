"""
slot_filter.py
หา "block" (2 timeslot ที่อยู่ block_id เดียวกัน) ที่ session หนึ่งวางได้ทั้งคู่พร้อมกัน
โดยไม่ชนกับห้อง/อาจารย์/กลุ่มที่จองแล้ว หรือ teacher_unavailability/room_unavailability

สำคัญ: 1 session (LECTURE หรือ LAB) = 1 block เสมอ = 2 timeslot ที่อยู่ block_id เดียวกัน
ห้ามเลือก 2 timeslot ที่คร่อมข้าม block (เช่น timeslot ตัวสุดท้ายของ block 1
กับตัวแรกของ block 2) ต้องเป็น 2 timeslot ที่มี block_id เท่ากันเป๊ะเท่านั้น
"""

from .load_data import get_cached_data
from .section_logic import build_session_list


def _timeslot_label(timeslot_ids: list[str], timeslots: list[dict]) -> str:
    ts_list = [t for t in timeslots if str(t["timeslot_id"]) in timeslot_ids]
    if not ts_list:
        return "-"
    ts_list.sort(key=lambda t: t["start_time"])
    return f"{ts_list[0]['day']} {ts_list[0]['start_time']}-{ts_list[-1]['end_time']}"


def _build_blocks(timeslots: list[dict]) -> list[dict]:
    """จัดกลุ่ม timeslot ตาม (day, block_id) คืนเฉพาะ block ที่มีครบ 2 timeslot เท่านั้น"""
    grouped: dict[tuple, list[dict]] = {}
    for t in timeslots:
        grouped.setdefault((t["day"], t["block_id"]), []).append(t)

    blocks = []
    for (day, block_id), ts_list in grouped.items():
        if len(ts_list) != 2:
            continue  # block ไม่ครบ 2 timeslot ข้ามไป (กันข้อมูลผิดปกติ)
        ts_list.sort(key=lambda t: t["start_time"])
        blocks.append({
            "day": day,
            "block_id": block_id,
            "timeslot_ids": [str(ts_list[0]["timeslot_id"]), str(ts_list[1]["timeslot_id"])],
        })
    return blocks


def get_valid_slots(session_id: str, limit: int | None = 10) -> dict:
    data = get_cached_data()
    rooms = data["rooms"]
    timeslots = data["timeslots"]
    groups_map = {g["group_id"]: g["total_students"] for g in data["groups"]}

    sessions = {s["session_id"]: s for s in build_session_list()}
    session = sessions.get(session_id)
    if not session:
        return {"error": f"ไม่พบ session {session_id}"}

    teacher_ids = session["teacher_ids"]
    group_ids = session["group_ids"]
    room_type_needed = session["room_type"]

    # max_capacity ถูกคำนวณให้ถูกต้องแล้วต่อ session ตั้งแต่ section_logic.py (แยกตามเหตุผล
    # ที่ทำให้เกิด session นี้ — parallel/team-teaching/capacity-split แต่ละแบบคำนวณต่างกัน)
    # ไม่ต้องหารซ้ำที่นี่อีก (เดิมเคยหารครึ่งอัตโนมัติทุกครั้งที่ session มี "section" ซึ่งผิด
    # เพราะ parallel case ค่า max_capacity ต่อแถวถูกต้องอยู่แล้ว ไม่ควรหารซ้ำ)
    student_count = session.get("max_capacity") or sum(groups_map.get(gid, 0) for gid in group_ids)

    # ห้องที่ถูกล็อกตายตัวไว้ (ตั้งค่าไว้ที่ subject_selected.fixed_room_id เฉพาะ LAB)
    # ถ้ามีค่า -> บังคับใช้ห้องนั้นห้องเดียวเท่านั้น ข้ามการกรองด้วย room_type/capacity
    # ตามปกติไปเลย (ถือว่าผู้ใช้ตั้งใจล็อกไว้แล้ว รู้อยู่แล้วว่าห้องนี้มีอุปกรณ์ที่ต้องใช้)
    # ยังคงเช็คว่า "ห้องว่างจริงไหมในคาบนั้น" ตามปกติอยู่ ไม่ได้ข้ามการเช็คชนกัน
    fixed_room_id = session.get("fixed_room_id")
    if fixed_room_id:
        candidate_rooms = [r for r in rooms if r["room_id"] == fixed_room_id]
        if not candidate_rooms:
            return {"error": f"ห้อง {fixed_room_id} ที่ล็อกไว้สำหรับ session นี้ ไม่พบในระบบ (ถูกลบไปหรือพิมพ์รหัสผิด)"}
    else:
        candidate_rooms = [
            r for r in rooms
            if r["room_type"] == room_type_needed and r["capacity"] >= student_count
        ]

    current = data["existing"] + data["assignments"]

    busy_rooms = {(a["room_id"], str(a["timeslot_id"])) for a in current if a.get("room_id")}
    busy_teacher_slots = {str(a["timeslot_id"]) for a in current if a.get("teacher_id") in teacher_ids}
    busy_group_slots = {str(a["timeslot_id"]) for a in current if a.get("group_id") in group_ids}

    unavailable_teacher_slots: dict[str, set] = {}
    for row in data["teacher_unavailability"]:
        unavailable_teacher_slots.setdefault(row["teacher_id"], set()).add(str(row["timeslot_id"]))

    unavailable_room_slots: dict[str, set] = {}
    for row in data["room_unavailability"]:
        unavailable_room_slots.setdefault(row["room_id"], set()).add(str(row["timeslot_id"]))

    def _teacher_unavailable_at(ts_id: str) -> bool:
        return any(ts_id in unavailable_teacher_slots.get(tid, set()) for tid in teacher_ids)

    def _room_unavailable_at(room_id, ts_id: str) -> bool:
        return ts_id in unavailable_room_slots.get(room_id, set())

    blocks = _build_blocks(timeslots)
    valid = []

    # หาว่า "พี่น้อง" (sibling_key เดียวกัน) ถูกจัดไปวันไหนแล้วบ้าง — ห้ามซ้ำวันกัน
    sibling_key = session.get("sibling_key")
    used_days = set()
    if sibling_key:
        sessions_by_id = sessions
        for row in current:
            sid = row.get("session_id")
            if not sid or sid == session_id:
                continue
            sibling_session = sessions_by_id.get(sid)
            if sibling_session and sibling_session.get("sibling_key") == sibling_key:
                ts = next((t for t in timeslots if str(t["timeslot_id"]) == str(row["timeslot_id"])), None)
                if ts:
                    used_days.add(ts["day"])

    for block in blocks:
        ts_ids = block["timeslot_ids"]

        if sibling_key and block["day"] in used_days:
            continue  # วันนี้พี่น้อง (block อื่นของวิชา+session_type เดียวกัน) จองไปแล้ว ข้าม

        # ทั้ง 2 timeslot ใน block ต้องผ่านเงื่อนไขอาจารย์/กลุ่ม/ไม่ว่าง พร้อมกันทั้งคู่
        if teacher_ids and any(ts in busy_teacher_slots for ts in ts_ids):
            continue
        if group_ids and any(ts in busy_group_slots for ts in ts_ids):
            continue
        if teacher_ids and any(_teacher_unavailable_at(ts) for ts in ts_ids):
            continue

        for room in candidate_rooms:
            room_id = room["room_id"]
            # ห้องต้องว่างทั้ง 2 timeslot ของ block นี้พร้อมกัน
            if any((room_id, ts) in busy_rooms for ts in ts_ids):
                continue
            if any(_room_unavailable_at(room_id, ts) for ts in ts_ids):
                continue

            valid.append({
                "timeslot_ids": ts_ids,          # ← ทั้ง block (2 ตัว) ไม่ใช่ตัวเดียว
                "timeslot_label": _timeslot_label(ts_ids, timeslots),
                "room_id": room_id,
                "room_name": room["room_name"],
                "day": block["day"],
                "block_id": block["block_id"],
            })

    return {
        "session_id": session_id,
        "subject_id": session["subject_id"],
        "section": session.get("section"),
        "valid_slots": valid if limit is None else valid[:limit],
        "count": len(valid),
    }