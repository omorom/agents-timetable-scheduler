"""
section_logic.py
1. สร้าง "session" ที่ต้องจัดจริง จาก sections (subject_selected) — แยกเป็น LECTURE/LAB
2. เช็คว่านิสิตเกินความจุห้อง LAB ที่ใหญ่สุดไหม ถ้าเกิน แบ่งเป็น section 1/2
3. จับกลุ่ม subject_selected หลายแถวที่เป็น "section คู่กันจริง" (วิชาเดียวกัน + ปีการศึกษา
   เดียวกัน + กลุ่มนิสิตเดียวกัน แต่คนละอาจารย์ — เช่นเปิดสอนผ่านหน้าเว็บทีละ section)
   ให้อยู่ในชุดเดียวกัน แล้วตั้ง session_id ให้ลงท้าย -1/-2 เพื่อให้กลไกจับคู่ pairing
   ใน auto_assign.py (ที่มองหา suffix -1/-2) ทำงานถูกต้อง — ถ้าไม่ทำแบบนี้ auto_assign.py
   จะมองว่าเป็นคนละวิชากันเลย ไม่จับคู่ให้ จัดกระจายไปคนละวันคนละเวลา

กฎ (ยืนยันแล้ว): lecture_hours/lab_hours คือ "จำนวน block" ไม่ใช่จำนวนชั่วโมง
เช่น lecture_hours=2 แปลว่าต้องจัด 2 block (คนละวันกัน เวลาไหนก็ได้ ไม่ต้องตรงกัน)
ไม่ใช่ 1 block ยาว 4 ชั่วโมง — แต่ละ block ที่มาจากวิชา+session_type เดียวกัน
("พี่น้องกัน") ต้องคนละวันเสมอ ห้ามซ้ำวัน (บังคับที่ชั้น slot_filter.py)

สำคัญ: ไฟล์นี้ "ไม่" cache ข้อมูลไว้ที่ module-level เรียก get_cached_data()
ข้างในฟังก์ชันทุกครั้งแทน เพื่อให้เห็นข้อมูลล่าสุดหลัง refresh_cache()
"""

from .load_data import get_cached_data


def _lab_capacity(data: dict) -> int:
    """ความจุห้อง LAB ที่ใหญ่สุด — คำนวณสดทุกครั้ง กันไว้ไม่ให้ max() พังถ้าไม่มีห้อง LAB เลย"""
    lab_rooms = [r for r in data["rooms"] if r["room_type"] == "LAB"]
    return max((r["capacity"] for r in lab_rooms), default=0)


def _student_count(section: dict, groups_map: dict) -> int:
    """จำนวนนิสิตของ section นี้ — ใช้ max_capacity ถ้าระบุไว้ ไม่งั้นรวมจำนวนจากทุกกลุ่มที่ผูกไว้"""
    if section.get("max_capacity"):
        return section["max_capacity"]
    return sum(groups_map.get(gid, 0) for gid in section.get("group_ids", []))


def _parallel_group_key(section: dict) -> tuple:
    """คีย์ระบุว่า section (subject_selected แถวนี้) เป็น 'section คู่กัน' กับแถวไหนบ้าง
    วิชาเดียวกัน + ปีการศึกษาเดียวกัน + กลุ่มนิสิตชุดเดียวกัน (ไม่สนลำดับ) ถือว่าคู่กัน
    ต่างอาจารย์ได้ — นั่นคือเคสปกติของ 'เปิดสอนหลาย section คนละอาจารย์' ผ่านหน้าเว็บ
    """
    return (
        section["subject_id"],
        section["academic_year"],
        tuple(sorted(section.get("group_ids", []))),
    )


def _assign_parallel_labels(data: dict) -> dict[int, str | None]:
    """คืน dict: subject_selected_id -> "1"/"2"/... (label สำหรับต่อท้าย session_id)
    หรือ None ถ้า section นั้นอยู่คนเดียว ไม่มีคู่ (ไม่ต้องต่อ suffix เลย เหมือนเดิม)

    เรียงตาม subject_selected_id เพื่อให้ label คงที่ (deterministic) ไม่สลับไปมาระหว่างรอบจัด
    """
    groups: dict[tuple, list[dict]] = {}
    for section in data["sections"]:
        key = _parallel_group_key(section)
        groups.setdefault(key, []).append(section)

    labels: dict[int, str | None] = {}
    for key, members in groups.items():
        if len(members) <= 1:
            for m in members:
                labels[m["subject_selected_id"]] = None
            continue
        members_sorted = sorted(members, key=lambda m: m["subject_selected_id"])
        for idx, m in enumerate(members_sorted, start=1):
            # เกินคู่ 1/2 (มี 3+ section คู่ขนานกัน) ก็ยังใส่เลขต่อได้เรื่อยๆ "3", "4", ...
            # แต่กลไก pairing ใน auto_assign.py ตอนนี้รองรับเต็มที่แค่คู่ 1/2 เท่านั้น
            labels[m["subject_selected_id"]] = str(idx)

    return labels


