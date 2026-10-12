"""
test_rules.py — เทสต์กฎการจัดตาราง + การทำงานของ Agent ด้วย "ข้อมูลจำลอง"

ไม่ต่อ Supabase จริง (ใช้ฐานข้อมูลจำลองในหน่วยความจำ) และไม่เรียก LLM จริง (ใช้ LLM จำลอง)
-> รันได้บ่อยแค่ไหนก็ได้ ไม่แตะตารางจริง ไม่เสียเงิน ใช้เช็คหลังแก้โค้ดทุกครั้งว่าของเดิมไม่พัง

วิธีรัน (จาก root โปรเจกต์):
    python test_rules.py            # รันทุกข้อ
    python test_rules.py lab        # รันเฉพาะข้อที่ชื่อมีคำว่า lab
    python test_rules.py -v         # แสดงรายละเอียดระหว่างรัน

exit code: 0 = ผ่านทุกข้อ, 1 = มีข้อไม่ผ่าน
"""

import asyncio
import copy
import io
import random
import re
import sys
import time
import types as _types
import uuid
import warnings
from contextlib import redirect_stdout

warnings.filterwarnings("ignore")
VERBOSE = "-v" in sys.argv

# ═════════════ 1. ฐานข้อมูลจำลอง (ต้องติดตั้งก่อน import โค้ดของโปรเจกต์) ═════════════

DB: dict = {}
TABLES: dict = {}
_next_id = [1]


class _Query:
    def __init__(self, name):
        self.name, self.op, self.filters, self.rows = name, "select", [], None

    def select(self, *a, **k): self.op = "select"; return self
    def insert(self, rows): self.op, self.rows = "insert", rows if isinstance(rows, list) else [rows]; return self
    def delete(self): self.op = "delete"; return self
    def eq(self, c, v): self.filters.append(lambda r: r.get(c) == v); return self
    def neq(self, c, v): self.filters.append(lambda r: r.get(c) != v); return self
    def in_(self, c, vs): self.filters.append(lambda r: r.get(c) in vs); return self
    def limit(self, n): return self

    def execute(self):
        table = DB.setdefault(self.name, [])
        ok = lambda r: all(f(r) for f in self.filters)
        if self.op == "insert":
            for r in self.rows:
                r = dict(r)
                r.setdefault("id", _next_id[0])
                _next_id[0] += 1
                table.append(r)
            return _types.SimpleNamespace(data=[])
        if self.op == "delete":
            DB[self.name] = [r for r in table if not ok(r)]
            return _types.SimpleNamespace(data=[])
        return _types.SimpleNamespace(data=copy.deepcopy([r for r in table if ok(r)]))


def _load(key, filters=None, limit=1000):
    if key == "timetable":
        return copy.deepcopy(DB.get("timetable_ai", []))
    return copy.deepcopy(TABLES.get(key, []))


_fake_get_data = _types.ModuleType("agent_timetable.tools.get_data")
_fake_get_data.supabase = _types.SimpleNamespace(table=lambda name: _Query(name))
_fake_get_data.load = _load
_fake_get_data.load_all = lambda: {}
_fake_get_data.load_subject_selected_full = lambda *a, **k: []
_fake_get_data.TABLE_MAP = {}
sys.modules["agent_timetable.tools.get_data"] = _fake_get_data

# โมเดลจำลอง: ไม่ต้องมี API key และไม่เรียก LLM จริง
_fake_models = _types.ModuleType("agent_timetable.models")
_fake_models.USE_OPENROUTER = True
_fake_models.make_model = lambda reasoning=False: "fake-model"
_fake_models.make_planner = lambda reasoning=False: None
sys.modules["agent_timetable.models"] = _fake_models

with redirect_stdout(io.StringIO()):
    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_response import LlmResponse
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    from agent_timetable.tools.scheduling import load_data
    from agent_timetable.tools.scheduling import auto_assign
    from agent_timetable.tools.scheduling.auto_assign import auto_assign_all
    from agent_timetable.tools.scheduling.assignment_store import (
        record_assignment, delete_session_assignment, manual_place_session,
    )
    from agent_timetable.tools.scheduling.section_logic import build_session_list
    from agent_timetable.tools.scheduling.find_issues import find_issues
    from agent_timetable.tools.scheduling import pipeline_steps
    from agent_timetable import scheduling_agent
    import check_schedule


