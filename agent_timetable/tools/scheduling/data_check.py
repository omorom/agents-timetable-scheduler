"""
data_check.py — ตรวจความพร้อมของข้อมูลก่อนจัดตาราง (Python ล้วน ใช้โดย DataGatherAgent)

ตรวจ 4 เรื่องที่ทำให้วิชาจัดไม่ได้แน่ หรือเสี่ยงจัดไม่ได้:
  1) วิชาที่ยังไม่ผูกอาจารย์ / กลุ่มนิสิต
  2) ไม่มีห้องประเภทที่ต้องใช้ที่จุนิสิตได้พอ
  3) ห้องที่ล็อกไว้ (fixed_room_id) หาไม่เจอในระบบ
  4) อาจารย์ต้องสอนเกินจำนวนคาบที่ว่าง / ว่างเหลือน้อยมาก
"""

from .load_data import get_cached_data
from .section_logic import build_session_list
from .slot_filter import _build_blocks

ROOM_LABEL = {"LECTURE": "ห้องบรรยาย", "LAB": "ห้องปฏิบัติการ"}


def _teacher_name(t: dict) -> str:
    for key in ("name", "full_name", "name_thai", "teacher_name"):
        if t.get(key):
            return str(t[key])
    full = f"{t.get('first_name') or ''} {t.get('last_name') or ''}".strip()
    return full or str(t.get("teacher_id"))


def check_data_readiness() -> list[dict]:
    """คืน list ของ {"id": "D1", "kind", "subject", "detail"} (id ให้ LLM อ้างถึงได้)"""
    data = get_cached_data()
    names = {s["subject_id"]: s.get("name_thai") or s.get("name_english") or s["subject_id"]
             for s in data["subjects"]}
    groups_map = {g["group_id"]: g["total_students"] for g in data["groups"]}
    room_ids = {r["room_id"] for r in data["rooms"]}
    issues: list[dict] = []

    def add(kind, subject, detail):
        issues.append({"id": f"D{len(issues) + 1}", "kind": kind, "subject": subject, "detail": detail})

    # 1) ยังไม่ผูกอาจารย์ / กลุ่มนิสิต
    for sec in data["sections"]:
        name = names.get(sec["subject_id"], sec["subject_id"])
        if not sec.get("teacher_ids"):
            add("no_teacher", name, "ยังไม่ได้ผูกอาจารย์ผู้สอน")
        if not sec.get("group_ids"):
            add("no_group", name, "ยังไม่ได้ผูกกลุ่มนิสิต (ระบบเช็คเวลาเรียนชนกันไม่ได้)")

    # 2) + 3) ห้อง — ตรวจต่อ session ไม่ซ้ำ (ประเภทห้อง + จำนวนคน + กลุ่ม)
    sessions = build_session_list()
    seen = set()
    for s in sessions:
        students = s.get("max_capacity") or sum(groups_map.get(g, 0) for g in s.get("group_ids") or [])
        key = (s["subject_id"], s["session_type"], s.get("fixed_room_id"), students, tuple(sorted(s.get("group_ids") or [])))
        if key in seen:
            continue
        seen.add(key)
        label = f"{names.get(s['subject_id'], s['subject_id'])} [{s['session_type']}]"

        if s.get("fixed_room_id"):
            if s["fixed_room_id"] not in room_ids:
                add("locked_room_missing", label,
                    f"ล็อกห้อง {s['fixed_room_id']} ไว้ แต่ไม่พบห้องนี้ในระบบ (อาจถูกลบหรือพิมพ์รหัสผิด)")
            continue
        same_type = [r["capacity"] for r in data["rooms"] if r["room_type"] == s["room_type"]]
        if not any(c >= students for c in same_type):
            add("no_room_big_enough", label,
                f"ต้องใช้{ROOM_LABEL.get(s['room_type'], 'ห้อง')}จุ {students} คน "
                f"แต่ห้องที่ใหญ่สุดจุ {max(same_type, default=0)} คน")

    # 4) คาบที่อาจารย์ต้องสอน เทียบกับคาบที่ว่าง (นับเป็น block 2 ชม.)
    blocks = _build_blocks(data["timeslots"])
    unavailable: dict[str, set] = {}
    for row in data["teacher_unavailability"]:
        unavailable.setdefault(row["teacher_id"], set()).add(str(row["timeslot_id"]))
    need: dict[str, int] = {}
    for s in sessions:
        size = -(-(s.get("continuous_size") or 2) // 2)   # เรียนรวด n ชม. = ceil(n/2) block
        for tid in s.get("teacher_ids") or []:
            need[tid] = need.get(tid, 0) + size
    teachers = {t["teacher_id"]: t for t in data["teachers"]}
    for tid, n in need.items():
        blocked = unavailable.get(tid, set())
        free = sum(1 for b in blocks if not any(ts in blocked for ts in b["timeslot_ids"]))
        who = _teacher_name(teachers.get(tid, {"teacher_id": tid}))
        if n > free:
            add("teacher_overbooked", None, f"อาจารย์ {who} ต้องสอน {n} คาบ แต่ตั้งเวลาว่างไว้แค่ {free} คาบ")
        elif blocked and free - n <= 1:
            add("teacher_tight", None, f"อาจารย์ {who} ต้องสอน {n} คาบ ว่าง {free} คาบ (เหลือที่ให้ระบบเลือกน้อยมาก)")

    return issues