"""
data_check.py — ตรวจความพร้อมของข้อมูลก่อนจัดตาราง (Python ล้วน ใช้โดย DataGatherAgent)

ตรวจเฉพาะเรื่องที่ "รู้ได้จากตัวเลข ไม่ต้องลองจัด" แบ่งเป็น 4 หมวด:
  1) ข้อมูลไม่ครบ    วิชาที่ยังไม่ผูกอาจารย์ / กลุ่มนิสิต
  2) อาจารย์ไม่ว่าง   คาบว่างน้อยกว่าคาบที่ต้องสอน / วิชาที่สอนร่วมหลายคนแต่ไม่มีเวลาว่างตรงกัน
  3) ห้องไม่พอ       ไม่มีห้องที่จุพอ / ห้องที่กำหนดไว้หาไม่เจอ / คาบของห้องแต่ละประเภทไม่พอทุกวิชา
                     / ห้องเดียวกันถูกหลายวิชากำหนดไว้เกินคาบที่ห้องมี
  4) นิสิตไม่ว่าง     คาบว่างของกลุ่ม (หักวิชาศึกษาทั่วไปที่ล็อกไว้) น้อยกว่าคาบที่ต้องเรียน
                     / ต้องเรียนกี่วันเกินกฎ "ไม่เกิน 3 วิชาต่อวัน"

ทุกข้อมี severity:
  "blocking" = จัดไม่ได้แน่ ไม่ว่าจะจัดยังไง
  "warning"  = จัดได้ แต่ตึงมาก อาจมีวิชาตก
และ "subjects" = รายชื่อวิชาที่น่าจะได้รับผลกระทบ (ใช้แสดงให้ผู้ใช้ก่อนกดจัดตาราง)

ทั้งหมดเป็น "เงื่อนไขขั้นต่ำ" — ผ่านทุกข้อไม่ได้แปลว่าจัดได้แน่ (เช่น ทุกวิชาอยากได้ช่วงเช้าเหมือนกัน)
ปัญหาแบบนั้นไปเจอหลังจัด ใน failure_analysis.diagnose()

รูปแบบข้อความทางแก้ (suggestion / alt):
  - แต่ละข้อเป็นทางแก้ที่ทำได้จริง 1 ทาง อ่านเดี่ยวๆ รู้เรื่อง (DataReviewAgent หยิบไปเป็นทางเลือกในการ์ด)
  - ขึ้นต้นด้วยคำกริยา บอกชื่อ (อาจารย์ / ห้อง / วิชา / กลุ่ม) และตัวเลขให้ชัด ไม่ใช้คำลอยๆ อย่าง "บางวิชา"
  - ไม่ขึ้นต้นด้วย "หรือ"
"""

from .load_data import get_cached_data
from .section_logic import build_session_list
from .slot_filter import _build_blocks

ROOM_LABEL = {"LECTURE": "ห้องบรรยาย", "LAB": "ห้องปฏิบัติการ"}
DAY_TH = {"MON": "วันจันทร์", "TUE": "วันอังคาร", "WED": "วันพุธ", "THU": "วันพฤหัสบดี", "FRI": "วันศุกร์"}
GROUP_DAY_LIMIT = 3            # กฎ: กลุ่มนิสิตเรียนไม่เกิน 3 วิชาต่อวัน (ตรงกับ candidate_scorer.py)
ROOM_TIGHT_RATIO = 0.9         # ใช้คาบของห้องประเภทหนึ่งเกิน 90% = เตือนว่าตึง
EXEMPT_DAY_LIMIT = {"ELECTIVE"}  # วิชาเลือกไม่นับในกฎ 3 วิชา/วัน (ตรงกับ candidate_scorer.py)


def _teacher_name(t: dict) -> str:
    for key in ("name", "full_name", "name_thai", "teacher_name"):
        if t.get(key):
            return str(t[key])
    full = f"{t.get('first_name') or ''} {t.get('last_name') or ''}".strip()
    return full or str(t.get("teacher_id"))