# ═════════════ 2. ตัวช่วยสร้างข้อมูล ═════════════

DAYS = ("MON", "TUE", "WED", "THU", "FRI")
HOURS = (8, 10, 13, 15)          # คาบละ 2 ชม.: 08-10, 10-12, 13-15, 15-17 (พักเที่ยง 12-13)


def timeslots():
    ts, i = [], 1
    for b, (d, h) in enumerate([(d, h) for d in DAYS for h in HOURS], 1):
        for k in (0, 1):
            ts.append({"timeslot_id": i, "block_id": b, "day": d,
                       "start_time": f"{h + k:02d}:00:00", "end_time": f"{h + k + 1:02d}:00:00"})
            i += 1
    return ts


def make_world(rooms, subjects, teachers, groups, sections, teacher_unavail=(), room_unavail=()):
    """ตั้งฐานข้อมูลจำลองใหม่ทั้งหมด คืน (timeslots, day_of, hour_of)"""
    ts = timeslots()
    TABLES.clear()
    TABLES.update({
        "timeslots": ts, "rooms": rooms,
        "subjects": [{"subject_id": s, "name_thai": s, "subject_type": "CORE"} for s in subjects],
        "teachers": [{"teacher_id": t, "teacher_name": t} for t in teachers],
        "groups": [{"group_id": g, "total_students": n} for g, n in groups.items()],
        "teacher_unavailability": [{"teacher_id": t, "timeslot_id": x} for t, x in teacher_unavail],
        "room_unavailability": [{"room_id": r, "timeslot_id": x} for r, x in room_unavail],
    })
    DB.clear()
    DB.update({"timetable_ai": [], "subject_selected": sections, "subject_selected_preferred_timeslots": []})
    load_data.refresh_cache()
    return ts, {t["timeslot_id"]: t["day"] for t in ts}, {t["timeslot_id"]: int(t["start_time"][:2]) for t in ts}


def room(rid, rtype, cap=100):
    return {"room_id": rid, "room_name": rid, "room_type": rtype, "capacity": cap}


def section(sid, subject, teachers, groups, lec=1, lab=0, combine=None, cap=None):
    return {"id": sid, "subject_id": subject, "academic_year": 2569, "max_capacity": cap, "fixed_room_id": None,
            "lecture_combine_group": combine,
            "subjects": {"subject_id": subject, "name_thai": subject, "name_english": subject,
                         "subject_type": "CORE", "lecture_hours": lec, "lab_hours": lab},
            "subject_selected_teachers": [{"teacher_id": t} for t in teachers],
            "subject_selected_groups": [{"group_id": g, "is_lecture_combined": False} for g in groups]}


def slots_at(ts, day, hour):
    return [t["timeslot_id"] for t in ts if t["day"] == day and int(t["start_time"][:2]) == hour]


def block(ts, day, hour):
    """timeslot_id ของคาบ 2 ชม. ที่เริ่ม day/hour (เป็น str แบบที่ระบบใช้)"""
    return [str(t["timeslot_id"]) for t in ts if t["day"] == day and int(t["start_time"][:2]) in (hour, hour + 1)]


def run_assign(seed):
    random.seed(seed)
    DB["timetable_ai"] = []
    load_data.refresh_cache()
    with redirect_stdout(io.StringIO()):
        result = auto_assign_all()
    load_data.refresh_cache()
    return result


def placed(session_id):
    return [r for r in DB["timetable_ai"] if r["session_id"] == session_id]


def no_rule_errors():
    """ใช้ตัวตรวจ check_schedule.py เป็นกรรมการกลาง: ต้องไม่มีหมวดไหนเป็น ❌"""
    return [r for r in check_schedule.run_checks() if r["level"] == check_schedule.FAIL]


# ═════════════ 3. เทสต์ ═════════════

