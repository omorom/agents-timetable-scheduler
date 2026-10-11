"""
retry_hints.py — คำแนะนำจาก CheckerAgent ที่ใช้ตอนจัดซ้ำเฉพาะวิชาที่ยังไม่ลงตาราง

คำแนะนำมี 2 แบบ:
  1) priority_subject_ids — วิชาที่จัดไม่ได้ ให้ลองวางก่อนตัวอื่น (เรียงตามลำดับในลิสต์)
  2) forbidden — ห้าม session นี้ลงคาบเหล่านี้ {session_id: [timeslot_id, ...]}
     ใช้กับวิชาที่ขวางอยู่ ตอนหาที่ใหม่ให้มัน จะได้ไม่กลับไปทับคาบที่เพิ่งเปิดให้วิชาอื่น

เก็บแบบ module-level เพราะ get_valid_slots() ถูกเรียกจากหลายชั้นมาก ไม่อยากส่ง
parameter ทะลุทุกฟังก์ชัน — มีผลเฉพาะระหว่าง retry_failed_sessions() ทำงานเท่านั้น
(ตั้งค่าก่อนเริ่ม แล้วล้างทิ้งใน finally) การลากย้าย/สลับด้วยมือจึงไม่ถูกกระทบ

ไฟล์นี้ตั้งใจไม่ import อะไรในโปรเจกต์เลย กัน import วนกับ slot_filter.py
"""

_active: dict = {"priority_subject_ids": [], "forbidden": {}}


def empty_hints() -> dict:
    return {"priority_subject_ids": [], "forbidden": {}}


def set_active(hints: dict | None) -> None:
    global _active
    hints = hints or {}
    _active = {
        "priority_subject_ids": [str(s) for s in hints.get("priority_subject_ids") or []],
        "forbidden": {
            str(sid): {str(t) for t in ts_ids}
            for sid, ts_ids in (hints.get("forbidden") or {}).items()
        },
    }


def clear_active() -> None:
    set_active(None)


def forbidden_slots(session_id) -> set[str]:
    return _active["forbidden"].get(str(session_id), set())


def merge_hints(old: dict | None, priority_subject_ids: list, forbidden: dict) -> dict:
    """รวมคำแนะนำใหม่เข้ากับของเดิม (สะสมข้ามรอบ ไม่ล้างของเก่า กัน Agent แนะนำวนไปมา)
    วิชาที่เพิ่งแนะนำให้จัดก่อน ขึ้นไปอยู่หน้าสุด
    """
    old = old or empty_hints()
    prio = [str(s) for s in priority_subject_ids]
    prio += [s for s in old.get("priority_subject_ids", []) if s not in prio]

    merged = {k: list(v) for k, v in (old.get("forbidden") or {}).items()}
    for sid, ts_ids in forbidden.items():
        cur = merged.setdefault(str(sid), [])
        for t in ts_ids:
            if str(t) not in cur:
                cur.append(str(t))
    return {"priority_subject_ids": prio, "forbidden": merged}