import json
import time
from typing import AsyncGenerator

from google.adk.agents import Agent, BaseAgent, SequentialAgent, LoopAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.events import Event, EventActions
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from .models import make_model, make_planner
from .cost_tracker import track_usage, reset_usage, usage_summary, print_summary
from .tools.scheduling.load_data import get_cached_data
from .tools.scheduling.retry_hints import merge_hints
from .tools.scheduling.pipeline_steps import (
    MAX_ATTEMPTS, MAX_DATA_ISSUES_FOR_LLM, gather_step, assign_step, prepare_decision, build_summary,
)

MAX_OPTIONS_PER_ATTEMPT = 3
CHECK_REUSE_SECONDS = 600   # ผลตรวจจาก /check-data ใช้ต่อได้ภายใน 10 นาที เกินนั้นดึง + ตรวจใหม่ (กันข้อมูลเก่า)

_started: dict[str, float] = {}


def _start_timer(callback_context: CallbackContext):
    _started[callback_context.agent_name] = time.time()


def _stop_timer(callback_context: CallbackContext):
    t = _started.pop(callback_context.agent_name, None)
    if t is not None:
        print(f"[timing] {callback_context.agent_name}: {time.time() - t:.1f}s")


def _start_pipeline(callback_context: CallbackContext):
    _start_timer(callback_context)
    reset_usage(callback_context)


def _stop_pipeline(callback_context: CallbackContext):
    _stop_timer(callback_context)
    print_summary(callback_context.state)
    try:
        report = dict(callback_context.state.get("final_report") or {})
        report["llm_cost"] = usage_summary(callback_context.state)
        callback_context.state["final_report"] = report
    except Exception as e:  # noqa: BLE001 — นับค่าใช้จ่ายพลาด ไม่ให้กระทบผลจัดตาราง
        print(f"[cost] ใส่ค่าใช้จ่ายใน final_report ไม่สำเร็จ: {e!r}")



class _State:

    def __init__(self, state):
        self._base, self.delta = state, {}

    def get(self, key, default=None):
        return self.delta[key] if key in self.delta else self._base.get(key, default)

    def __getitem__(self, key):
        return self.get(key)

    def __setitem__(self, key, value):
        self.delta[key] = value


def _event(agent, ctx, state=None, text=None, escalate=False) -> Event:
    actions = EventActions(state_delta=dict(state.delta) if state else {})
    if state:
        state.delta.clear()
    if escalate:
        actions.escalate = True   # escalate = สั่ง LoopAgent หยุดวน
    content = types.Content(role="model", parts=[types.Part(text=text)]) if text else None
    return Event(invocation_id=ctx.invocation_id, author=agent.name, branch=ctx.branch,
                content=content, actions=actions)


def _log(tool_context: ToolContext, entry: dict) -> None:
    tool_context.state["attempt_log"] = list(tool_context.state.get("attempt_log") or []) + [entry]


def suggest_retry(tool_context: ToolContext, priority_subject_ids: list[str],
                option_ids: list[str], reason: str) -> dict:

    valid = {s["subject_id"] for s in get_cached_data()["subjects"]}
    prio = [str(s) for s in priority_subject_ids if str(s) in valid]
    option_map = tool_context.state.get("fix_options") or {}
    chosen = [o for o in option_ids if o in option_map][:MAX_OPTIONS_PER_ATTEMPT]
    if not prio and not chosen:
        return {"accepted": False, "reason": "subject_id/option_id ไม่ตรงกับข้อมูลที่ให้"}

    forbidden: dict[str, list[str]] = {}
    for o in chosen:
        forbidden.setdefault(option_map[o]["session_id"], []).extend(option_map[o]["timeslot_ids"])
    tool_context.state["retry_hints"] = merge_hints(tool_context.state.get("retry_hints"), prio, forbidden)
    tool_context.state["pending_moves"] = [option_map[o] for o in chosen]
    _log(tool_context, {"advice_for_attempt": (tool_context.state.get("attempt_no") or 0) + 1,
                        "priority_subject_ids": prio, "options": chosen, "reason": reason})
    return {"accepted": True, "priority_subject_ids": prio, "options": chosen}


def suggest_soft_fixes(tool_context: ToolContext, option_ids: list[str], reason: str) -> dict:
    option_map = tool_context.state.get("soft_options") or {}
    chosen, used = [], set()
    for o in option_ids:
        opt = option_map.get(o)
        if opt and opt["session_id"] not in used and len(chosen) < MAX_OPTIONS_PER_ATTEMPT:
            chosen.append(o)
            used.add(opt["session_id"])
    if not chosen:
        return {"accepted": False, "reason": "option_id ไม่ตรงกับข้อมูลที่ให้"}

    tool_context.state["pending_soft_fixes"] = [option_map[o] for o in chosen]
    _log(tool_context, {"advice_for_attempt": (tool_context.state.get("attempt_no") or 0) + 1,
                        "soft_options": chosen, "reason": reason})
    return {"accepted": True, "options": chosen}