def test_basic_schedule_is_valid():
    """จัดตารางทั่วไป 2 กลุ่ม หลายวิชา: ต้องจัดครบ และไม่ผิดกฎข้อไหนเลย (ตรวจด้วย check_schedule)"""
    subs = [f"S{k}" for k in range(5)]
    make_world([room("R1", "LECTURE"), room("R2", "LECTURE"), room("L1", "LAB")], subs,
               [f"T{k}" for k in range(5)], {"CS-Y1": 40, "IT-Y1": 40},
               [section(k + 1, s, [f"T{k}"], ["CS-Y1" if k % 2 else "IT-Y1"], 1, 1) for k, s in enumerate(subs)])
    for seed in range(5):
        r = run_assign(seed)
        assert r["failed_count"] == 0, f"seed {seed}: จัดไม่ได้ {r['failed_count']} วิชา"
        errs = no_rule_errors()
        assert not errs, f"seed {seed}: ผิดกฎ {[(e['title'], e['items'][:2]) for e in errs]}"


def test_lab_two_sections_same_teacher_back_to_back():
    """LAB นิสิต 50 คน ห้องแล็บจุ 30 -> แบ่ง 2 section อาจารย์คนเดียว ต้องห้องเดียวกันและเรียนต่อกัน"""
    ts, day, hour = make_world([room("R", "LECTURE", 200), room("LAB-A", "LAB", 30), room("LAB-B", "LAB", 30)],
                               ["X"], ["T1"], {"G1": 50}, [section(1, "X", ["T1"], ["G1"], 1, 1)])
    for seed in range(10):
        run_assign(seed)
        a, b = placed("SS1-LAB-1"), placed("SS1-LAB-2")
        assert a and b, "LAB section ใดหายไป"
        ha = sorted(hour[r["timeslot_id"]] for r in a)
        hb = sorted(hour[r["timeslot_id"]] for r in b)
        assert day[a[0]["timeslot_id"]] == day[b[0]["timeslot_id"]], f"seed {seed}: คนละวัน"
        assert ha[-1] + 1 == hb[0] or hb[-1] + 1 == ha[0], f"seed {seed}: ไม่ต่อกัน {ha} / {hb}"
        assert a[0]["room_id"] == b[0]["room_id"], f"seed {seed}: คนละห้อง"


def test_lab_two_sections_different_teachers_same_time():
    """2 section คนละอาจารย์ กลุ่มเดียวกัน (แบ่งนิสิตครึ่งๆ) -> LAB เวลาเดียวกัน คนละห้อง
    และตัวตรวจต้องไม่นับว่า "นิสิตชนกัน" (เจอจริงกับ 254171 IT-Y1 หลัง import ข้อมูลใหม่)"""
    make_world([room("R1", "LECTURE", 200), room("R2", "LECTURE", 200), room("LAB-A", "LAB", 30), room("LAB-B", "LAB", 30)],
               ["X"], ["T1", "T2"], {"G1": 50},
               [section(1, "X", ["T1"], ["G1"], 1, 1, cap=25), section(2, "X", ["T2"], ["G1"], 1, 1, cap=25)])
    for seed in range(5):
        r = run_assign(seed)
        assert r["failed_count"] == 0, f"seed {seed}: จัดไม่ได้ {r['failed']}"
        a, b = placed("SS1-LAB-1"), placed("SS2-LAB-2")
        assert {x["timeslot_id"] for x in a} == {x["timeslot_id"] for x in b}, "ต้องเรียนเวลาเดียวกัน"
        assert a[0]["room_id"] != b[0]["room_id"], "ต้องคนละห้อง"
        errs = no_rule_errors()
        assert not errs, f"seed {seed}: ตัวตรวจฟ้องผิด {[(e['title'], e['items'][:2]) for e in errs]}"


def test_lab_never_same_day_as_combined_lecture():
    """LECTURE เรียนรวม CS+IT แต่ LAB แยกกลุ่ม: LAB ห้ามอยู่วันเดียวกับ LECTURE"""
    make_world([room("R", "LECTURE", 200), room("L1", "LAB"), room("L2", "LAB")], ["X"], ["T1", "T2"],
               {"CS-Y4": 40, "IT-Y4": 40},
               [section(10, "X", ["T1"], ["CS-Y4"], 1, 1, combine="X-Y4"),
                section(20, "X", ["T2"], ["IT-Y4"], 1, 1, combine="X-Y4")])
    for seed in range(10):
        run_assign(seed)
        errs = no_rule_errors()
        assert not errs, f"seed {seed}: {[(e['title'], e['items'][:2]) for e in errs]}"