def _parallel_groups(data: dict) -> dict[tuple, list[dict]]:
    """คืน dict: key (ตาม _parallel_group_key) -> list ของ section ที่คู่กัน
    เรียง member ในแต่ละกลุ่มตาม subject_selected_id ให้ deterministic เสมอ
    """
    groups: dict[tuple, list[dict]] = {}
    for section in data["sections"]:
        key = _parallel_group_key(section)
        groups.setdefault(key, []).append(section)
    for key in groups:
        groups[key] = sorted(groups[key], key=lambda m: m["subject_selected_id"])
    return groups


def build_section_plan() -> list[dict]:
    """เช็คว่า section ไหนต้องแบ่ง (นิสิตเกิน capacity ห้อง LAB ที่ใหญ่สุด)
    เช็คเฉพาะ section ที่มี lab_hours > 0 เท่านั้น (ไม่มี LAB ไม่ต้องเช็ค)
    ไม่แตะ section ที่ถูกจับคู่ parallel ไปแล้ว (_assign_parallel_labels) — เพราะ
    ตัวนั้นถือว่า "มีคู่อยู่แล้วจากคนละอาจารย์" ไม่ต้องแบ่งซ้ำเพราะ capacity อีกชั้น
    """
    data = get_cached_data()
    lab_capacity = _lab_capacity(data)
    groups_map = {g["group_id"]: g["total_students"] for g in data["groups"]}
    parallel_labels = _assign_parallel_labels(data)

    rooms_by_id = {r["room_id"]: r for r in data["rooms"]}

    plan = []
    for section in data["sections"]:
        if section["lab_hours"] <= 0:
            continue
        if parallel_labels.get(section["subject_selected_id"]) is not None:
            # มีคู่จากคนละอาจารย์อยู่แล้ว ไม่ต้องแบ่งซ้ำด้วย capacity
            continue

        count = _student_count(section, groups_map)

        # ถ้าล็อกห้องไว้ (fixed_room_id) ต้องเทียบ "ความจุห้องที่ล็อกไว้จริง" ไม่ใช่ห้อง
        # LAB ที่ใหญ่สุดทั้งระบบ — เพราะต่อให้ระบบมีห้องใหญ่กว่า ผู้ใช้ก็ตั้งใจล็อกห้องนี้
        # ไว้แล้ว (มีอุปกรณ์เฉพาะ) ถ้านิสิตเกินห้องนี้ ต้องแบ่ง 2 section แต่ทั้งคู่ต้อง
        # ใช้ห้องเดียวกัน (ห้องที่ล็อกไว้) เรียนต่อกันคนละคาบ ไม่ใช่คนละห้อง
        fixed_room_id = section.get("fixed_room_id")
        is_fixed_room_split = False
        if fixed_room_id and fixed_room_id in rooms_by_id:
            threshold = rooms_by_id[fixed_room_id]["capacity"]
            is_fixed_room_split = bool(threshold and count > threshold)
        else:
            threshold = lab_capacity
            is_fixed_room_split = bool(threshold and count > threshold)

        plan.append({
            "subject_selected_id": section["subject_selected_id"],
            "subject_id": section["subject_id"],
            "students": count,
            "sections": 2 if is_fixed_room_split else 1,
            # true ก็ต่อเมื่อสาเหตุที่แบ่งมาจาก "ห้องที่ล็อกไว้เล็กเกินไป" โดยเฉพาะ —
            # ใช้บอก build_session_list() ว่าทั้ง 2 section ที่แบ่งออกมาต้องใช้ห้องเดียวกัน
            # (ห้องที่ล็อกไว้) เสมอ ไม่ใช่คนละห้องแบบกรณี capacity เกินทั่วไป
            "keep_fixed_room_both": is_fixed_room_split and bool(fixed_room_id),
        })
    return plan


