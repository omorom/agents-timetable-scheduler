"""
scheduling_agent.py — ประกอบ agent ของระบบจัดตารางเป็น pipeline

  SchedulingPipeline (SequentialAgent)
    1) DataGatherAgent     ดึงข้อมูล + ตรวจสอบข้อมูลก่อนจัดตาราง (Python)
         └ DataReviewAgent (LLM) แนะนำแนวทางแก้ไข — เรียกเฉพาะเมื่อเจอปัญหา
    2) QualityLoop (LoopAgent, สูงสุด MAX_ATTEMPTS รอบ)
         ├ AssignerAgent   Greedy จัด / แก้เฉพาะจุด (Python)
         └ CheckerAgent    ตรวจตาราง (Python)
              └ CheckerDecisionAgent (LLM) เลือกวิธีแก้ — เรียกเฉพาะเมื่อมีปัญหาที่แก้ได้

ไฟล์ที่เกี่ยวข้อง:
  prompts.py      ข้อความสั่งงานของ AI
  agent_tools.py  tool ที่ AI เรียก + ทางสำรองเมื่อ AI ตอบไม่ตรงรูปแบบ
  tools/scheduling/pipeline_steps.py  งาน Python ของแต่ละขั้น
"""

import time
from typing import AsyncGenerator

from google.adk.agents import Agent, BaseAgent, SequentialAgent, LoopAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.tools.agent_tool import AgentTool
from google.genai import types

from .models import make_model, make_planner
from .cost_tracker import track_usage, reset_usage, usage_summary, print_summary
from .prompts import data_review_instruction, checker_instruction
from .agent_tools import (
    suggest_retry, suggest_soft_fixes, exit_loop, recommend,
    build_option_map, fallback_options, fallback_decision,
)
from .tools.scheduling.pipeline_steps import (
    MAX_ATTEMPTS, gather_step, assign_step, prepare_decision, build_summary,
)

CHECK_REUSE_SECONDS = 600   # ผลตรวจจาก /check-data ใช้ต่อได้ภายใน 10 นาที เกินนั้นดึง + ตรวจใหม่ (กันข้อมูลเก่า)


# ───────────── timer / ค่าใช้จ่าย ─────────────

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


def _start_check(callback_context: CallbackContext):
    _start_timer(callback_context)
    reset_usage(callback_context)


def _stop_check(callback_context: CallbackContext):
    _stop_timer(callback_context)
    print_summary(callback_context.state)   # ค่า LLM ของรอบตรวจข้อมูล (แสดงใน console)


# ───────────── state helper ─────────────

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


# ───────────── agents ─────────────

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
        state["data_options"] = []   # ล้างทางเลือกของรอบก่อน
        state["data_option_map"] = build_option_map(state.get("data_issues")) if info["blocking_count"] else {}
        print(f"[data] ดึงข้อมูลแล้ว: {info['section_count']} section, {info['room_count']} ห้อง, "
              f"{info['teacher_count']} อาจารย์ / ตรวจเจอ {info['data_issue_count']} เรื่อง "
              f"(จัดไม่ได้แน่ {info['blocking_count']})")
        yield _event(self, ctx, state)   # บันทึกผลตรวจลง state ก่อน — LLM ล่มก็ยังมีผลจาก Python
        if not info["blocking_count"]:
            return

        # มีเรื่องที่จัดไม่ได้แน่ -> ให้ LLM ประเมินว่าควรแก้ก่อนหรือจัดต่อได้
        async for event in self.sub_agents[0].run_async(ctx):   # DataReviewAgent (LLM)
            yield event
        state = _State(ctx.session.state)

        if not state.get("data_review") and (state.get("data_review_text") or "").strip():
            # LLM ไม่เรียก tool แต่ตอบเป็นข้อความ -> ใช้ข้อความนั้น + ตัดสินแทนด้วยกฎเดียวกับ prompt
            state["data_review"] = state["data_review_text"].strip()
            if not state.get("data_decision"):
                state["data_decision"] = fallback_decision(state.get("skip_impact"))
                print(f"[data] DataReviewAgent ไม่เรียก tool -> ใช้คำตัดสินสำรอง: {state['data_decision']}")
            yield _event(self, ctx, state)

        # LLM ไม่ได้ส่งทางเลือกมา -> ใช้ทางแก้จาก Python แทน การ์ดจะได้มีทางเลือกเสมอ
        if state.get("data_decision") and not state.get("data_options"):
            state["data_options"] = fallback_options(state.get("data_option_map") or {},
                                                     state.get("data_decision"))
            print("[data] ทางเลือก: ใช้ชุดสำรองจาก Python (AI ไม่ได้ส่งมา)")
            yield _event(self, ctx, state)
        elif state.get("data_options"):
            print(f"[data] ทางเลือก: AI เลือก {[o['id'] for o in state['data_options']]}")


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


# ───────────── ประกอบ pipeline ─────────────

_llm = dict(after_model_callback=track_usage,
            disallow_transfer_to_parent=True, disallow_transfer_to_peers=True)   # ห้ามโอนงานให้ agent อื่นเอง
_timer = dict(before_agent_callback=_start_timer, after_agent_callback=_stop_timer)

checker_decision_agent = Agent(
    model=make_model(), planner=make_planner(), name="CheckerDecisionAgent",
    description="เลือกวิธีแก้ตารางจากตัวเลือกที่ Python เตรียมไว้ แล้วบอกเหตุผล",
    instruction=checker_instruction, tools=[suggest_retry, suggest_soft_fixes, exit_loop], **_llm,
)


def make_data_gather_agent(**callbacks) -> DataGatherAgent:
    # ADK ให้ agent หนึ่งตัวอยู่ใต้ parent ได้ตัวเดียว -> สร้าง 2 ชุด (ใน pipeline / ให้ /check-data รันเดี่ยว)
    data_review_agent = Agent(
        model=make_model(), planner=make_planner(), name="DataReviewAgent",
        description="ประเมินผลกระทบของปัญหาข้อมูล แล้วตัดสินว่าควรแก้ข้อมูลก่อนหรือจัดต่อได้เลย",
        instruction=data_review_instruction, tools=[recommend],
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