def test_lecture_leaves_room_for_lab_after_it():
    """LECTURE ของวิชาที่มี LAB ควรไม่ไปอยู่วันท้ายสัปดาห์จน LAB ไม่มีวันหลัง LECTURE ให้ลง"""
    subs = [f"S{k}" for k in range(5)]
    # ห้องบรรยายไม่ว่าง จ.-อ. ช่วงสาย -> LECTURE ถูกดันไปวันท้ายๆ ง่าย
    busy = [("R1", t["timeslot_id"]) for t in timeslots()
            if t["day"] in ("MON", "TUE") and int(t["start_time"][:2]) >= 10]
    ts, day, hour = make_world([room("R1", "LECTURE"), room("L1", "LAB")], subs, subs, {"G1": 40},
                               [section(k + 1, s, [s], ["G1"], 1, 1) for k, s in enumerate(subs)], room_unavail=busy)
    friday_lec = soft = failed = 0
    for seed in range(10):
        r = run_assign(seed)
        failed += r["failed_count"]
        friday_lec += sum(1 for sid in {x["session_id"] for x in DB["timetable_ai"]}
                          if sid.endswith("-LEC") and day[placed(sid)[0]["timeslot_id"]] == "FRI")
        soft += sum(1 for i in find_issues() if i["type"] == "lecture_before_lab")
    assert failed == 0, f"จัดไม่ได้ {failed}"
    assert friday_lec <= 2, f"LECTURE ไปตกวันศุกร์ {friday_lec} ครั้งจาก 10 รอบ (ควรแทบไม่มี)"
    assert soft <= 5, f"LAB อยู่ก่อน LECTURE {soft} จุดจาก 10 รอบ (ก่อนแก้ประมาณ 12)"


def test_lecture_blocks_can_use_another_room():
    """LECTURE 2 block ต่อสัปดาห์ ไม่มี section: block แรกได้ห้อง R1 แต่ R1 ไม่ว่างอีกเลย
    -> block ที่สองต้องย้ายไปห้องอื่นได้ (เดิมบังคับห้องเดียวกัน แล้ว "จัดไม่ได้" ทั้งที่ห้องอื่นว่าง
    เจอจริงกับ 254374 ปี 3)"""
    ts = timeslots()
    mon8 = {int(x) for x in block(ts, "MON", 8)}
    busy = ([("R1", t["timeslot_id"]) for t in ts if t["timeslot_id"] not in mon8] +
            [("R2", t["timeslot_id"]) for t in ts if t["day"] in ("MON", "TUE")])
    make_world([room("R1", "LECTURE"), room("R2", "LECTURE")], ["X"], ["T1"], {"G1": 40},
               [section(1, "X", ["T1"], ["G1"], 2, 0)], room_unavail=busy)
    extra, auto_assign.EXTRA_ATTEMPTS = auto_assign.EXTRA_ATTEMPTS, 0   # ห้ามให้การจัดซ้ำช่วย ต้องได้ในรอบเดียว
    try:
        for seed in range(10):
            r = run_assign(seed)
            assert r["failed_count"] == 0, f"seed {seed}: จัดไม่ได้ {r['failed']}"
            assert len({x["session_id"] for x in DB["timetable_ai"]}) == 2, "ต้องมี LECTURE 2 block"
            errs = no_rule_errors()
            assert not errs, f"seed {seed}: ผิดกฎ {[(e['title'], e['items'][:2]) for e in errs]}"
    finally:
        auto_assign.EXTRA_ATTEMPTS = extra