def build_session_list() -> list[dict]:
    """สร้าง session (1 session = 1 block = 2 timeslot) ที่ต้องจัดจริงทั้งหมด

    แต่ละ session มี field "sibling_key" บอกว่ามัน "พี่น้อง" กับ session ไหนบ้าง
    (มาจากวิชา+session_type+section เดียวกัน) — session ที่ sibling_key เดียวกัน
    ต้องถูกจัดคนละวันกันเสมอ (บังคับที่ slot_filter.py ตอนหา candidate)

    หมายเหตุสำคัญ — LECTURE กับ LAB ปฏิบัติต่างกันสำหรับ "parallel group"
    (หลายแถว subject_selected เป็นวิชา+ปี+กลุ่มนิสิตเดียวกัน แต่คนละอาจารย์):
      - LECTURE: รวมทุกแถวในกลุ่มเป็น "session เดียว" (ห้องเดียวกัน เวลาเดียวกัน จริงๆ)
        teacher_ids รวมทุกอาจารย์เข้าด้วยกัน และ max_capacity รวมนิสิตทุก section
        เข้าด้วยกัน (เพื่อให้ slot_filter เลือกห้องที่จุคนได้ครบทั้งกลุ่ม)
      - LAB: ยังคงแยกคนละ session ต่ออาจารย์ (คนละห้อง เวลาเดียวกัน) เหมือนเดิม
        ใช้กลไก pairing เดิมของ auto_assign.py (session_id ลงท้าย -1/-2)

    team-teaching (1 แถวเดียว มีหลายอาจารย์ผูกไว้) ก็ได้ผลแบบเดียวกันโดยธรรมชาติ
    (LECTURE รวมอยู่แล้วในตัว เพราะเป็น session เดียวตั้งแต่ต้น, LAB แยกคนละอาจารย์)
    """
    data = get_cached_data()
    plan_by_id = {p["subject_selected_id"]: p for p in build_section_plan()}
    parallel_labels = _assign_parallel_labels(data)
    parallel_groups = _parallel_groups(data)
    # กันสร้าง LECTURE ซ้ำ — parallel group หนึ่งกลุ่ม สร้าง LECTURE รวมแค่ครั้งเดียว
    # (ใช้ subject_selected_id ของสมาชิกตัวแรกในกลุ่ม เป็นตัวแทนสร้าง)
    lecture_created_for_group: set[tuple] = set()

    result = []
    for section in data["sections"]:
        parallel_label = parallel_labels.get(section["subject_selected_id"])
        base_id = f"SS{section['subject_selected_id']}"

        # ── LECTURE: สร้าง 1 session ต่อ 1 block ตาม lecture_hours ──
        lecture_blocks = section["lecture_hours"] or 0
        if lecture_blocks > 0:
            group_key = _parallel_group_key(section)
            group_members = parallel_groups.get(group_key, [section])

            # รวม LECTURE เป็นห้องเดียวกันก็ต่อเมื่อ "ทุกสมาชิก" ในกลุ่มตั้งใจรวมไว้จริง
            # (is_lecture_combined = True ทุกแถว) — ถ้าไม่ครบทุกแถว (ค่า default คือ False
            # อยู่แล้ว) ถือว่า "ไม่ได้ตั้งใจรวม" ให้ปฏิบัติเหมือน LAB คือแยกคนละ session
            # ต่อ section แล้วปล่อยให้ auto_assign.py ตัดสินใจเอง (same_teacher=True ใน
            # sections คู่ -> ห้องเดียวกันติดกัน, same_teacher=False -> เวลาเดียวกันคนละห้อง)
            should_combine = len(group_members) > 1 and all(
                m.get("is_lecture_combined") for m in group_members
            )

            if should_combine:
                # parallel group ตั้งใจรวมไว้จริง — รวมเป็น session เดียว สร้างแค่ครั้งเดียวต่อกลุ่ม
                if group_key not in lecture_created_for_group:
                    lecture_created_for_group.add(group_key)
                    combined_teacher_ids: list[str] = []
                    for m in group_members:
                        for tid in (m.get("teacher_ids") or []):
                            if tid not in combined_teacher_ids:
                                combined_teacher_ids.append(tid)
                    combined_capacity = sum((m.get("max_capacity") or 0) for m in group_members) or None

                    lead = group_members[0]  # ใช้ subject_selected_id ตัวแรกเป็นฐานของ session_id
                    lead_base_id = f"SS{lead['subject_selected_id']}"
                    lecture_sibling_key = f"{lead_base_id}-LEC"
                    for block_num in range(1, lecture_blocks + 1):
                        session_id = (
                            lecture_sibling_key if lecture_blocks == 1
                            else f"{lecture_sibling_key}{block_num}"
                        )
                        result.append({
                            "session_id": session_id,
                            "subject_selected_id": lead["subject_selected_id"],
                            "subject_id": lead["subject_id"],
                            "session_type": "LECTURE",
                            "section": None,  # รวมกันแล้ว ไม่ต้องมี label คู่ขนานอีก
                            "sibling_key": lecture_sibling_key,
                            "room_type": "LECTURE",
                            "teacher_ids": combined_teacher_ids,
                            "group_ids": lead["group_ids"],
                            "max_capacity": combined_capacity,  # ← รวม capacity ทุก section แล้ว
                        })
                # สมาชิกตัวอื่นในกลุ่มเดียวกัน ไม่ต้องสร้าง LECTURE ซ้ำ (ข้ามไปเลย)
            else:
                # ไม่ตั้งใจรวม (หรือไม่มีคู่ขนานเลย) — สร้าง LECTURE แยกต่อ section
                # ถ้ามีคู่ขนาน (parallel_label ไม่ None) ใส่ label ให้ด้วย เพื่อให้
                # auto_assign.py มองว่านี่คือคู่ที่ต้องจับคู่กัน (เหมือน LAB ทุกประการ)
                lecture_sibling_key = f"{base_id}-LEC" + (f"-{parallel_label}" if parallel_label else "")
                for block_num in range(1, lecture_blocks + 1):
                    session_id = (
                        lecture_sibling_key if lecture_blocks == 1 else f"{lecture_sibling_key}{block_num}"
                    )
                    result.append({
                        "session_id": session_id,
                        "subject_selected_id": section["subject_selected_id"],
                        "subject_id": section["subject_id"],
                        "session_type": "LECTURE",
                        "section": parallel_label,  # ← ใส่ label คู่ขนาน (ถ้ามี) ให้ pairing ทำงาน
                        "sibling_key": lecture_sibling_key,
                        "room_type": "LECTURE",
                        "teacher_ids": section["teacher_ids"],
                        "group_ids": section["group_ids"],
                        "max_capacity": section.get("max_capacity"),
                    })

        # ── LAB: สร้าง 1 session ต่อ 1 block ตาม lab_hours x จำนวน section (ถ้าแบ่ง) ──
        # เกิดการแตกเป็นหลาย session (letter "1"/"2"/...) ได้ 3 ทาง แยกกันชัดเจน:
        #   1) team-teaching: 1 แถว subject_selected แต่มีอาจารย์ผูกไว้มากกว่า 1 คน
        #      -> LAB แตกเป็นคนละ session ต่ออาจารย์ 1 คน (คนละห้อง เวลาเดียวกัน)
        #      นิสิตถูกแบ่งเท่าๆ กันตามจำนวนอาจารย์ (เช่น 75 คน 2 อาจารย์ -> คนละ ~38 คน)
        #   2) parallel: หลายแถว subject_selected เป็นวิชา+ปี+กลุ่มนิสิตเดียวกัน (คนละอาจารย์)
        #      -> ใช้ parallel_label ที่คำนวณไว้แล้ว (คนละห้อง เวลาเดียวกัน)
        #      max_capacity ของแต่ละแถวถูกกรอกไว้ถูกต้องอยู่แล้วตอนเพิ่มวิชา ไม่ต้องหารซ้ำ
        #   3) capacity เกิน: 1 แถว 1 อาจารย์ แต่นิสิตเกินความจุห้อง LAB ที่ใหญ่สุด
        #      -> แบ่งตาม build_section_plan (เดิม) นิสิตแบ่งเท่าๆ กันตาม num_sections
        # ทำตามลำดับความสำคัญนี้ ไม่ปนกัน (มีคู่จากทางไหนแล้วไม่ต้องเช็คทางอื่นซ้ำ)
        #
        # สำคัญ: max_capacity ของแต่ละ unit คำนวณตรงนี้ให้ถูกต้อง "ครั้งเดียว" แล้วส่งเข้า
        # slot_filter.py ใช้ตรงๆ เลย (ไม่มีการหารครึ่งซ้ำอีกที่ slot_filter.py แล้ว — เดิม
        # slot_filter.py เคยหารครึ่งอัตโนมัติทุกครั้งที่ session มี "section" ซึ่งผิด เพราะ
        # กรณี parallel (2) ค่า max_capacity ของแต่ละแถวถูกต้องอยู่แล้ว ไม่ควรหารซ้ำอีก
        # ทำให้ห้องที่เลือกได้เล็กเกินจริง เช่น 75 คนหารเหลือ 38 ทั้งที่ควรใช้ 75 เต็ม)
        lab_blocks = section["lab_hours"] or 0
        if lab_blocks > 0:
            team_teachers = section.get("teacher_ids") or []
            section_capacity = section.get("max_capacity") or 0
            keep_fixed_room_both = False  # true เฉพาะกรณี 3 ที่แบ่งเพราะห้องล็อกไว้เล็กเกินไป
            if parallel_label is not None:
                # กรณี 2: คู่ขนานจากคนละแถวอยู่แล้ว ใช้ label เดียวกับที่กำหนดไว้
                # capacity ของแถวนี้ถูกต้องอยู่แล้ว (กรอกแยกไว้ตอนเพิ่มวิชาแต่ละ section) ไม่หาร
                lab_units = [(parallel_label, team_teachers, section_capacity)]
            elif len(team_teachers) > 1:
                # กรณี 1: team-teaching ในแถวเดียวกัน -> แตกคนละ session ต่ออาจารย์ 1 คน
                # แบ่งนิสิตเท่าๆ กันตามจำนวนอาจารย์ (ปัดขึ้น กันเศษหาย)
                per_teacher_capacity = -(-section_capacity // len(team_teachers)) if section_capacity else None
                lab_units = [
                    (str(idx), [tid], per_teacher_capacity)
                    for idx, tid in enumerate(team_teachers, start=1)
                ]
            else:
                # กรณี 3: capacity เกินอย่างเดียว (เดิม) — แบ่งนิสิตเท่าๆ กันตาม num_sections
                plan = plan_by_id.get(section["subject_selected_id"])
                num_sections = plan["sections"] if plan else 1
                keep_fixed_room_both = bool(plan and plan.get("keep_fixed_room_both"))
                if num_sections == 2:
                    half_capacity = -(-section_capacity // 2) if section_capacity else None
                    lab_units = [("1", team_teachers, half_capacity), ("2", team_teachers, half_capacity)]
                else:
                    lab_units = [(None, team_teachers, section_capacity)]

            for unit_idx, (letter, lab_teacher_ids, unit_capacity) in enumerate(lab_units):
                lab_sibling_key = f"{base_id}-LAB" + (f"-{letter}" if letter else "")
                # ห้องที่ล็อกไว้ (ถ้ามี) ปกติใช้กับ sub-session "ตัวแรก" ของ section นี้เท่านั้น
                # ตัวที่เหลือ (ถ้าแตกออกมาจาก team-teaching/capacity — เกิดพร้อมกันเวลาเดียวกัน
                # คนละห้อง) ปล่อยเป็นอัตโนมัติ ไม่งั้น 2 sub-session จะแย่งห้องเดียวกันจนชนกันเอง
                #
                # ข้อยกเว้น: ถ้าสาเหตุที่แบ่งคือ "ห้องที่ล็อกไว้เล็กเกินไปสำหรับนิสิตทั้งหมด"
                # (keep_fixed_room_both) ทั้ง 2 unit ต้องใช้ห้องเดียวกันเสมอ (ห้องที่ล็อกไว้)
                # เพราะไม่ได้ชนกัน — เรียนคนละคาบ (ต่อกัน) ไม่ใช่พร้อมกัน จึงใช้ห้องเดียวกัน
                # ได้สบายๆ (ปล่อยให้ assign_lab_pair_deterministic ที่ same_teacher=True
                # จัดการหาคาบติดกันในห้องเดียวกันให้เองตามปกติ)
                if keep_fixed_room_both:
                    unit_fixed_room_id = section.get("fixed_room_id")
                else:
                    unit_fixed_room_id = section.get("fixed_room_id") if unit_idx == 0 else None
                for block_num in range(1, lab_blocks + 1):
                    session_id = lab_sibling_key if lab_blocks == 1 else f"{lab_sibling_key}-B{block_num}"
                    result.append({
                        "session_id": session_id,
                        "subject_selected_id": section["subject_selected_id"],
                        "subject_id": section["subject_id"],
                        "session_type": "LAB",
                        "section": letter,
                        "sibling_key": lab_sibling_key,  # ← กันซ้ำวันเฉพาะ block ของ section เดียวกัน
                        "room_type": "LAB",
                        "teacher_ids": lab_teacher_ids,  # ← team-teaching: คนละ session มีแค่ 1 คน
                        "group_ids": section["group_ids"],
                        "max_capacity": unit_capacity,  # ← คำนวณถูกต้องแล้วต่อ unit ไม่ต้องหารซ้ำที่ slot_filter
                        # ห้องที่บังคับใช้ตายตัว (ถ้าตั้งไว้) — slot_filter.py ต้องกรองให้เหลือ
                        # แค่ห้องนี้ห้องเดียว (เช็คเวลาว่างของห้องนี้ตามปกติ)
                        "fixed_room_id": unit_fixed_room_id,
                    })

    return result