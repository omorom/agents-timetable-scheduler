"""
scheduling_agent.py — pipeline จัดตาราง (Google ADK multi-agent)

    SchedulingPipeline (SequentialAgent)
     ├─ DataGatherAgent  "ตรวจก่อนจัด"     Python ดึงข้อมูลจาก Supabase + ตรวจข้อมูล
     │                                   -> (ถ้าเจอปัญหา) LLM แยกความร้ายแรง + สรุปทางแก้
     └─ QualityLoop (LoopAgent สูงสุด MAX_ATTEMPTS รอบ)
          ├─ AssignerAgent "รับคำสั่ง+ลงมือ"  ให้ Greedy จัด/แก้ตามที่ CheckerAgent เลือก
          └─ CheckerAgent  "ตรวจหลังจัด"     Python ตรวจกฎ + เตรียมตัวเลือก
                                          -> (ถ้ามีเรื่องให้เลือก) LLM เลือก + บอกเหตุผล

หลักการ: งานที่ต้องแม่นยำให้ Python ทำ (อยู่ใน tools/scheduling/pipeline_steps.py)
         ใช้ LLM เฉพาะตอนที่มีเรื่องต้องตัดสินใจ ไม่มีก็ไม่เรียก (ไม่เสีย token)
"""

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

MAX_OPTIONS_PER_ATTEMPT = 3   # แก้ทีละน้อย ไม่เปลี่ยนตารางเยอะจนคุมไม่ได้


# ───────────── จับเวลา / ค่าใช้จ่าย ─────────────

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


# ───────────── ตัวช่วยสำหรับ Custom Agent ─────────────

class _State:
    """อ่าน state ล่าสุด / เขียนเก็บไว้ใน delta แล้วส่งออกไปกับ Event
    (ADK บันทึก state ผ่าน Event เท่านั้น ถ้าเขียน session.state ตรงๆ generate_service.py จะไม่เห็นค่า)
    """

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


# ───────────── Tools ของ CheckerAgent (LLM เรียกเพื่อบอกการตัดสินใจ) ─────────────

def _log(tool_context: ToolContext, entry: dict) -> None:
    tool_context.state["attempt_log"] = list(tool_context.state.get("attempt_log") or []) + [entry]


def suggest_retry(tool_context: ToolContext, priority_subject_ids: list[str],
                  option_ids: list[str], reason: str) -> dict:
    """เลือกวิธีแก้วิชาที่จัดไม่ได้ ระบบจะแก้เฉพาะวิชาเหล่านั้นในรอบถัดไป (ไม่จัดทั้งตารางใหม่)

    Args:
        priority_subject_ids: subject_id ของวิชาที่อยากให้ลองวางก่อน (ใช้ค่าจากข้อมูลที่ให้เท่านั้น)
        option_ids: option_id ที่เลือก (ไม่เกิน 3 ตัว) แต่ละตัว = ให้วิชาที่ขวางหลบคาบหนึ่ง ไม่มีใส่ []
        reason: เหตุผลสั้นๆ 1 ประโยค (แสดงให้ผู้ใช้เห็น)
    """
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
    """เลือกทางแก้ LAB ที่อยู่ก่อนวัน LECTURE ระบบแก้ในรอบถัดไปทีละจุด (แก้แล้วไม่ดีขึ้นจะคืนกลับเอง)

    Args:
        option_ids: option_id ที่เลือก (ไม่เกิน 3 ตัว)
        reason: เหตุผลสั้นๆ 1 ประโยค (แสดงให้ผู้ใช้เห็น)
    """
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
    """หยุดแก้ตาราง ใช้เมื่อไม่มีตัวเลือกไหนคุ้มที่จะแก้

    Args:
        reason: เหตุผลสั้นๆ 1 ประโยค ว่าทำไมไม่แก้ (แสดงให้ผู้ใช้เห็น)
    """
    _log(tool_context, {"declined_after_attempt": tool_context.state.get("attempt_no") or 0,
                        "reason": reason or "ไม่มีตัวเลือกที่คุ้มจะแก้"})
    tool_context.actions.escalate = True
    return {"stopped": True}


