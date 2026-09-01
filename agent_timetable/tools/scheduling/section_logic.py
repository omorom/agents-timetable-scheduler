from .load_data import get_cached_data

# subject_id (รหัสวิชา — คงที่ตลอด ไม่เปลี่ยนไม่ว่าจะเปิดสอนกี่รอบ) ของวิชาที่ต้องเรียน
# lecture ติดกันในวันเดียว (ไม่แยกวัน) — ตอนนี้มีวิชาเดียว (273252 กฎหมายเทคโนโลยี
# สารสนเทศ) ถ้ามีเพิ่มค่อยย้ายไปเป็นคอลัมน์ใน DB
#
# สำคัญ: ใช้ subject_id ไม่ใช่ subject_selected_id เพราะ subject_selected_id คือ id
# ของ "การเปิดสอนวิชานั้นในเทอมนั้น" (แถวในตาราง subject_selected) ซึ่งเปลี่ยนไปทุกครั้ง
# ที่มีคนกด "เปิดสอน" วิชานี้ใหม่ (ลบของเดิมแล้วสร้างแถวใหม่ = id ใหม่) ถ้า hardcode
# ด้วย subject_selected_id จะพังทันทีที่มีคนเปิดสอนใหม่ — subject_id (รหัสวิชาในหลักสูตร)
# คงที่ตลอดไปไม่ว่าจะเปิดสอนกี่รอบ ทนทานกว่ามาก
CONTINUOUS_SUBJECTS = {"273252"}


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


def _combined_lecture_groups(data: dict) -> dict[str, list[dict]]:
    """คืน dict: lecture_combine_group (string ที่ผู้ใช้ตั้งไว้จากฟอร์ม) -> list ของ
    section ที่ตั้งใจรวม LECTURE เข้าด้วยกันจริง

    ใช้เฉพาะตอนตัดสินใจ "รวม LECTURE" เท่านั้น — ไม่เกี่ยวกับ _assign_parallel_labels/
    _parallel_groups ที่ใช้กันคนละเรื่อง (จับคู่ section ปกติ/LAB pairing) เจตนาแยก
    ฟังก์ชันนี้ออกมาต่างหากชัดเจน เพื่อไม่ให้กระทบวิชาอื่นที่ไม่ได้ตั้งค่านี้เลย
    (เช่น 254171 ที่เป็น parallel section ปกติ ไม่เกี่ยวกับการรวม LECTURE)

    สำคัญ (แก้ไขล่าสุด): ใช้ lecture_combine_group ตรงๆ แทนการเดาจาก
    is_lecture_combined + (subject_id, academic_year) แบบเดิม — เดิมมีปัญหาจริงเจอกับ
    วิชา 254171 ที่มี 2 สาขา (CS-Y1 กับ IT-Y1) ตั้งใจรวมกันเองแยกเป็นคนละกลุ่ม (CS รวม
    กับ CS, IT รวมกับ IT) แต่ is_lecture_combined=true ทุกแถวเหมือนกันหมด ระบบเดิม
    เลยไปรวมข้าม CS/IT กันหมดทั้งที่ไม่ตั้งใจ — ตอนนี้ section ไหนอยากรวมกับ section
    ไหน ต้องมี lecture_combine_group "ค่าเดียวกัน" เป๊ะ ไม่ใช่แค่ is_lecture_combined
    เป็น true เหมือนกันเฉยๆ (ดู routers/subject_selected.py หัวไฟล์อธิบายไว้ละเอียด)
    """
    groups: dict[str, list[dict]] = {}
    for section in data["sections"]:
        combine_group = section.get("lecture_combine_group")
        if not combine_group:
            continue
        groups.setdefault(combine_group, []).append(section)
    for key in groups:
        groups[key] = sorted(groups[key], key=lambda m: m["subject_selected_id"])
    return groups


def build_section_plan() -> list[dict]:
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
        fixed_room_id = section.get("fixed_room_id")
        is_fixed_room_split = False
        if fixed_room_id and fixed_room_id in rooms_by_id:
            threshold = rooms_by_id[fixed_room_id]["capacity"]
            is_fixed_room_split = bool(threshold and count > threshold)
        else:
            threshold = lab_capacity
            is_fixed_room_split = bool(threshold and count > threshold)

        plan.append(
            {
                "subject_selected_id": section["subject_selected_id"],
                "subject_id": section["subject_id"],
                "students": count,
                "sections": 2 if is_fixed_room_split else 1,
                "keep_fixed_room_both": is_fixed_room_split and bool(fixed_room_id),
            }
        )
    return plan