def test_elective_not_counted_in_three_per_day():
    """กฎ "ไม่เกิน 3 วิชา/วัน" ไม่นับวิชาเลือก: มีวิชาบังคับ 2 + วิชาเลือก 2 แล้ว ยังวางวิชาบังคับที่ 3 ได้
    (เดิมตัวจัดนับวิชาเลือกด้วย แต่ตัวตรวจไม่นับ -> วิชาบังคับถูกบล็อกโดยไม่จำเป็น)"""
    from agent_timetable.tools.scheduling.candidate_scorer import _check_full_day, _build_day_order
    ts, day, hour = make_world([room("R1", "LECTURE")], ["C1", "C2", "C3", "E1", "E2"], ["T1"], {"G1": 30}, [])
    for t in TABLES["subjects"]:
        if t["subject_id"].startswith("E"):
            t["subject_type"] = "ELECTIVE"
    load_data.refresh_cache()
    mon = [t["timeslot_id"] for t in ts if t["day"] == "MON"]
    placed_rows = [{"group_id": "G1", "subject_id": sid, "timeslot_id": mon[k * 2]}
                   for k, sid in enumerate(["C1", "C2", "E1", "E2"])]
    order = _build_day_order(ts)
    assert _check_full_day(["G1"], "C3", [str(mon[-1])], placed_rows, order, "CORE"), \
        "วิชาบังคับที่ 3 ต้องวางได้ (วิชาเลือกไม่นับ)"
    placed_rows.append({"group_id": "G1", "subject_id": "C3", "timeslot_id": mon[-2]})
    assert not _check_full_day(["G1"], "C4", [str(mon[-1])], placed_rows, order, "CORE"), \
        "วิชาบังคับที่ 4 ต้องถูกบล็อก"


def test_continuous_subject_is_placed_first():
    """วิชาเรียนรวด 3 ชม. (273252) มีช่องให้ลงน้อยที่สุด ต้องได้ที่ทุกครั้ง แม้อาจารย์ว่างแค่ 3 วัน"""
    subs = [f"S{k}" for k in range(6)]
    ts, day, hour = make_world(
        [room("R1", "LECTURE"), room("R2", "LECTURE"), room("L1", "LAB")], subs + ["273252"], subs + ["LAW"],
        {"IT-Y2": 40},
        [section(k + 1, s, [s], ["IT-Y2"], 1, 1) for k, s in enumerate(subs)] + [section(99, "273252", ["LAW"], ["IT-Y2"], 3, 0)])
    TABLES["teacher_unavailability"] = [{"teacher_id": "LAW", "timeslot_id": t["timeslot_id"]}
                                        for t in ts if t["day"] in ("TUE", "THU")]
    for seed in range(15):
        r = run_assign(seed)
        assert not any(f["subject_id"] == "273252" for f in r["failed"]), f"seed {seed}: 273252 จัดไม่ได้"
        rows = placed("SS99-LEC")
        hs = sorted(hour[x["timeslot_id"]] for x in rows)
        assert len(hs) == 3 and hs[-1] - hs[0] == 2, f"seed {seed}: ไม่ได้เรียนรวด 3 ชม. {hs}"


def test_273100_same_time_different_rooms_15_17():
    """273100: section CS ปี 1 กับ IT ปี 1 (คนละกลุ่ม คนละอาจารย์) ต้องเวลาเดียวกัน คนละห้อง ช่วง 15-17"""
    ts, day, hour = make_world(
        [room(r, "LECTURE", 120) for r in ("R1", "R2", "R3")], ["273100", "Z"], ["A1", "A2", "B1", "B2", "Z1"],
        {"CS-Y1": 110, "IT-Y1": 86},
        [section(1, "273100", ["A1", "A2"], ["CS-Y1"]), section(2, "273100", ["B1", "B2"], ["IT-Y1"]),
         section(3, "Z", ["Z1"], ["CS-Y1"])])
    for seed in range(10):
        run_assign(seed)
        a, b = placed("SS1-LEC"), placed("SS2-LEC")
        assert a and b, f"seed {seed}: section ใดหายไป"
        ta, tb = {r["timeslot_id"] for r in a}, {r["timeslot_id"] for r in b}
        assert ta == tb, f"seed {seed}: ไม่ตรงเวลากัน"
        assert a[0]["room_id"] != b[0]["room_id"], f"seed {seed}: ห้องเดียวกัน"
        assert all(hour[t] >= 15 for t in ta), f"seed {seed}: ไม่อยู่ช่วง 15-17"