def exit_loop(tool_context: ToolContext, reason: str = "") -> dict:
    _log(tool_context, {"declined_after_attempt": tool_context.state.get("attempt_no") or 0,
                        "reason": reason or "ไม่มีตัวเลือกที่คุ้มจะแก้"})
    tool_context.actions.escalate = True
    return {"stopped": True}

# ความยากของการแก้แต่ละแบบ (ให้ LLM ชั่งว่าคุ้มแก้ก่อนไหม)
_FIX_EFFORT = {
    "teacher_overbooked": "ง่าย (เปิดเวลาว่างอาจารย์ในระบบ)", "teacher_tight": "ง่าย (เปิดเวลาว่างอาจารย์ในระบบ)",
    "team_no_common_time": "ง่าย (เปิดเวลาว่างอาจารย์ในระบบ)", "sync_window": "ง่าย (เปิดเวลาว่างอาจารย์ในระบบ)",
    "no_teacher": "ง่าย (ผูกอาจารย์ให้วิชา)", "no_group": "ง่าย (ผูกกลุ่มนิสิตให้วิชา)",
    "locked_room_missing": "ง่าย (แก้ห้องที่ล็อกไว้)", "locked_room_overload": "ง่าย (ยกเลิกการล็อกห้องบางวิชา)",
    "no_room_big_enough": "ยาก (ต้องแบ่ง section หรือหาห้องใหญ่ขึ้น)",
    "room_shortage": "ยาก (ต้องเพิ่มห้อง)", "room_tight": "ยาก (ต้องเพิ่มห้อง)",
    "group_overbooked": "ปานกลาง (ย้าย/ลดวิชาศึกษาทั่วไปที่ล็อกไว้)", "group_tight": "ปานกลาง (ย้าย/ลดวิชาศึกษาทั่วไปที่ล็อกไว้)",
    "group_day_limit": "ปานกลาง (ย้าย/ลดวิชาศึกษาทั่วไปที่ล็อกไว้)",
}


def recommend(tool_context: ToolContext, decision: str, message: str) -> dict:
    """ส่งคำแนะนำให้ผู้ใช้ก่อนจัดตาราง

    decision: "fix_first" = ควรแก้ข้อมูลก่อนกดจัด / "ok_to_continue" = จัดต่อได้เลย แล้วจัดวิชาที่เหลือเองทีหลัง
    message: ข้อความถึงผู้ใช้ 1-2 ประโยค
    """
    if decision not in ("fix_first", "ok_to_continue"):
        return {"accepted": False, "reason": "decision ต้องเป็น fix_first หรือ ok_to_continue"}
    if not (message or "").strip():
        return {"accepted": False, "reason": "message ว่าง"}
    tool_context.state["data_decision"] = decision
    tool_context.state["data_review"] = message.strip()
    tool_context.actions.skip_summarization = True   # ได้คำตอบแล้ว ไม่ต้องให้ LLM พูดต่อ
    return {"accepted": True}