def build_session_list() -> list[dict]:
    data = get_cached_data()
    plan_by_id = {p["subject_selected_id"]: p for p in build_section_plan()}
    parallel_labels = _assign_parallel_labels(data)
    parallel_groups = _parallel_groups(data)
    combined_lecture_groups = _combined_lecture_groups(data)
    lecture_created_for_group: set[tuple] = set()

    # subject_id -> subject_type (เช่น "ELECTIVE", "CORE", "GENERAL") — ใช้ยกเว้น
    # hard rule full_day (เกิน 3 วิชา/วันของกลุ่มนิสิต) ให้วิชาเลือกเสรีเท่านั้น
    # เพราะนิสิตเป็นคนเลือกลงเองอยู่แล้ว รู้ตัวว่าตารางจะแน่นแค่ไหน (ดู candidate_scorer.py)
    subject_type_by_id = {s["subject_id"]: s.get("subject_type") for s in data["subjects"]}

    result = []
    for section in data["sections"]:
        parallel_label = parallel_labels.get(section["subject_selected_id"])
        base_id = f"SS{section['subject_selected_id']}"

        # ── LECTURE: สร้าง 1 session ต่อ 1 block ตาม lecture_hours ──
        lecture_blocks = section["lecture_hours"] or 0
        if lecture_blocks > 0:
            # ลองทาง "รวมตามที่ผู้ใช้ระบุไว้ชัดเจน" ก่อน (lecture_combine_group ตั้ง
            # ค่าไว้ — เช่น 273389 ที่ section 1 สอนกลุ่ม Y3+Y4, section 2 สอนกลุ่ม
            # IT-Y2 คนละกลุ่มเลย แต่ตั้งใจให้ LECTURE เรียนร่วมห้องเดียวกัน) ถ้าไม่มี
            # ค่านี้ (None) ค่อย fallback ไปทางเดิม (_parallel_group_key ที่บังคับ
            # group_ids ตรงกันเป๊ะ — ใช้กับ parallel section ปกติ เช่น 254171 ที่แยก
            # เพราะความจุห้องเกิน หรือ CS/IT ที่รวมกันเองแยกคนละกลุ่ม ไม่เกี่ยวกัน)
            combine_group = section.get("lecture_combine_group")
            cross_group_members = combined_lecture_groups.get(combine_group, []) if combine_group else []
            should_combine_cross_group = len(cross_group_members) > 1

            if should_combine_cross_group:
                group_key = combine_group
                group_members = cross_group_members
                should_combine = True
            else:
                group_key = _parallel_group_key(section)
                group_members = parallel_groups.get(group_key, [section])
                should_combine = len(group_members) > 1 and all(
                    m.get("is_lecture_combined") for m in group_members
                )

            if should_combine:
                # parallel group ตั้งใจรวมไว้จริง — รวมเป็น session เดียว สร้างแค่ครั้งเดียวต่อกลุ่ม
                if group_key not in lecture_created_for_group:
                    lecture_created_for_group.add(group_key)
                    combined_teacher_ids: list[str] = []
                    for m in group_members:
                        for tid in m.get("teacher_ids") or []:
                            if tid not in combined_teacher_ids:
                                combined_teacher_ids.append(tid)
                    combined_capacity = (
                        sum((m.get("max_capacity") or 0) for m in group_members) or None
                    )

                    lead = group_members[
                        0
                    ]  # ใช้ subject_selected_id ตัวแรกเป็นฐานของ session_id
                    lead_base_id = f"SS{lead['subject_selected_id']}"
                    lecture_sibling_key = f"{lead_base_id}-LEC"
                    is_continuous = lead["subject_id"] in CONTINUOUS_SUBJECTS

                    # รวมกลุ่มนิสิตจาก "ทุก" section ที่เข้าร่วม ไม่ใช่แค่ของ lead
                    # ตัวแรก — สำคัญมากสำหรับกรณีรวมข้ามกลุ่ม (เช่น 273389 ที่ต้องมี
                    # ทั้ง Y3, Y4, IT-Y2) ถ้าใช้แค่ lead["group_ids"] กลุ่มอื่นจะหาย
                    # ไปจากตารางเลย (กรณี parallel section ปกติที่ group_ids เหมือน
                    # กันเป๊ะอยู่แล้ว การรวมแบบนี้ก็ให้ผลเหมือนเดิมทุกประการ ไม่กระทบ)
                    combined_group_ids: list[str] = []
                    for m in group_members:
                        for gid in m.get("group_ids") or []:
                            if gid not in combined_group_ids:
                                combined_group_ids.append(gid)

                    if is_continuous:
                        # วิชาที่ต้อง lecture ติดกันในวันเดียว (เช่น 3 ชม.รวด) —
                        # สร้าง "1 session เดียว" ที่ครอบคลุมทั้ง lecture_blocks ชั่วโมง
                        # (ไม่ใช่หลาย session แยกกัน) จะได้เป็น session_id เดียวใน DB
                        # แล้ว frontend merge เป็นแท่งเดียวให้เองตาม timeslot_ids ที่มีครบ
                        result.append(
                            {
                                "session_id": lecture_sibling_key,
                                "subject_selected_id": lead["subject_selected_id"],
                                "subject_id": lead["subject_id"],
                                "subject_type": subject_type_by_id.get(lead["subject_id"]),
                                "session_type": "LECTURE",
                                "section": None,
                                "sibling_key": lecture_sibling_key,
                                "room_type": "LECTURE",
                                "teacher_ids": combined_teacher_ids,
                                "group_ids": combined_group_ids,
                                "max_capacity": combined_capacity,
                                "continuous_size": lecture_blocks,  # ← จำนวนชั่วโมงที่ต้องติดกัน
                            }
                        )
                    else:
                        for block_num in range(1, lecture_blocks + 1):
                            session_id = (
                                lecture_sibling_key
                                if lecture_blocks == 1
                                else f"{lecture_sibling_key}{block_num}"
                            )
                            result.append(
                                {
                                    "session_id": session_id,
                                    "subject_selected_id": lead["subject_selected_id"],
                                    "subject_id": lead["subject_id"],
                                    "subject_type": subject_type_by_id.get(lead["subject_id"]),
                                    "session_type": "LECTURE",
                                    "section": None,  # รวมกันแล้ว ไม่ต้องมี label คู่ขนานอีก
                                    "sibling_key": lecture_sibling_key,
                                    "room_type": "LECTURE",
                                    "teacher_ids": combined_teacher_ids,
                                    "group_ids": combined_group_ids,
                                    "max_capacity": combined_capacity,  # ← รวม capacity ทุก section แล้ว
                                    "continuous_size": None,
                                }
                            )
                # สมาชิกตัวอื่นในกลุ่มเดียวกัน ไม่ต้องสร้าง LECTURE ซ้ำ (ข้ามไปเลย)
            else:
                lecture_sibling_key = f"{base_id}-LEC" + (
                    f"-{parallel_label}" if parallel_label else ""
                )
                is_continuous = section["subject_id"] in CONTINUOUS_SUBJECTS

                if is_continuous:
                    # วิชาที่ต้อง lecture ติดกันในวันเดียว (เช่น 3 ชม.รวด) — สร้าง
                    # "1 session เดียว" ครอบคลุมทั้ง lecture_blocks ชั่วโมง ไม่ใช่หลาย
                    # session แยกกัน (จะได้เป็น session_id เดียวใน DB, frontend merge
                    # เป็นแท่งเดียวให้เองตาม timeslot_ids ที่มีครบ ไม่ต้องแก้ frontend)
                    result.append(
                        {
                            "session_id": lecture_sibling_key,
                            "subject_selected_id": section["subject_selected_id"],
                            "subject_id": section["subject_id"],
                            "subject_type": subject_type_by_id.get(section["subject_id"]),
                            "session_type": "LECTURE",
                            "section": parallel_label,
                            "sibling_key": lecture_sibling_key,
                            "room_type": "LECTURE",
                            "teacher_ids": section["teacher_ids"],
                            "group_ids": section["group_ids"],
                            "max_capacity": section.get("max_capacity"),
                            "continuous_size": lecture_blocks,  # ← จำนวนชั่วโมงที่ต้องติดกัน
                        }
                    )
                else:
                    for block_num in range(1, lecture_blocks + 1):
                        session_id = (
                            lecture_sibling_key
                            if lecture_blocks == 1
                            else f"{lecture_sibling_key}{block_num}"
                        )
                        result.append(
                            {
                                "session_id": session_id,
                                "subject_selected_id": section["subject_selected_id"],
                                "subject_id": section["subject_id"],
                                "subject_type": subject_type_by_id.get(section["subject_id"]),
                                "session_type": "LECTURE",
                                "section": parallel_label,  # ← ใส่ label คู่ขนาน (ถ้ามี) ให้ pairing ทำงาน
                                "sibling_key": lecture_sibling_key,
                                "room_type": "LECTURE",
                                "teacher_ids": section["teacher_ids"],
                                "group_ids": section["group_ids"],
                                "max_capacity": section.get("max_capacity"),
                                "continuous_size": None,
                            }
                        )
        lab_blocks = section["lab_hours"] or 0
        if lab_blocks > 0:
            team_teachers = section.get("teacher_ids") or []
            section_capacity = section.get("max_capacity") or 0
            keep_fixed_room_both = (
                False  # true เฉพาะกรณี 3 ที่แบ่งเพราะห้องล็อกไว้เล็กเกินไป
            )
            if parallel_label is not None:
                lab_units = [(parallel_label, team_teachers, section_capacity)]
            else:
                # เดิม: ถ้ามีอาจารย์ > 1 คนผูกกับ section เดียวกัน (team_teachers > 1)
                # เคยสมมติเอาเองว่าต้องแบ่งครึ่งนิสิตไปคนละห้อง เวลาเดียวกัน (เหมือน
                # parallel section ที่แยกจริง) — ผิด เพราะจริงๆ แล้วคือ team-teaching
                # ปกติ (สอนร่วมกันห้องเดียวกัน เวลาเดียวกัน กลุ่มเดียวกันทั้งหมด ไม่ได้
                # กด "แยก section" อะไรเลย) การแยก unit ทำให้ระบบไปเรียกร้องหา 2 ห้อง +
                # อาจารย์ 2 คน + กลุ่มนิสิต ว่างพร้อมกันเป๊ะ ซึ่งแคบเกินจริงจนหาไม่เจอ
                # ตอนนี้รวมเป็น LAB เดียวเสมอ ไม่ว่าจะมีกี่อาจารย์ก็ตาม (นอกจาก
                # parallel_label ที่เป็น section แยกจริงจาก DB ต่างหาก) — การแยกเพราะ
                # ความจุห้องเล็กเกิน (fixed_room_id) ยังคงทำงานผ่าน plan ด้านล่างตามปกติ
                plan = plan_by_id.get(section["subject_selected_id"])
                num_sections = plan["sections"] if plan else 1
                keep_fixed_room_both = bool(plan and plan.get("keep_fixed_room_both"))
                if num_sections == 2:
                    half_capacity = (
                        -(-section_capacity // 2) if section_capacity else None
                    )
                    lab_units = [
                        ("1", team_teachers, half_capacity),
                        ("2", team_teachers, half_capacity),
                    ]
                else:
                    lab_units = [(None, team_teachers, section_capacity)]

            for unit_idx, (letter, lab_teacher_ids, unit_capacity) in enumerate(
                lab_units
            ):
                lab_sibling_key = f"{base_id}-LAB" + (f"-{letter}" if letter else "")
                if keep_fixed_room_both:
                    unit_fixed_room_id = section.get("fixed_room_id")
                else:
                    unit_fixed_room_id = (
                        section.get("fixed_room_id") if unit_idx == 0 else None
                    )
                for block_num in range(1, lab_blocks + 1):
                    session_id = (
                        lab_sibling_key
                        if lab_blocks == 1
                        else f"{lab_sibling_key}-B{block_num}"
                    )
                    result.append(
                        {
                            "session_id": session_id,
                            "subject_selected_id": section["subject_selected_id"],
                            "subject_id": section["subject_id"],
                            "subject_type": subject_type_by_id.get(section["subject_id"]),
                            "session_type": "LAB",
                            "section": letter,
                            "sibling_key": lab_sibling_key,
                            "room_type": "LAB",
                            "teacher_ids": lab_teacher_ids,
                            "group_ids": section["group_ids"],
                            "max_capacity": unit_capacity,
                            "fixed_room_id": unit_fixed_room_id,
                        }
                    )

    return result