def test_place_unscheduled_subject_by_drag():
    """ลากวิชาที่จัดไม่ได้มาวางเอง: วางช่องว่างได้, ช่องที่ชนต้องบอกเหตุผล, วิชาเรียนรวดห้ามคร่อมพักเที่ยง"""
    ts, day, hour = make_world([room("R1", "LECTURE"), room("R2", "LECTURE")], ["A", "273252"], ["T1", "L1"],
                               {"IT-Y2": 40}, [section(1, "A", ["T1"], ["IT-Y2"]), section(2, "273252", ["L1"], ["IT-Y2"], 3, 0)])
    s = {x["session_id"]: x for x in build_session_list()}
    record_assignment(s["SS1-LEC"], {"timeslot_ids": block(ts, "MON", 8), "room_id": "R1",
                                     "room_name": "R1", "timeslot_label": "-"})
    mon8 = str(slots_at(ts, "MON", 8)[0])
    r = manual_place_session("SS2-LEC", mon8)
    assert not r["success"] and "IT-Y2" in r["reason"], f"ต้องบอกว่ากลุ่มชน: {r}"
    r = manual_place_session("SS2-LEC", str(slots_at(ts, "TUE", 10)[0]))
    assert not r["success"] and "พักเที่ยง" in r["reason"], f"ต้องบอกเรื่องพักเที่ยง: {r}"
    r = manual_place_session("SS2-LEC", str(slots_at(ts, "WED", 13)[0]))
    assert r["success"], r
    assert len(placed("SS2-LEC")) == 3, "ต้องได้ 3 ชม."
    r = manual_place_session("SS2-LEC", str(slots_at(ts, "WED", 13)[0]))
    assert not r["success"] and "อยู่ในตารางแล้ว" in r["reason"], r


# ── Agent (ใช้ LLM จำลองที่ตัดสินใจแบบคงที่ จะได้เทสต์ "ระบบรอบตัว Agent" ได้โดยไม่เสียเงิน) ──

class FakeLlm(BaseLlm):
    model: str = "fake"
    decide: str = "pick"            # "pick" = เลือกตัวเลือกแรก / "decline" = สั่งหยุด
    calls: list = []

    async def generate_content_async(self, req, stream=False):
        si = req.config.system_instruction
        si = si if isinstance(si, str) else "".join(p.text or "" for p in si.parts)
        usage = types.GenerateContentResponseUsageMetadata(prompt_token_count=100, candidates_token_count=10)
        self.calls.append(sorted(req.tools_dict or {}))
        last = req.contents[-1] if req.contents else None
        text = lambda t: LlmResponse(content=types.Content(role="model", parts=[types.Part(text=t)]), usage_metadata=usage)
        call = lambda n, a: LlmResponse(content=types.Content(role="model", parts=[types.Part(
            function_call=types.FunctionCall(name=n, args=a))]), usage_metadata=usage)
        if last and any(p.function_response for p in (last.parts or [])):
            yield text("ตัดสินใจแล้ว"); return
        if not req.tools_dict:
            yield text("จัดไม่ได้แน่: ตัวอย่างสรุปปัญหาข้อมูล"); return
        if self.decide == "decline":
            yield call("exit_loop", {"reason": "ไม่คุ้มที่จะย้าย"}); return
        if "ตารางจัดได้แล้ว" in si:
            yield call("suggest_soft_fixes", {"option_ids": re.findall(r'"option_id": "(S\d+)"', si)[:1],
                                              "reason": "ย้าย LAB ไปหลัง LECTURE"}); return
        yield call("suggest_retry", {"priority_subject_ids": re.findall(r'"subject_id": "([^"]+)"', si)[:1],
                                     "option_ids": re.findall(r'"option_id": "(O\d+)"', si)[:1],
                                     "reason": "ให้วิชาที่ขวางหลบ"})


def run_pipeline(decide="pick"):
    llm = FakeLlm(decide=decide, calls=[])
    scheduling_agent.checker_decision_agent.model = llm
    scheduling_agent.data_review_agent.model = llm
    svc = InMemorySessionService()
    runner = Runner(agent=scheduling_agent.scheduling_pipeline, app_name="t", session_service=svc)

    async def go():
        sid = f"t-{uuid.uuid4()}"
        await svc.create_session(app_name="t", user_id="u", session_id=sid)
        final = ""
        async for ev in runner.run_async(user_id="u", session_id=sid, new_message=types.Content(
                role="user", parts=[types.Part(text="จัดตารางเรียน")])):
            if ev.is_final_response() and ev.content and ev.content.parts:
                final = ev.content.parts[0].text
        s = await svc.get_session(app_name="t", user_id="u", session_id=sid)
        return final, s.state.get("final_report") or {}

    with redirect_stdout(io.StringIO()) as out:
        final, report = asyncio.run(go())
    if VERBOSE:
        print(out.getvalue())
    return final, report, llm.calls