def _data_review_instruction(ctx: ReadonlyContext) -> str:
    # ตัวเลข/ทางแก้ Python คำนวณไว้แล้ว (ผู้ใช้เห็นในการ์ด) — LLM มีหน้าที่ชั่งน้ำหนักแล้วตัดสินใจ
    issues = [{"title": i.get("title") or i.get("detail"), "facts": i.get("facts"),
               "fix": i.get("suggestion"), "fix_effort": _FIX_EFFORT.get(i.get("kind"), "ปานกลาง"),
               "subject_count": len(i.get("subjects") or [])}
              for i in (ctx.state.get("data_issues") or []) if i.get("severity") == "blocking"][:MAX_DATA_ISSUES_FOR_LLM]
    impact = (ctx.state.get("skip_impact") or [])[:30]
    return (
        "คุณคือ DataReviewAgent ที่ปรึกษาของอาจารย์ผู้จัดตารางเรียน ระบบตรวจข้อมูลก่อนจัดตารางแล้วพบปัญหาที่ทำให้บางวิชาจัดไม่ได้แน่ "
        "ถ้าผู้ใช้กด \"จัดต่อเลย\" ระบบจะจัดวิชาอื่นตามปกติ แต่ข้ามวิชาใน \"วิชาที่จะหลุด\" "
        "(ผู้ใช้ลากวางเองทีหลังได้ หลังแก้ข้อมูลแล้ว)\n\n"
        "งานของคุณ: ตัดสินว่าควรแก้ข้อมูลก่อน หรือจัดต่อได้เลย แล้วเรียก tool recommend ครั้งเดียว\n"
        "- \"fix_first\" เมื่อ วิชาบังคับ (elective=false) หลุด หรือหลุดตั้งแต่ 3 วิชา และการแก้ไม่ยาก "
        "(แก้ไม่กี่นาทีแล้วจัดครบ คุ้มกว่าจัดแล้วต้องมาลากวางเอง)\n"
        "- \"ok_to_continue\" เมื่อ หลุดน้อย (1-2 วิชา) และเป็นวิชาเลือก หรือการแก้ยาก (ต้องเพิ่มห้อง/แบ่ง section) "
        "ซึ่งรอไม่ได้ ให้จัดส่วนอื่นไปก่อน\n\n"
        "message: ข้อความถึงอาจารย์ผู้จัดตาราง เขียนเหมือนผู้ช่วยที่สุภาพและเป็นกันเอง พูดภาษาคน กระชับ\n"
        "- 2 ประโยค ไม่เกิน 45 คำ ลงท้ายด้วย \"ค่ะ\"\n"
        "- ประโยคแรก: ผลถ้าจัดตอนนี้ — จำนวนวิชาที่จะจัดไม่ได้ทั้งหมด (นับจาก \"วิชาที่จะหลุด\" ไม่นับวิชาซ้ำ) "
        "ถ้ามีวิชาที่ knock_on=true ให้บอกในประโยคนี้ด้วยว่าวิชาไหนของกลุ่มไหนจะหลุดตามไป เพราะต้องเรียนพร้อมกลุ่มใด "
        "(ใช้รหัสวิชาก็พอ ไม่ต้องใส่ชื่อเต็ม)\n"
        "- ประโยคที่สอง: สิ่งที่แนะนำให้ทำ พร้อมเหตุผลสั้นๆ ที่ฟังแล้วอยากทำตาม "
        "เช่น แก้จุดเดียวจบ / แก้ไม่กี่นาที / วิชาที่หลุดเป็นวิชาเลือก ลากวางเองทีหลังได้ "
        "ถ้ามีหลายปัญหาให้บอกว่าเริ่มจากเรื่องไหน\n"
        "- ตัวอย่างน้ำเสียง (ห้ามลอกเนื้อหา): \"ถ้าจัดตอนนี้จะมี X วิชาที่ยังลงตารางไม่ได้ … "
        "แนะนำให้ … ก่อนนะคะ แก้จุดเดียวก็จัดได้ครบค่ะ\"\n"
        "- เลี่ยงคำแข็งๆ อย่าง \"หลุด\" \"ควรแก้ไขข้อมูลเพราะ\" \"เนื่องจาก\" และไม่ต้องอธิบายตัวเลขคาบหรือวิธีแก้ละเอียด "
        "(การ์ดด้านล่างแสดงอยู่แล้ว)\n"
        "- ห้ามใช้คำอังกฤษหรือชื่อฟิลด์ (fix_first, knock_on, elective ฯลฯ) ไม่ใช้ markdown "
        "ใช้ชื่อและตัวเลขจากข้อมูลเท่านั้น ห้ามแต่งเพิ่ม\n\n"
        f"ปัญหา:\n{json.dumps(issues, ensure_ascii=False)}\n\n"
        f"วิชาที่จะหลุด:\n{json.dumps(impact, ensure_ascii=False)}"
    )


_CHECKER_RULES = {
    "retry": (
        "สถานการณ์: มีวิชาที่จัดไม่ได้หรือชนกัน\n"
        "- verdict \"retry_may_help\" = มีวิชาอื่นขวางอยู่ แก้ได้ (มี options)\n"
        "- verdict \"data_problem\" / \"needs_manual\" = ระบบแก้เองไม่ได้ ไม่ต้องเลือก\n"
        "เรียก tool ครั้งเดียว:\n"
        "- suggest_retry(priority_subject_ids, option_ids, reason) ถ้ามีทางที่น่าลอง "
        "(priority = subject_id ของวิชา retry_may_help และ hard_issues, option เลือกไม่เกิน 3 ตัว "
        "เลือกตัวที่ช่วยได้หลายวิชาก่อน)\n"
        "- exit_loop(reason) ถ้าไม่มีทางไหนคุ้มที่จะลอง\n"
    ),
    "soft": (
        "สถานการณ์: ตารางจัดได้แล้ว แต่ยังมี LAB อยู่ก่อนวัน LECTURE (ไม่ผิดกฎ แต่ไม่ดีต่อการเรียน) "
        "ระบบลองให้แล้วว่าทุกตัวเลือกทำได้จริงโดยไม่ผิดกฎข้ออื่น\n"
        "เรียก tool ครั้งเดียว:\n"
        "- suggest_soft_fixes(option_ids, reason) เลือกไม่เกิน 3 ตัว: แบบ \"ไม่กระทบวิชาอื่น\" คุ้มเสมอ, "
        "แบบสลับเลือกเมื่อลด soft issue ได้มากพอ, ไม่เลือก 2 ตัวที่แก้วิชาเดียวกัน\n"
        "- exit_loop(reason) ถ้าไม่มีตัวไหนคุ้ม\n"
    ),
}


