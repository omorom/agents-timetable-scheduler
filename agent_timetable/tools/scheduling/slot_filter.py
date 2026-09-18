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

    student_count = session.get("max_capacity") or sum(groups_map.get(gid, 0) for gid in group_ids)

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


def _timeslots_by_day_sorted(timeslots: list[dict]) -> dict[str, list[dict]]:
    """คืน dict: day -> list of timeslot ดิบ (ไม่จับคู่เป็น block) เรียงตาม start_time
    ใช้สำหรับหา 'timeslot ติดกันตามเวลาจริง' ซึ่งรองรับทั้งจำนวนคู่และคี่
    (ต่างจาก _build_blocks ที่บังคับจับคู่ทีละ 2 เท่านั้น ใช้กับจำนวนคี่ไม่ได้)
    """
    by_day: dict[str, list[dict]] = {}
    for t in timeslots:
        by_day.setdefault(t["day"], []).append(t)
    for day in by_day:
        by_day[day].sort(key=lambda t: t["start_time"])
    return by_day


def _block_start_ids(timeslots: list[dict]) -> set[str]:
    """คืน set ของ timeslot_id ที่เป็น 'ตัวแรก' ของ block (คู่) ตามกฎมหาวิทยาลัย —
    คาบเรียนต้องเริ่มที่จุดเริ่มของคู่เท่านั้น (เช่น 08:00, 10:00, 13:00, 15:00)
    ห้ามเริ่มที่ตัวที่สองของคู่ (เช่น 09:00, 11:00, 14:00, 16:00) แม้เวลาจะติดกันจริง
    ก็ตาม ใช้กรอง 'จุดเริ่มที่อนุญาต' ของ get_valid_continuous_slots
    """
    grouped: dict[tuple, list[dict]] = {}
    for t in timeslots:
        grouped.setdefault((t["day"], t["block_id"]), []).append(t)

    starts: set[str] = set()
    for ts_list in grouped.values():
        if not ts_list:
            continue
        first = min(ts_list, key=lambda t: t["start_time"])
        starts.add(str(first["timeslot_id"]))
    return starts


def get_valid_continuous_slots(session: dict, num_units: int, limit: int | None = None) -> dict:
    data = get_cached_data()
    rooms = data["rooms"]
    timeslots = data["timeslots"]
    groups_map = {g["group_id"]: g["total_students"] for g in data["groups"]}

    first = session
    teacher_ids = first["teacher_ids"]
    group_ids = first["group_ids"]
    room_type_needed = first["room_type"]
    student_count = first.get("max_capacity") or sum(groups_map.get(gid, 0) for gid in group_ids)

    fixed_room_id = first.get("fixed_room_id")
    if fixed_room_id:
        candidate_rooms = [r for r in rooms if r["room_id"] == fixed_room_id]
        if not candidate_rooms:
            return {"error": f"ห้อง {fixed_room_id} ที่ล็อกไว้ ไม่พบในระบบ"}
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

    by_day = _timeslots_by_day_sorted(timeslots)
    block_start_ids = _block_start_ids(timeslots)  # ← จุดเริ่มที่อนุญาตตามกฎมหาลัย
    valid = []

    for day, day_slots in by_day.items():
        for i in range(len(day_slots) - num_units + 1):
            window = day_slots[i: i + num_units]

            # ต้องเริ่มที่จุดเริ่มของ block (คู่) เท่านั้น เช่น 08:00/10:00/13:00/15:00
            # ห้ามเริ่มที่ตัวที่สองของคู่ (09:00/11:00/14:00/16:00) แม้เวลาจะติดกันจริง
            if str(window[0]["timeslot_id"]) not in block_start_ids:
                continue

            # ต้องติดกันจริงตามเวลา (end_time ของตัวก่อนหน้า == start_time ของตัวถัดไป)
            # ไม่ใช่แค่ index ติดกันในลิสต์ (กันช่วงพักเที่ยง/ช่องว่างระหว่าง timeslot)
            contiguous = all(
                window[j]["end_time"] == window[j + 1]["start_time"]
                for j in range(len(window) - 1)
            )
            if not contiguous:
                continue

            all_ts_ids = [str(t["timeslot_id"]) for t in window]

            if teacher_ids and any(ts in busy_teacher_slots for ts in all_ts_ids):
                continue
            if group_ids and any(ts in busy_group_slots for ts in all_ts_ids):
                continue
            if teacher_ids and any(_teacher_unavailable_at(ts) for ts in all_ts_ids):
                continue

            for room in candidate_rooms:
                room_id = room["room_id"]
                if any((room_id, ts) in busy_rooms for ts in all_ts_ids):
                    continue
                if any(_room_unavailable_at(room_id, ts) for ts in all_ts_ids):
                    continue

                valid.append({
                    "day": day,
                    "room_id": room_id,
                    "room_name": room["room_name"],
                    "timeslot_ids": [str(t["timeslot_id"]) for t in window],  # ← แบนตรงๆ ให้ตรงกับ format ที่ pick_best_candidate คาดหวัง (เหมือน get_valid_slots ปกติ)
                })

    return {
        "session_id": session["session_id"],
        "valid_slots": valid if limit is None else valid[:limit],
        "count": len(valid),
    }