def _blocked_world():
    """วิชา B จัดไม่ได้เพราะวิชา A จองคาบเดียวที่ B ลงได้ (A ย้ายไปวันอื่นได้)"""
    ts, day, hour = make_world([room("R1", "LECTURE"), room("R2", "LECTURE")], ["A", "B", "C"], ["T1", "T2", "T3"],
                               {"G1": 30, "G2": 30, "G3": 30},
                               [section(10, "A", ["T1"], ["G1"]), section(20, "B", ["T2"], ["G1"]),
                                section(30, "C", ["T3"], ["G3"])])
    only_mon8 = {int(x) for x in block(ts, "MON", 8)}
    TABLES["teacher_unavailability"] = (
        [{"teacher_id": "T2", "timeslot_id": t["timeslot_id"]} for t in ts if t["timeslot_id"] not in only_mon8] +
        [{"teacher_id": "T1", "timeslot_id": t["timeslot_id"]} for t in ts if t["day"] not in ("MON", "TUE")])
    random.seed(0)
    random.choice = lambda seq: seq[0]          # ให้ Greedy เลือก จ. 08:00 ให้ A ก่อน (สร้างปัญหาแบบคงที่)


def _agent_test(decide):
    """รัน pipeline ในโลกที่ Greedy จัด B ไม่ได้ — ปิดการจัดซ้ำหลายรอบ (EXTRA_ATTEMPTS=0)
    เพื่อบังคับให้ CheckerAgent เป็นคนแก้ (ถ้าเปิดไว้ อัลกอริทึมจะแก้เองได้ก่อนถึง Agent)"""
    _random_choice, _extra = random.choice, auto_assign.EXTRA_ATTEMPTS
    try:
        auto_assign.EXTRA_ATTEMPTS = 0
        _blocked_world()
        return run_pipeline(decide)
    finally:
        random.choice, auto_assign.EXTRA_ATTEMPTS = _random_choice, _extra


def test_multi_start_retries_unlucky_run():
    """รอบแรกโชคร้าย (A แย่งคาบเดียวที่ B ลงได้) -> auto_assign_all จัดซ้ำโดยให้ B จัดก่อน -> ครบ"""
    _random_choice = random.choice
    try:
        _blocked_world()
        with redirect_stdout(io.StringIO()) as log:
            result = auto_assign_all()
    finally:
        random.choice = _random_choice
    assert result["failed_count"] == 0, f"ยังมีวิชาที่จัดไม่ได้: {result['failed']}"
    assert "จัดซ้ำรอบ 1/" in log.getvalue(), "ควรมีการจัดซ้ำอย่างน้อย 1 รอบ"
    fails = [c for c in check_schedule.run_checks() if c["level"] == check_schedule.FAIL]
    assert not fails, fails


def test_agent_fixes_blocked_subject():
    """Greedy จัด B ไม่ได้ -> CheckerAgent เลือกให้ A หลบ -> รอบ 2 จัดได้ครบ (เรียก LLM ไม่กี่ครั้ง)"""
    final, report, calls = _agent_test("pick")
    assert report.get("fully_complete"), f"ยังจัดไม่ครบ: {final}"
    assert report.get("attempts_used") == 2, f"ควรใช้ 2 รอบ ได้ {report.get('attempts_used')}"
    assert "CheckerAgent" in final, f"สรุปต้องบอกการตัดสินใจของ Agent: {final}"
    assert len(calls) <= 4, f"เรียก LLM {len(calls)} ครั้ง (มากเกินไป)"