def _checker_instruction(ctx: ReadonlyContext) -> str:
    return (
        "คุณคือ CheckerAgent ผู้ตัดสินใจว่าจะแก้ตารางเรียนตรงไหน Greedy เป็นคนวางตาราง "
        "Python ตรวจกฎและเตรียมตัวเลือกให้แล้ว คุณไม่ต้องตรวจกฎเอง\n\n"
        f"{_CHECKER_RULES[ctx.state.get('checker_mode') or 'retry']}\n"
        "หลังเรียก tool ตอบภาษาไทย 1-2 ประโยคว่าเลือกอะไรเพราะอะไร "
        "ใช้ค่าจากข้อมูลด้านล่างเท่านั้น ห้ามเดา subject_id หรือ option_id เอง\n\n"
        f"ข้อมูล:\n{json.dumps(ctx.state.get('checker_brief') or {}, ensure_ascii=False)}"
    )


class DataGatherAgent(BaseAgent):
    """ดึงข้อมูล + ตรวจความพร้อม (Python) -> ถ้าเจอเรื่องที่จัดไม่ได้แน่ ให้ DataReviewAgent (LLM)
    ประเมินผลกระทบแล้วตัดสินว่า "ควรแก้ข้อมูลก่อน" หรือ "จัดต่อได้เลย"

    ทำงาน 2 จังหวะใน session เดียวกัน:
      1) /check-data  (ตอนกด "สร้างตาราง")  ดึง + ตรวจ + LLM สรุป -> การ์ดในแชท
      2) /generate    (ตอนกด "จัดต่อเลย")   session เดิม -> ใช้ผลจากจังหวะ 1 ต่อ ไม่ดึง/ไม่ตรวจซ้ำ
    """

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = _State(ctx.session.state)
        checked_at = state.get("data_checked_at")
        reuse = bool(checked_at) and time.time() - checked_at < CHECK_REUSE_SECONDS
        info = gather_step(state, reuse_check=reuse)
        if reuse:
            print(f"[data] ใช้ข้อมูลที่ตรวจไว้ตอนกดสร้างตาราง ({time.time() - checked_at:.0f} วินาทีก่อน) "
                  f"/ {info['data_issue_count']} เรื่อง")
            yield _event(self, ctx, state)
            return

        state["data_checked_at"] = time.time()
        print(f"[data] ดึงข้อมูลแล้ว: {info['section_count']} section, {info['room_count']} ห้อง, "
              f"{info['teacher_count']} อาจารย์ / ตรวจเจอ {info['data_issue_count']} เรื่อง "
              f"(จัดไม่ได้แน่ {info['blocking_count']})")
        yield _event(self, ctx, state)   # บันทึกผลตรวจลง state ก่อน — LLM ล่มก็ยังมีผลจาก Python
        if info["blocking_count"]:   # มีเรื่องที่จัดไม่ได้แน่ -> ให้ LLM ประเมินว่าควรแก้ก่อนหรือจัดต่อได้
            async for event in self.sub_agents[0].run_async(ctx):   # DataReviewAgent (LLM)
                yield event
            state = _State(ctx.session.state)
            if not state.get("data_review") and (state.get("data_review_text") or "").strip():
                state["data_review"] = state["data_review_text"].strip()   # LLM ไม่เรียก tool แต่ตอบเป็นข้อความ
                yield _event(self, ctx, state)


class AssignerAgent(BaseAgent):

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = _State(ctx.session.state)
        assign_step(state)
        yield _event(self, ctx, state)


