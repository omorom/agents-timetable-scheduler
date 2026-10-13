"""
substitute.py — หาอาจารย์ที่สอนแทนได้ (tool ของแชทบอท)

ระบบไม่มีข้อมูลว่าอาจารย์คนไหน "มีความเชี่ยวชาญ" สอนวิชาไหนได้
จึงใช้เกณฑ์ที่ตรวจได้จากข้อมูลจริงเท่านั้น:
  1) มีเวลาว่างพอ: คาบว่าง (หลังหักคาบที่ตั้งไม่ว่าง) - คาบที่ต้องสอนอยู่แล้ว >= คาบของวิชาที่จะรับเพิ่ม
  2) จัดอันดับให้คนที่ "สอนวิชานี้อยู่แล้ว" (section อื่น) ขึ้นก่อน เพราะสอนแทนได้แน่
     คนที่เหลือบอกตรงๆ ว่าว่างพอ แต่ต้องให้ผู้ใช้ดูความเหมาะสมเอง

วางไฟล์นี้ไว้ที่ agent_timetable/tools/substitute.py
"""

from .scheduling.load_data import refresh_cache
from .scheduling.section_logic import build_session_list
from .scheduling.slot_filter import _build_blocks
from .scheduling.data_check import _teacher_name, _blocks_of

MAX_CANDIDATES = 5


def find_substitute_teachers(teacher_name: str, subject: str = "") -> dict:
    """หาอาจารย์ที่มีเวลาว่างพอจะสอนแทนอาจารย์คนหนึ่ง

    teacher_name: ชื่ออาจารย์ที่ต้องการหาคนสอนแทน (ส่วนหนึ่งของชื่อก็ได้ เช่น "ลิมปพัทธ์")
    subject: รหัสหรือชื่อวิชา ถ้าว่าง = หาให้ทุกวิชาที่อาจารย์คนนี้สอน
    คืนรายชื่ออาจารย์ที่ว่างพอ เรียงจากเหมาะที่สุด พร้อมเหตุผล
    """
    data = refresh_cache()
    teachers = {t["teacher_id"]: t for t in data["teachers"]}
    names = {s["subject_id"]: str(s.get("name_thai") or s.get("name_english") or s["subject_id"]).strip()
             for s in data["subjects"]}
    sessions = build_session_list()
    blocks = _build_blocks(data["timeslots"])

    key = (teacher_name or "").strip()
    target = [tid for tid, t in teachers.items() if key and key in _teacher_name(t)]
    if not target:
        return {"error": f"ไม่พบอาจารย์ชื่อ \"{teacher_name}\""}
    if len(target) > 1:
        return {"error": "พบอาจารย์หลายคนที่ชื่อตรงกัน กรุณาระบุชื่อให้ชัดขึ้น",
                "matches": [_teacher_name(teachers[t]) for t in target]}
    tid = target[0]

    unavail: dict[str, set] = {}
    for row in data["teacher_unavailability"]:
        unavail.setdefault(row["teacher_id"], set()).add(str(row["timeslot_id"]))

    def free_count(t: str) -> int:
        blocked = unavail.get(t, set())
        return sum(1 for b in blocks if not any(ts in blocked for ts in b["timeslot_ids"]))

    need: dict[str, int] = {}
    for s in sessions:
        for t in s.get("teacher_ids") or []:
            need[t] = need.get(t, 0) + _blocks_of(s)

    # วิชาที่อาจารย์คนนี้สอน (กรองตาม subject ถ้าระบุมา)
    mine: dict[str, int] = {}
    for s in sessions:
        if tid in (s.get("teacher_ids") or []):
            sid = s["subject_id"]
            if subject and subject not in sid and subject not in names.get(sid, ""):
                continue
            mine[sid] = mine.get(sid, 0) + _blocks_of(s)
    if not mine:
        return {"error": f"ไม่พบวิชา \"{subject}\" ที่ {_teacher_name(teachers[tid])} สอน" if subject
                else f"{_teacher_name(teachers[tid])} ยังไม่มีวิชาที่ต้องสอนในเทอมนี้"}

    results = []
    for sid, blocks_needed in mine.items():
        already = {t for s in sessions if s["subject_id"] == sid for t in (s.get("teacher_ids") or []) if t != tid}
        cands = []
        for t in teachers:
            if t == tid:
                continue
            spare = free_count(t) - need.get(t, 0)
            if spare < blocks_needed:
                continue
            cands.append({
                "name": _teacher_name(teachers[t]),
                "spare_blocks": spare,
                "teaches_this_subject": t in already,
                "note": "สอนวิชานี้อยู่แล้ว (section อื่น)" if t in already
                        else "มีเวลาว่างพอ แต่ควรตรวจว่าสอนวิชานี้ได้หรือไม่",
            })
        cands.sort(key=lambda c: (not c["teaches_this_subject"], -c["spare_blocks"]))
        results.append({
            "subject": f"{sid} {names.get(sid, '')}".strip(),
            "blocks_needed": blocks_needed,
            "candidates": cands[:MAX_CANDIDATES],
            "candidate_total": len(cands),
        })

    return {
        "teacher": _teacher_name(teachers[tid]),
        "teacher_free_blocks": free_count(tid),
        "teacher_needed_blocks": need.get(tid, 0),
        "subjects": results,
        "note": "ระบบไม่มีข้อมูลความเชี่ยวชาญของอาจารย์ คนที่ไม่ได้สอนวิชานี้อยู่แล้ว ผู้ใช้ต้องตรวจความเหมาะสมเอง",
    }