def _blocks_of(session: dict) -> int:
    """คาบที่ session นี้ใช้ (คาบละ 2 ชม.) — เรียนรวด n ชม. = ceil(n/2) คาบ"""
    return -(-(session.get("continuous_size") or 2) // 2)


def check_data_readiness() -> list[dict]:
    """คืน list ของ {"id": "D1", "kind", "severity", "subject", "subjects", "detail",
                     "title", "facts", "suggestion", "alt"}
    - detail     = ประโยคเต็ม (ส่งให้ LLM / ใช้ในผลสรุปท้ายการจัดตาราง)
    - title      = หัวข้อสั้น สำหรับการ์ดในแชท เช่น "ผศ.ดร.ธนะธร ไม่มีเวลาว่าง"
    - facts      = ตัวเลขประกอบสั้นๆ เช่น "ต้องสอน 5 คาบ ว่าง 0 คาบ"
    - suggestion = ทางแก้หลัก 1 ทาง, alt = ทางแก้รอง 1 ทาง (ว่างได้)
    (id ให้ LLM อ้างถึงได้, subject = วิชาหลักของเรื่องนี้ หรือ None ถ้าเป็นเรื่องของอาจารย์/ห้อง/กลุ่ม)
    """
    data = get_cached_data()
    names = {s["subject_id"]: str(s.get("name_thai") or s.get("name_english") or s["subject_id"]).strip()
             for s in data["subjects"]}
    subject_type = {s["subject_id"]: s.get("subject_type") for s in data["subjects"]}
    groups_map = {g["group_id"]: g["total_students"] for g in data["groups"]}
    room_ids = {r["room_id"] for r in data["rooms"]}
    teachers = {t["teacher_id"]: t for t in data["teachers"]}
    sessions = build_session_list()
    blocks = _build_blocks(data["timeslots"])
    issues: list[dict] = []

    def add(kind, severity, subject, detail, subjects=None, suggestion="", *, title="", facts="", alt=""):
        issues.append({"id": f"D{len(issues) + 1}", "kind": kind, "severity": severity,
                       "subject": subject,
                       "subjects": sorted(subjects if subjects is not None else ([subject] if subject else [])),
                       "detail": detail, "title": title or detail, "facts": facts,
                       "suggestion": suggestion, "alt": alt})

    ts_by_id = {str(t["timeslot_id"]): t for t in data["timeslots"]}

    def block_label(b: dict) -> str:
        rows = sorted((ts_by_id[t] for t in b["timeslot_ids"] if t in ts_by_id), key=lambda t: t["start_time"])
        day = DAY_TH.get(b["day"], b["day"])
        hm = lambda t: str(t)[:5]   # "08:00:00" -> "08:00"
        return f"{day} {hm(rows[0]['start_time'])}–{hm(rows[-1]['end_time'])} น." if rows else day

    def examples(bs: list[dict], k: int = 3) -> str:
        """ตัวอย่างคาบ กระจายหลายวัน (ไม่เอาวันเดียวกันซ้ำถ้าเลี่ยงได้)"""
        picked, days = [], set()
        for b in bs:
            if b["day"] not in days:
                picked.append(b); days.add(b["day"])
        picked += [b for b in bs if b not in picked]
        return ", ".join(block_label(b) for b in picked[:k])

    def free_blocks(blocked_ts: set) -> list[dict]:
        return [b for b in blocks if not any(ts in blocked_ts for ts in b["timeslot_ids"])]

    teacher_unavail: dict[str, set] = {}
    for row in data["teacher_unavailability"]:
        teacher_unavail.setdefault(row["teacher_id"], set()).add(str(row["timeslot_id"]))
    room_unavail: dict[str, set] = {}
    for row in data["room_unavailability"]:
        room_unavail.setdefault(row["room_id"], set()).add(str(row["timeslot_id"]))
    general_busy: dict[str, set] = {}          # คาบที่กลุ่มนิสิตติดวิชาศึกษาทั่วไปที่ล็อกไว้
    for row in data["existing"]:
        if row.get("group_id"):
            general_busy.setdefault(row["group_id"], set()).add(str(row["timeslot_id"]))

    # ───────── 1) ข้อมูลไม่ครบ ─────────
    for sec in data["sections"]:
        name = names.get(sec["subject_id"], sec["subject_id"])
        if not sec.get("teacher_ids"):
            add("no_teacher", "blocking", name, "ยังไม่ได้ผูกอาจารย์ผู้สอน",
                suggestion=f"ผูกอาจารย์ผู้สอนให้วิชา {name}",
                title=f"{name} ยังไม่มีอาจารย์ผู้สอน")
        if not sec.get("group_ids"):
            add("no_group", "warning", name, "ยังไม่ได้ผูกกลุ่มนิสิต (ระบบเช็คเวลาเรียนชนกันไม่ได้)",
                suggestion=f"ผูกกลุ่มนิสิตให้วิชา {name}",
                title=f"{name} ยังไม่ผูกกลุ่มนิสิต", facts="ระบบเช็คเวลาเรียนชนกันไม่ได้")

    # ───────── 2) อาจารย์ไม่ว่าง ─────────
    need: dict[str, int] = {}
    taught: dict[str, set] = {}
    taught_groups: dict[str, set] = {}
    for s in sessions:
        for tid in s.get("teacher_ids") or []:
            need[tid] = need.get(tid, 0) + _blocks_of(s)
            taught.setdefault(tid, set()).add(names.get(s["subject_id"], s["subject_id"]))
            taught_groups.setdefault(tid, set()).update(s.get("group_ids") or [])

    def openable(blocked_ts: set, groups: set) -> list[dict]:
        """คาบที่ตอนนี้ปิดอยู่ แต่ถ้าเปิด นิสิตทุกกลุ่มที่เกี่ยวข้องว่าง (ไม่ติดวิชาที่ล็อกไว้)"""
        g_busy = set().union(*(general_busy.get(g, set()) for g in groups)) if groups else set()
        return [b for b in blocks
                if any(ts in blocked_ts for ts in b["timeslot_ids"])
                and not any(ts in g_busy for ts in b["timeslot_ids"])]

    overbooked: set = set()   # อาจารย์ที่แจ้งไปแล้วว่าว่างไม่พอ — ใช้ตัดเรื่องซ้ำในวิชาสอนร่วม
    for tid, n in need.items():
        blocked = teacher_unavail.get(tid, set())
        free = len(free_blocks(blocked))
        who = _teacher_name(teachers.get(tid, {"teacher_id": tid}))
        candidates = openable(blocked, taught_groups.get(tid, set()))
        if n > free:
            overbooked.add(tid)
            tip = f"เพิ่มเวลาว่างของ {who} อีก {n - free} คาบ" + (f" เช่น {examples(candidates)}" if candidates else "")
            add("teacher_overbooked", "blocking", None,
                f"อาจารย์ {who} ต้องสอน {n} คาบ แต่ตั้งเวลาว่างไว้แค่ {free} คาบ", taught.get(tid), tip,
                title=f"{who} " + ("ไม่มีเวลาว่าง" if free == 0 else "เวลาว่างไม่พอสอน"),
                facts=f"ต้องสอน {n} คาบ ว่าง {free} คาบ",
                alt=f"ให้อาจารย์ท่านอื่นช่วยสอนแทนบางวิชาของ {who}")
        elif blocked and free - n <= 1:
            tip = f"เพิ่มเวลาว่างของ {who} อีก 1–2 คาบ" + (f" เช่น {examples(candidates, 2)}" if candidates else "")
            add("teacher_tight", "warning", None,
                f"อาจารย์ {who} ต้องสอน {n} คาบ ว่าง {free} คาบ (เหลือที่ให้ระบบเลือกน้อยมาก)", taught.get(tid), tip,
                title=f"{who} เวลาว่างเหลือน้อย", facts=f"ต้องสอน {n} คาบ ว่าง {free} คาบ")

    # วิชาที่สอนร่วมหลายอาจารย์ ต้องหาคาบที่ "ทุกคนว่างพร้อมกัน" (รวมบรรยาย+ปฏิบัติเป็นเรื่องเดียว)
    team: dict[tuple, int] = {}
    for s in sessions:
        tids = tuple(sorted(s.get("teacher_ids") or []))
        if len(tids) >= 2:
            team[(s["subject_id"], tids)] = team.get((s["subject_id"], tids), 0) + _blocks_of(s)
    for (subj, tids), needed in team.items():
        blocked = set().union(*(teacher_unavail.get(t, set()) for t in tids))
        common = len(free_blocks(blocked))
        if common >= needed:
            continue
        # ถ้าไม่นับอาจารย์ที่แจ้งไปแล้วว่าว่างไม่พอ คนที่เหลือมีเวลาตรงกันพอ
        # -> ต้นเหตุคือเรื่องเดียวกัน แก้ที่อาจารย์คนนั้นก็หาย ไม่ต้องแจ้งซ้ำ
        rest = [t for t in tids if t not in overbooked]
        if len(rest) < len(tids) and (not rest or len(free_blocks(
                set().union(*(teacher_unavail.get(t, set()) for t in rest)))) >= needed):
            continue
        tname = lambda t: _teacher_name(teachers.get(t, {"teacher_id": t}))
        name = names.get(subj, subj)
        # คาบที่ติดอาจารย์แค่คนเดียว = ขอให้คนนั้นเปิดคาบเดียวก็สอนร่วมได้
        near: dict[str, list] = {}
        for b in blocks:
            missing = [t for t in tids if any(ts in teacher_unavail.get(t, set()) for ts in b["timeslot_ids"])]
            if len(missing) == 1:
                near.setdefault(missing[0], []).append(b)
        tips = [f"{tname(t)} เพิ่มเวลาว่าง {examples(bs, 2).replace(', ', ' หรือ ')}"
                for t, bs in sorted(near.items(), key=lambda kv: -len(kv[1]))[:2]]
        split = f"แยกให้อาจารย์แต่ละท่านสอนวิชา {name} คนละ section"
        tip = f"ขอให้ {' / '.join(tips)}" if tips else split
        add("team_no_common_time", "blocking", name,
            f"สอนร่วมโดย {', '.join(tname(t) for t in tids)} ต้องใช้ {needed} คาบที่ทุกคนว่างพร้อมกัน "
            f"แต่มีแค่ {common} คาบ", [name], tip,
            title=f"{name}: อาจารย์ที่สอนร่วมไม่ว่างตรงกัน",
            facts=f"สอนร่วม {len(tids)} คน ต้องใช้ {needed} คาบ ว่างตรงกัน {common} คาบ",
            alt=split if tips else "")

    # ───────── 3) ห้องไม่พอ ─────────
    seen = set()
    for s in sessions:
        students = s.get("max_capacity") or sum(groups_map.get(g, 0) for g in s.get("group_ids") or [])
        key = (s["subject_id"], s["session_type"], s.get("fixed_room_id"), students, tuple(sorted(s.get("group_ids") or [])))
        if key in seen:
            continue
        seen.add(key)
        name = names.get(s["subject_id"], s["subject_id"])
        label = f"{name} [{s['session_type']}]"
        if s.get("fixed_room_id"):
            if s["fixed_room_id"] not in room_ids:
                add("locked_room_missing", "blocking", label,
                    f"กำหนดห้อง {s['fixed_room_id']} ไว้ แต่ไม่พบห้องนี้ในระบบ (อาจถูกลบหรือพิมพ์รหัสผิด)", [name],
                    f"แก้รหัสห้อง {s['fixed_room_id']} ของวิชา {name} ให้ตรงกับห้องในระบบ",
                    title=f"{label}: ห้องที่กำหนดไว้ไม่มีในระบบ", facts=f"รหัสห้อง {s['fixed_room_id']}",
                    alt=f"ยกเลิกการกำหนดห้องของวิชา {name} ให้ระบบเลือกห้องเอง")
            continue
        same_type = [r["capacity"] for r in data["rooms"] if r["room_type"] == s["room_type"]]
        if not any(c >= students for c in same_type):
            biggest = max(same_type, default=0)
            room_label = ROOM_LABEL.get(s["room_type"], "ห้อง")
            tip = (f"แบ่งวิชา {name} เป็น {-(-students // biggest)} section ไม่เกิน section ละ {biggest} คน"
                   if biggest else f"เพิ่ม{room_label}ในระบบ")
            add("no_room_big_enough", "blocking", label,
                f"ต้องใช้{room_label}จุ {students} คน แต่ห้องที่ใหญ่สุดจุ {biggest} คน", [name], tip,
                title=f"{label}: ไม่มีห้องที่จุพอ", facts=f"นิสิต {students} คน ห้องใหญ่สุดจุ {biggest} คน",
                alt=f"เพิ่ม{room_label}ที่จุ {students} คนขึ้นไป" if biggest else "")

    # คาบที่ห้องแต่ละประเภทมีให้ เทียบกับคาบที่ทุกวิชาต้องใช้
    room_free = {r["room_id"]: len(free_blocks(room_unavail.get(r["room_id"], set()))) for r in data["rooms"]}
    for rtype in sorted({s["room_type"] for s in sessions}):
        users = [s for s in sessions if s["room_type"] == rtype]
        demand = sum(_blocks_of(s) for s in users)
        rooms = [r for r in data["rooms"] if r["room_type"] == rtype]
        supply = sum(room_free[r["room_id"]] for r in rooms)
        label = ROOM_LABEL.get(rtype, f"ห้อง {rtype}")
        affected = {names.get(s["subject_id"], s["subject_id"]) for s in users}
        closed = len(rooms) * len(blocks) - supply      # คาบที่ห้องถูกตั้งไม่ว่างไว้
        add_rooms = f"เพิ่ม{label}อีก {-(-max(demand - supply, 1) // len(blocks))} ห้อง"
        reopen = f"เพิ่มเวลาว่างของ{label}ที่ตั้งไม่ว่างไว้ (ปิดอยู่ {closed} คาบ)" if closed else ""
        if demand > supply:
            # ทางหลัก = ทางที่แก้ได้ครบ: ถ้าเปิดห้องที่ปิดไว้แล้วพอ ให้เปิดก่อน ไม่งั้นต้องเพิ่มห้อง
            main, other = (reopen, add_rooms) if closed >= demand - supply else (add_rooms, reopen)
            add("room_shortage", "blocking", None,
                f"วิชาที่ใช้{label}รวมกันต้องใช้ {demand} คาบ แต่{label}ทั้ง {len(rooms)} ห้องมีคาบว่างรวม "
                f"{supply} คาบ ขาดอย่างน้อย {demand - supply} คาบ", affected, main,
                title=f"{label}ไม่พอ", facts=f"ต้องใช้ {demand} คาบ มี {supply} คาบ (ขาด {demand - supply})",
                alt=other)
        elif supply and demand > ROOM_TIGHT_RATIO * supply:
            add("room_tight", "warning", None,
                f"{label}ถูกใช้ {demand} จาก {supply} คาบ ({demand * 100 // supply}%) "
                f"ตึงมาก อาจมีบางวิชาหาห้องไม่ได้", affected,
                reopen or f"เพิ่ม{label}ชั่วคราว 1 ห้อง",
                title=f"{label}ใกล้เต็ม", facts=f"ใช้ {demand} จาก {supply} คาบ ({demand * 100 // supply}%)")

    # ห้องที่ถูกหลายวิชากำหนดไว้ (fixed_room_id)
    locked: dict[str, list] = {}
    for s in sessions:
        if s.get("fixed_room_id") in room_ids:
            locked.setdefault(s["fixed_room_id"], []).append(s)
    room_name = {r["room_id"]: r.get("room_name") or r["room_id"] for r in data["rooms"]}
    for rid, users in locked.items():
        demand = sum(_blocks_of(s) for s in users)
        free = room_free[rid]
        if demand <= free:
            continue
        affected = {names.get(s["subject_id"], s["subject_id"]) for s in users}
        room = room_name[rid]
        if free == 0:
            # ห้องปิดทั้งสัปดาห์: ยกเลิกการกำหนดห้องแค่บางวิชาไม่ช่วย ต้องเปิดเวลาห้องก่อน
            main = f"เพิ่มเวลาว่างของห้อง {room} อย่างน้อย {demand} คาบ"
            alt = f"ยกเลิกการกำหนดห้อง {room} ของทั้ง {len(affected)} วิชา ให้ระบบเลือกห้องเอง"
            title = f"ห้อง {room} ถูกตั้งไม่ว่างทั้งสัปดาห์"
        else:
            main = f"ยกเลิกการกำหนดห้อง {room} อย่างน้อย {demand - free} คาบ ให้ระบบเลือกห้องเอง"
            alt = f"เพิ่มเวลาว่างของห้อง {room} อีก {demand - free} คาบ"
            title = f"ห้อง {room} ถูกกำหนดให้วิชาเกินคาบที่ว่าง"
        add("locked_room_overload", "blocking", None,
            f"ห้อง {room} ถูก {len(affected)} วิชากำหนดไว้ รวม {demand} คาบ แต่ห้องมีคาบว่าง {free} คาบ",
            affected, main, title=title,
            facts=f"{len(affected)} วิชากำหนดห้องนี้ไว้ รวม {demand} คาบ ห้องว่าง {free} คาบ", alt=alt)

    # ───────── 4) คาบว่างของนิสิตไม่พอ ─────────
    # section คู่ขนานที่อาจารย์คนละคน เรียน "เวลาเดียวกัน คนละห้อง" (นิสิตแบ่งครึ่งกันไป)
    # จึงนับเป็นเวลาของกลุ่มแค่ครั้งเดียว — ต้องจับกลุ่มตาม (วิชา, ประเภท, กลุ่มนิสิต, ลำดับคาบ)
    by_sibling: dict[str, list] = {}
    for s in sessions:
        by_sibling.setdefault(s.get("sibling_key") or s["session_id"], []).append(s)
    order_in_sibling = {}
    for members in by_sibling.values():
        for i, s in enumerate(sorted(members, key=lambda x: x["session_id"])):
            order_in_sibling[s["session_id"]] = i

    for g in sorted({g for s in sessions for g in s.get("group_ids") or []}):
        mine = [s for s in sessions if g in (s.get("group_ids") or [])]
        if not mine:
            continue
        glabel = _group_label(g)   # "IT ปี 1" อ่านง่ายกว่ารหัส "IT-Y1"
        slots: dict[tuple, list] = {}
        for s in mine:
            key = (s["subject_id"], s["session_type"], tuple(sorted(s.get("group_ids") or [])),
                   order_in_sibling[s["session_id"]])
            slots.setdefault(key, []).append(s)
        need_g = 0
        for members in slots.values():
            teacher_sets = [set(m.get("teacher_ids") or []) for m in members]
            all_different = len(members) > 1 and all(
                not (a & b) for i, a in enumerate(teacher_sets) for b in teacher_sets[i + 1:])
            need_g += _blocks_of(members[0]) if all_different else sum(_blocks_of(m) for m in members)
        free_g = free_blocks(general_busy.get(g, set()))
        affected = {names.get(s["subject_id"], s["subject_id"]) for s in mine}
        if need_g > len(free_g):
            add("group_overbooked", "blocking", None,
                f"กลุ่ม {glabel} ต้องเรียน {need_g} คาบ แต่มีคาบว่าง {len(free_g)} คาบ "
                f"(หลังหักวิชาศึกษาทั่วไปที่ล็อกไว้)", affected,
                f"ย้ายหรือลดวิชาศึกษาทั่วไปที่ล็อกไว้ของ {glabel} อย่างน้อย {need_g - len(free_g)} คาบ",
                title=f"{glabel} คาบเรียนไม่พอ",
                facts=f"ต้องเรียน {need_g} คาบ ว่าง {len(free_g)} คาบ (หักวิชาศึกษาทั่วไปแล้ว)",
                alt=f"เลื่อนบางวิชาของ {glabel} ไปเปิดเทอมอื่น")
            continue
        if general_busy.get(g) and len(free_g) - need_g <= 1:
            add("group_tight", "warning", None,
                f"กลุ่ม {glabel} ต้องเรียน {need_g} คาบ ว่าง {len(free_g)} คาบ (เหลือที่ให้ระบบเลือกน้อยมาก)", affected,
                f"ย้ายวิชาศึกษาทั่วไปที่ล็อกไว้ของ {glabel} ออก 1–2 คาบ",
                title=f"{glabel} คาบว่างเหลือน้อย", facts=f"ต้องเรียน {need_g} คาบ ว่าง {len(free_g)} คาบ")

        # กฎไม่เกิน 3 วิชา/วัน: แต่ละวิชาต้องใช้กี่ "วัน" — บรรยายแต่ละคาบห้ามวันซ้ำกัน
        # ปฏิบัติแต่ละคาบห้ามวันซ้ำกัน และปฏิบัติห้ามวันเดียวกับบรรยาย
        day_need = 0
        for subj in {s["subject_id"] for s in mine if subject_type.get(s["subject_id"]) not in EXEMPT_DAY_LIMIT}:
            per_type = {}
            for t in ("LECTURE", "LAB"):
                keys = [s.get("sibling_key") for s in mine if s["subject_id"] == subj and s["session_type"] == t]
                per_type[t] = max((keys.count(k) for k in set(keys)), default=0)
            day_need += per_type["LECTURE"] + per_type["LAB"]
        days_open = len({b["day"] for b in free_g})
        if day_need > GROUP_DAY_LIMIT * days_open:
            add("group_day_limit", "blocking", None,
                f"กลุ่ม {glabel} ต้องใช้รวม {day_need} วิชา-วัน แต่กฎไม่เกิน {GROUP_DAY_LIMIT} วิชา/วัน "
                f"ใน {days_open} วัน รับได้แค่ {GROUP_DAY_LIMIT * days_open}", affected,
                f"ย้ายวิชาศึกษาทั่วไปที่ล็อกไว้ของ {glabel} ให้มีวันว่างเพิ่ม",
                title=f"{glabel} ต้องเรียนเกิน {GROUP_DAY_LIMIT} วิชา/วัน",
                facts=f"ต้องใช้ {day_need} วิชา-วัน รับได้ {GROUP_DAY_LIMIT * days_open} ({days_open} วันที่ว่าง)",
                alt=f"ลดจำนวนวิชาของ {glabel} ในเทอมนี้")

    # ───────── 5) วิชาที่ต้องเรียนพร้อมกัน แต่ไม่มีเวลาว่างในช่วงที่บังคับ ─────────
    # แจ้งเฉพาะ "ต้นเหตุ" ที่เรื่องอื่นข้างบนยังไม่ได้บอก (ฝั่งที่ตกตามไปด้วย ระบบข้ามให้เองตอนจัด ไม่แจ้งซ้ำ)
    by_id = {s["session_id"]: s for s in sessions}
    seen_sync = set()
    for sid, why in impossible_sessions().items():
        s = by_id.get(sid)
        if not s:
            continue
        name = names.get(s["subject_id"], s["subject_id"])
        who = f"{name} {', '.join(_group_label(g) for g in s.get('group_ids') or [])}"
        # ฝั่งที่เป็นต้นเหตุ แต่เรื่องอื่นข้างบนยังไม่ได้บอก (เช่น อาจารย์ว่างทั้งสัปดาห์ แต่ไม่ว่างช่วง 15–17 ที่บังคับ)
        if why.startswith(DATA_REASON_PREFIX) and "ในช่วง" in why and who not in seen_sync:
            covered = any(i["kind"] == "teacher_overbooked" and i["title"].rsplit(" ", 1)[0] in why for i in issues)
            if not covered:
                seen_sync.add(who)
                add("sync_window", "blocking", name, f"{who}: {why[len(DATA_REASON_PREFIX):]}", [name],
                    f"เพิ่มเวลาว่างของอาจารย์วิชา {name} ในช่วงที่ต้องเรียนพร้อมกัน",
                    title=f"{who} ไม่มีเวลาในช่วงที่ต้องเรียนพร้อมกัน", facts=why[len(DATA_REASON_PREFIX):])
    return issues


# ─────────────────────────────────────────────────────────────────────────
# session ที่ "จัดไม่ได้แน่ 100%" — ใช้ให้ตัวจัดตารางข้ามไปเลย ไม่เสียเวลาลอง/ซ่อม
#
# ดูทีละ session ว่า "ถ้าตารางยังว่างทั้งหมด" มีคาบไหนที่อาจารย์ทุกคนว่าง นิสิตไม่ติดวิชาศึกษาทั่วไป
# ที่ล็อกไว้ และมีห้องที่จุพอและไม่ได้ปิด อย่างน้อย 1 คาบไหม ถ้าไม่มีเลย = จัดไม่ได้แน่ ไม่ว่าจะ
# จัดวิชาอื่นยังไงก็ตาม (ต่างจาก check_data_readiness ที่นับยอดรวม ซึ่ง "ไม่พอ" ยังจัดได้บางส่วน)
#
# วิชาที่ต้องเรียน LECTURE พร้อมกัน (SYNC_LECTURE_GROUPS) ถ้าฝั่งหนึ่งจัดไม่ได้ อีกฝั่งก็จัดไม่ได้ด้วย
# (SYNC_STRICT) และถึงแต่ละฝั่งจัดได้ แต่ไม่มีคาบที่ว่างตรงกันในช่วงเวลาที่กำหนด ก็จัดไม่ได้ทั้งคู่
# ─────────────────────────────────────────────────────────────────────────

DATA_REASON_PREFIX = "ติดข้อมูล: "


def _group_label(g: str) -> str:
    """รหัสกลุ่ม -> "CS ปี 1" (รูปแบบเดียวกับหน้าเว็บ) ใช้สาขาจากตาราง groups
    (รหัสจริงมีทั้ง "IT-Y1" และ "Y1" เฉยๆ ของ CS จึงเดาจากรหัสอย่างเดียวไม่ได้)"""
    import re
    major = next((x.get("major") for x in get_cached_data()["groups"] if x["group_id"] == g), None)
    m = re.search(r"Y(\d+)$", g or "", re.I)
    if not m:
        return str(g)
    if not major:
        major = g.split("-")[0].upper() if "-" in g else "CS"
    return f"{major} ปี {m.group(1)}"


def impossible_sessions() -> dict[str, str]:
    """คืน {session_id: เหตุผลที่จัดไม่ได้แน่} — ว่าง = ทุก session มีโอกาสจัดได้"""
    from .auto_assign import SYNC_LECTURE_GROUPS, SYNC_TIME_WINDOWS, SYNC_STRICT  # import ในฟังก์ชัน กัน import วน

    data = get_cached_data()
    sessions = build_session_list()
    blocks = _build_blocks(data["timeslots"])
    ts_by_id = {str(t["timeslot_id"]): t for t in data["timeslots"]}
    groups_map = {g["group_id"]: g["total_students"] for g in data["groups"]}
    teachers = {t["teacher_id"]: t for t in data["teachers"]}
    names = {s["subject_id"]: str(s.get("name_thai") or s.get("name_english") or s["subject_id"]).strip()
             for s in data["subjects"]}

    teacher_unavail: dict[str, set] = {}
    for row in data["teacher_unavailability"]:
        teacher_unavail.setdefault(row["teacher_id"], set()).add(str(row["timeslot_id"]))
    room_unavail: dict[str, set] = {}
    for row in data["room_unavailability"]:
        room_unavail.setdefault(row["room_id"], set()).add(str(row["timeslot_id"]))
    general_busy: dict[str, set] = {}
    for row in data["existing"]:
        if row.get("group_id"):
            general_busy.setdefault(row["group_id"], set()).add(str(row["timeslot_id"]))

    def in_window(b: dict, window) -> bool:
        if not window:
            return True
        lo, hi = window
        return all(str(ts_by_id[t]["start_time"])[:5] >= lo and str(ts_by_id[t]["end_time"])[:5] <= hi
                   for t in b["timeslot_ids"] if t in ts_by_id)

    def analyse(s: dict, window=None) -> tuple[set, str]:
        """(คาบที่ลงได้ถ้าตารางว่าง, เหตุผลถ้าไม่มีเลย)"""
        tids = s.get("teacher_ids") or []
        gids = s.get("group_ids") or []
        students = s.get("max_capacity") or sum(groups_map.get(g, 0) for g in gids)
        if s.get("fixed_room_id"):
            rooms = [r for r in data["rooms"] if r["room_id"] == s["fixed_room_id"]]
            if not rooms:
                return set(), f"ห้อง {s['fixed_room_id']} ที่กำหนดไว้ไม่มีในระบบ"
        else:
            rooms = [r for r in data["rooms"] if r["room_type"] == s["room_type"] and r["capacity"] >= students]
            if not rooms:
                return set(), f"ไม่มี{ROOM_LABEL.get(s['room_type'], 'ห้อง')}ที่จุ {students} คน"
        if s.get("continuous_size"):
            return {"?"}, ""          # เรียนรวดหลายชั่วโมง: ไม่วิเคราะห์ละเอียด ปล่อยให้ตัวจัดลองเอง

        t_block = set().union(*(teacher_unavail.get(t, set()) for t in tids)) if tids else set()
        g_block = set().union(*(general_busy.get(g, set()) for g in gids)) if gids else set()
        ok_t, ok_g, ok_r, ok = set(), set(), set(), set()
        for b in blocks:
            key = (b["day"], b["block_id"])
            ts = b["timeslot_ids"]
            if not in_window(b, window):
                continue
            t_ok = not any(x in t_block for x in ts)
            g_ok = not any(x in g_block for x in ts)
            r_ok = any(not any(x in room_unavail.get(r["room_id"], set()) for x in ts) for r in rooms)
            if t_ok: ok_t.add(key)
            if g_ok: ok_g.add(key)
            if r_ok: ok_r.add(key)
            if t_ok and g_ok and r_ok:
                ok.add(key)
        if ok:
            return ok, ""
        when = f" ในช่วง {window[0]}–{window[1]}" if window else ""
        if not ok_t:
            zero = [t for t in tids if not any(
                not any(x in teacher_unavail.get(t, set()) for x in b["timeslot_ids"]) and in_window(b, window)
                for b in blocks)]
            if zero:
                who = ", ".join(_teacher_name(teachers.get(t, {"teacher_id": t})) for t in zero)
                return set(), f"{who} ไม่มีเวลาว่าง{when}"
            return set(), f"อาจารย์ที่สอนร่วมไม่มีเวลาว่างตรงกัน{when}"
        if not ok_g:
            return set(), f"{', '.join(_group_label(g) for g in gids)} ไม่มีคาบว่าง{when} (ติดวิชาศึกษาทั่วไปที่ล็อกไว้)"
        if not ok_r:
            return set(), f"ห้องที่ใช้ได้ถูกตั้งไม่ว่างทุกคาบ{when}"
        return set(), f"ไม่มีคาบที่อาจารย์ นิสิต และห้องว่างตรงกัน{when}"

    result: dict[str, str] = {}
    for s in sessions:
        ok, why = analyse(s)
        if not ok:
            result[s["session_id"]] = DATA_REASON_PREFIX + why

    # ── วิชาที่ต้องเรียน LECTURE พร้อมกัน (จับคู่ตาม "ลำดับคาบ" แบบเดียวกับ _assign_sync_lecture_groups) ──
    if SYNC_STRICT:
        label = lambda s: f"{names.get(s['subject_id'], s['subject_id'])} {', '.join(_group_label(g) for g in s.get('group_ids') or [])}"
        for subject_ids in SYNC_LECTURE_GROUPS:
            window = SYNC_TIME_WINDOWS.get(tuple(subject_ids))
            units: dict[tuple, list] = {}
            for s in sessions:
                if s["session_type"] == "LECTURE" and s["subject_id"] in subject_ids:
                    units.setdefault((s["subject_id"], tuple(sorted(s.get("group_ids") or []))), []).append(s)
            if len(subject_ids) == 1:
                keys = sorted(units)
            else:
                first = {}
                for k in sorted(units):
                    first.setdefault(k[0], k)
                if len(first) < len(subject_ids):
                    continue
                keys = [first[sid] for sid in subject_ids]
            if len(keys) < 2:
                continue
            lists = [sorted(units[k], key=lambda x: x["session_id"]) for k in keys]
            for idx in range(min(len(lst) for lst in lists)):
                block = [lst[idx] for lst in lists]
                analysed = [(s, *analyse(s, window)) for s in block]
                bad = [(s, why) for s, ok, why in analysed if not ok]
                if bad:
                    # เหตุผลแบบไม่จำกัดช่วงเวลา (เช่น "ไม่มีเวลาว่าง" ทั้งสัปดาห์) ชัดกว่า ถ้ามีให้ใช้อันนั้น
                    for s, why in bad:
                        result.setdefault(s["session_id"], DATA_REASON_PREFIX + why)
                    root = bad[0][0]
                    root_why = result[root["session_id"]][len(DATA_REASON_PREFIX):]
                    for s, ok, _ in analysed:
                        if ok:
                            result[s["session_id"]] = f"ต้องเรียนพร้อม {label(root)} ซึ่งจัดไม่ได้ ({root_why})"
                    continue
                common = set.intersection(*(ok for _, ok, _ in analysed))
                if not common and "?" not in set().union(*(ok for _, ok, _ in analysed)):
                    who = " กับ ".join(label(s) for s in block)
                    for s in block:
                        result[s["session_id"]] = (DATA_REASON_PREFIX + f"{who} ต้องเรียนพร้อมกัน "
                                                   f"แต่ไม่มีเวลาว่างตรงกันในช่วง {window[0]}–{window[1]}" if window else
                                                   DATA_REASON_PREFIX + f"{who} ต้องเรียนพร้อมกัน แต่ไม่มีเวลาว่างตรงกัน")
    return result