def test_agent_can_decline_and_loop_stops():
    """ถ้า Agent ตัดสินใจไม่แก้ ระบบต้องหยุดทันที (ไม่วนเปล่า) และบอกเหตุผลในสรุป"""
    final, report, calls = _agent_test("decline")
    assert report.get("attempts_used") == 1, f"ต้องหยุดหลังรอบแรก ได้ {report.get('attempts_used')}"
    assert "ไม่คุ้มที่จะย้าย" in final, final


def test_no_llm_call_when_nothing_to_decide():
    """ตารางดีอยู่แล้ว + ข้อมูลไม่มีปัญหา -> ไม่ต้องเรียก LLM เลย (ไม่เสีย token)"""
    make_world([room("R1", "LECTURE")], ["A"], ["T1"], {"G1": 30}, [section(1, "A", ["T1"], ["G1"])])
    final, report, calls = run_pipeline()
    assert report.get("fully_complete"), final
    assert calls == [], f"ไม่ควรเรียก LLM แต่เรียก {len(calls)} ครั้ง"


def test_data_check_finds_problems_before_scheduling():
    """DataGatherAgent ต้องเจอปัญหาข้อมูลก่อนจัด: ไม่มีอาจารย์ / ไม่มีห้องจุพอ / อาจารย์ว่างไม่พอ"""
    from agent_timetable.tools.scheduling.data_check import check_data_readiness
    ts, day, hour = make_world([room("R1", "LECTURE", 50)], ["A", "B", "C"], ["T1", "T3"], {"G1": 30, "BIG": 300},
                               [section(1, "A", ["T1"], ["G1"]), section(2, "B", [], ["G1"]),
                                section(3, "C", ["T3"], ["BIG"])])
    TABLES["teacher_unavailability"] = [{"teacher_id": "T1", "timeslot_id": t["timeslot_id"]} for t in ts]
    load_data.refresh_cache()
    kinds = {i["kind"] for i in check_data_readiness()}
    assert {"no_teacher", "no_room_big_enough", "teacher_overbooked"} <= kinds, kinds


def test_checker_catches_real_errors():
    """ตัวตรวจ check_schedule.py ต้องจับข้อผิดได้จริง (ใส่ตารางที่ผิดเข้าไปเอง แล้วดูว่าฟ้องไหม)"""
    ts, day, hour = make_world([room("R1", "LECTURE"), room("L1", "LAB")], ["A", "B"], ["T1", "T2"], {"G1": 30},
                               [section(1, "A", ["T1"], ["G1"], 1, 1), section(2, "B", ["T2"], ["G1"])])
    s = {x["session_id"]: x for x in build_session_list()}
    mon8 = block(ts, "MON", 8)
    put = lambda sid, slots, rid: record_assignment(s[sid], {"timeslot_ids": slots, "room_id": rid,
                                                             "room_name": rid, "timeslot_label": "-"})
    put("SS1-LEC", mon8, "R1")
    put("SS2-LEC", mon8, "R1")                      # ห้องเดียวกัน คาบเดียวกัน + กลุ่มเดียวกัน -> ชน
    put("SS1-LAB", block(ts, "MON", 10), "L1")      # LAB วันเดียวกับ LECTURE
    titles = {r["title"].split(".")[0] for r in check_schedule.run_checks() if r["level"] == check_schedule.FAIL}
    assert {"2", "6"} <= titles, f"ต้องฟ้องหมวด 2 (ชน) และ 6 (LAB วันเดียวกับ LECTURE) ได้แค่ {titles}"


# ═════════════ 4. ตัวรัน ═════════════

def main():
    keyword = next((a for a in sys.argv[1:] if not a.startswith("-")), "")
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f) and keyword in n]
    passed = 0
    for n, f in tests:
        started = time.time()
        try:
            f()
            passed += 1
            print(f"✅ {n}  ({time.time() - started:.1f}s)")
        except AssertionError as e:
            print(f"❌ {n}\n     {e}")
        except Exception as e:  # noqa: BLE001
            print(f"💥 {n} — error: {e!r}")
            if VERBOSE:
                import traceback
                traceback.print_exc()
        if VERBOSE:
            print(f"     {f.__doc__.strip()}")
    print("-" * 60)
    print(f"ผ่าน {passed}/{len(tests)} ข้อ")
    sys.exit(0 if passed == len(tests) else 1)


if __name__ == "__main__":
    main()