class CheckerAgent(BaseAgent):

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = _State(ctx.session.state)
        mode, brief = prepare_decision(state)

        if mode is not None:
            state["checker_mode"], state["checker_brief"] = mode, brief
            yield _event(self, ctx, state)
            escalated = False
            async for event in self.sub_agents[0].run_async(ctx):   # CheckerDecisionAgent (LLM)
                escalated = escalated or bool(event.actions.escalate)
                yield event
            state = _State(ctx.session.state)
            next_attempt = (state.get("attempt_no") or 0) + 1
            chose = any(e.get("advice_for_attempt") == next_attempt for e in state.get("attempt_log") or [])
            if chose and not escalated:
                return   # มีคำสั่งแล้ว วนกลับไปให้ AssignerAgent ลงมือ

        # จบ: สรุปผล (Python เขียน รวมเหตุผลที่ Agent ตัดสินใจทุกรอบ) แล้วหยุด loop
        state["final_report"] = {**(state.get("final_report") or {}), "attempt_log": state.get("attempt_log", [])}
        yield _event(self, ctx, state, text=build_summary(state), escalate=True)



_llm = dict(after_model_callback=track_usage,
            disallow_transfer_to_parent=True, disallow_transfer_to_peers=True)   # ห้ามโอนงานให้ agent อื่นเอง

checker_decision_agent = Agent(
    model=make_model(), planner=make_planner(), name="CheckerDecisionAgent",
    description="เลือกวิธีแก้ตารางจากตัวเลือกที่ Python เตรียมไว้ แล้วบอกเหตุผล",
    instruction=_checker_instruction, tools=[suggest_retry, suggest_soft_fixes, exit_loop], **_llm,
)

_timer = dict(before_agent_callback=_start_timer, after_agent_callback=_stop_timer)


def _start_check(callback_context: CallbackContext):
    _start_timer(callback_context)
    reset_usage(callback_context)


def _stop_check(callback_context: CallbackContext):
    _stop_timer(callback_context)
    print_summary(callback_context.state)   # ค่า LLM ของรอบตรวจข้อมูล (แสดงใน console)


def make_data_gather_agent(**callbacks) -> DataGatherAgent:
    # ADK ให้ agent หนึ่งตัวอยู่ใต้ parent ได้ตัวเดียว -> สร้าง 2 ชุด (ใน pipeline / ให้ /check-data รันเดี่ยว)
    data_review_agent = Agent(
        model=make_model(), planner=make_planner(), name="DataReviewAgent",
        description="ประเมินผลกระทบของปัญหาข้อมูล แล้วตัดสินว่าควรแก้ข้อมูลก่อนหรือจัดต่อได้เลย",
        instruction=_data_review_instruction, tools=[recommend],
        output_key="data_review_text",   # สำรอง: ถ้า LLM ตอบเป็นข้อความแทนการเรียก tool
        **_llm,
    )
    return DataGatherAgent(
        name="DataGatherAgent", sub_agents=[data_review_agent],
        description="ดึงข้อมูลล่าสุดจาก Supabase แล้วตรวจความพร้อมของข้อมูลก่อนจัดตาราง", **(callbacks or _timer),
    )


data_gather_agent = make_data_gather_agent()   # ขั้นแรกของ SchedulingPipeline
data_check_agent = make_data_gather_agent(     # ตัวที่ /check-data รัน (ตอนกด "สร้างตาราง")
    before_agent_callback=_start_check, after_agent_callback=_stop_check,
)
assigner_agent = AssignerAgent(
    name="AssignerAgent",
    description="รับคำสั่งจาก CheckerAgent แล้วให้ Greedy จัด/แก้ตาราง เก็บรอบที่ดีที่สุดไว้เสมอ", **_timer,
)
checker_agent = CheckerAgent(
    name="CheckerAgent", sub_agents=[checker_decision_agent],
    description="ตรวจผล วิเคราะห์ว่า Greedy พลาดตรงไหน แล้วเลือกวิธีแก้ส่งให้ AssignerAgent", **_timer,
)

quality_loop = LoopAgent(
    name="QualityLoop", sub_agents=[assigner_agent, checker_agent], max_iterations=MAX_ATTEMPTS,
    description="Greedy จัด -> Checker วิเคราะห์ + เลือกวิธีแก้ -> แก้เฉพาะจุด จนไม่มีอะไรให้แก้หรือครบจำนวนรอบ",
)

scheduling_pipeline = SequentialAgent(
    name="SchedulingPipeline", sub_agents=[data_gather_agent, quality_loop],
    description="ตรวจข้อมูล -> ( จัดตาราง -> วิเคราะห์ + เลือกวิธีแก้ -> แก้เฉพาะจุด )",
    before_agent_callback=_start_pipeline, after_agent_callback=_stop_pipeline,
)

scheduling_tool = AgentTool(agent=scheduling_pipeline)