# ───────────── Instruction ของ LLM (สร้างใหม่ทุกครั้งจาก state) ─────────────

def _data_review_instruction(ctx: ReadonlyContext) -> str:
    issues = (ctx.state.get("data_issues") or [])[:MAX_DATA_ISSUES_FOR_LLM]
    return (
        "คุณคือผู้ตรวจความพร้อมของข้อมูลก่อนจัดตารางเรียน ระบบตรวจข้อมูลจากฐานข้อมูลแล้วเจอรายการด้านล่าง\n"
        "1. แยกว่าเรื่องไหน \"จัดไม่ได้แน่\" (เช่น ไม่มีห้องจุพอ ไม่มีอาจารย์ อาจารย์ว่างไม่พอสอน) "
        "เรื่องไหน \"ควรระวัง\" (เช่น อาจารย์ว่างเหลือน้อย)\n"
        "2. ถ้าหลายเรื่องมีสาเหตุเดียวกัน (อาจารย์/วิชาเดียวกัน) ให้รวมเป็นเรื่องเดียว\n"
        "3. แนะนำทางแก้เรื่องละ 1 ประโยค (เช่น แบ่ง section, เพิ่มห้อง, ผูกอาจารย์, แก้เวลาว่าง)\n"
        "ตอบภาษาไทย ไม่เกิน 6 บรรทัด ขึ้นต้นด้วย \"จัดไม่ได้แน่:\" และ/หรือ \"ควรระวัง:\" "
        "ใช้เฉพาะข้อมูลด้านล่าง ห้ามแต่งเพิ่ม ห้ามแสดงรหัส D1/D2\n\n"
        f"รายการ:\n{json.dumps(issues, ensure_ascii=False)}"
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


# ───────────── Agents ─────────────

class DataGatherAgent(BaseAgent):
    """ตรวจก่อนจัด: Python ดึงข้อมูล + ตรวจ -> (ถ้าเจอปัญหา) LLM จัดลำดับความร้ายแรง + สรุป"""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = _State(ctx.session.state)
        info = gather_step(state)
        print(f"[data] ดึงข้อมูลแล้ว: {info['section_count']} section, {info['room_count']} ห้อง, "
              f"{info['teacher_count']} อาจารย์ / ตรวจเจอ {info['data_issue_count']} เรื่อง")
        yield _event(self, ctx, state)
        if info["data_issue_count"]:
            async for event in self.sub_agents[0].run_async(ctx):   # DataReviewAgent (LLM)
                yield event


class AssignerAgent(BaseAgent):
    """รับคำสั่งจาก CheckerAgent ผ่าน state แล้วให้ Greedy ลงมือ (ทำงานทุกรอบแน่นอน)"""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = _State(ctx.session.state)
        assign_step(state)
        yield _event(self, ctx, state)


class CheckerAgent(BaseAgent):
    """ตรวจหลังจัด: Python เตรียมตัวเลือก -> LLM เลือก -> คำสั่งไปถึง AssignerAgent ผ่าน state
    หยุด loop เมื่อ: ไม่มีอะไรให้ตัดสินใจ / LLM ไม่เลือกอะไร / ครบจำนวนรอบ
    """

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

data_review_agent = Agent(
    model=make_model(), planner=make_planner(), name="DataReviewAgent",
    description="อ่านผลตรวจข้อมูล แยกความร้ายแรง และสรุปทางแก้",
    instruction=_data_review_instruction, output_key="data_review", **_llm,
)

checker_decision_agent = Agent(
    model=make_model(), planner=make_planner(), name="CheckerDecisionAgent",
    description="เลือกวิธีแก้ตารางจากตัวเลือกที่ Python เตรียมไว้ แล้วบอกเหตุผล",
    instruction=_checker_instruction, tools=[suggest_retry, suggest_soft_fixes, exit_loop], **_llm,
)

_timer = dict(before_agent_callback=_start_timer, after_agent_callback=_stop_timer)

data_gather_agent = DataGatherAgent(
    name="DataGatherAgent", sub_agents=[data_review_agent],
    description="ดึงข้อมูลล่าสุดจาก Supabase แล้วตรวจความพร้อมของข้อมูลก่อนจัดตาราง", **_timer,
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