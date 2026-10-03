import time

from google.adk.agents import Agent, SequentialAgent, LoopAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.tool_context import ToolContext

from .models import make_model, make_planner
from .tools.scheduling.load_data import refresh_cache, get_cached_data
from .tools.scheduling.auto_assign import auto_assign_all
from .tools.scheduling.assignment_store import get_current_schedule, move_session
from .tools.scheduling.find_issues import find_issues

# [OpenRouter] ไม่ใช้ GEMINI_MODEL / BuiltInPlanner แล้ว — โมเดลและการปิด reasoning
# ย้ายไปตั้งใน models.py ที่เดียว (BuiltInPlanner ใช้ได้กับ Gemini API ตรงเท่านั้น)

# ลดจาก 3 เหลือ 2 — ถ้ารอบแรกยังมีปัญหาชนกัน ให้ลองสุ่มจัดใหม่ได้อีกแค่ 1 รอบ
MAX_LOOP_ITERATIONS = 2

# จำกัดจำนวนครั้งที่ CheckerAgent เรียก fix_one_session() ได้ต่อ 1 รอบ
MAX_MANUAL_FIX_PER_ROUND = 5


# จับเวลาแต่ละ agent จะได้เห็นใน terminal ว่าตัวไหนช้าจริง
_agent_start_times: dict[str, float] = {}


def _start_timer(callback_context: CallbackContext):
    _agent_start_times[callback_context.agent_name] = time.time()
    return None


def _stop_timer(callback_context: CallbackContext):
    name = callback_context.agent_name
    started = _agent_start_times.pop(name, None)
    if started is not None:
        print(f"[timing] {name}: {time.time() - started:.1f}s")
    return None


def _format_schedule_table() -> str:
    schedule = get_current_schedule()
    data = get_cached_data()
    subjects = {s["subject_id"]: s for s in data["subjects"]}
    timeslots_by_id = {str(t["timeslot_id"]): t for t in data["timeslots"]}
    rooms_by_id = {r["room_id"]: r["room_name"] for r in data["rooms"]}

    lines = []
    for item in schedule:
        subject = subjects.get(item["subject_id"], {})
        name = subject.get("name_english") or subject.get("name_thai") or item["subject_id"]
        section_suffix = f" (section {item['section']})" if item.get("section") else ""

        ts_rows = [timeslots_by_id[str(tid)] for tid in item.get("timeslot_ids", []) if str(tid) in timeslots_by_id]
        ts_rows.sort(key=lambda t: t["start_time"])
        label = (
            f"{ts_rows[0]['day']} {ts_rows[0]['start_time']}-{ts_rows[-1]['end_time']}"
            if ts_rows else "-"
        )

        room_name = rooms_by_id.get(item["room_id"], item["room_id"])
        lines.append(f"- {name} [{item['session_type']}]{section_suffix}: {room_name}, {label}")

    return "\n".join(lines)


# ── 1. DataGatherAgent ──────────────────────────────────────────────────

def gather_context(tool_context: ToolContext) -> dict:
    data = refresh_cache()
    summary = {
        "teacher_count": len(data["teachers"]),
        "room_count": len(data["rooms"]),
        "section_count": len(data["sections"]),
        "existing_locked_count": len(data["existing"]),
        "has_sections": len(data["sections"]) > 0,
    }
    tool_context.state["context_summary"] = summary
    return summary


# ── 2. AssignerAgent ───────────────────────────────────────────────────

def assign_and_fix_schedule(tool_context: ToolContext) -> dict:
    # รีเซ็ตตัวนับทุกครั้งที่เริ่มรอบใหม่ (เดิมนับสะสมทั้ง session
    # ทำให้รอบหลังๆ แก้เฉพาะจุดไม่ได้เลย)
    tool_context.state["manual_fix_call_count"] = 0

    context = tool_context.state.get("context_summary", {})
    if not context.get("has_sections"):
        result = {
            "assigned_count": 0, "failed_count": 0, "failed_sessions": [],
            "remaining_hard_issue_count": 0, "remaining_soft_issue_count": 0,
            "rounds_used": 0, "converged": False, "no_sections": True,
        }
        tool_context.state["schedule_result"] = result
        return result

    started = time.time()
    assign_result = auto_assign_all()
    print(f"[timing] auto_assign_all (Python): {time.time() - started:.1f}s")

    result = {
        "assigned_count": assign_result["assigned_count"],
        "failed_count": assign_result["failed_count"],
        "failed_sessions": assign_result["failed"],
        "remaining_hard_issue_count": assign_result["remaining_hard_issue_count"],
        "remaining_soft_issue_count": assign_result["remaining_soft_issue_count"],
        "rounds_used": assign_result["rounds_used"],
        "converged": assign_result["converged"],
        "no_sections": False,
    }
    tool_context.state["schedule_result"] = result
    return result


# ── 3. CheckerAgent ────────────────────────────────────────────────────

def exit_loop(tool_context: ToolContext) -> dict:
    """เรียก tool นี้เพื่อหยุด loop เมื่อไม่มีปัญหาชนกัน (hard issue) เหลือแล้ว"""
    tool_context.actions.escalate = True
    return {}


def audit_and_report(tool_context: ToolContext) -> dict:
    schedule_result = tool_context.state.get("schedule_result", {})

    if schedule_result.get("no_sections"):
        report = {
            "status": "no_sections",
            "message": "ไม่มีวิชาที่เปิดสอนในระบบเลย ไม่มีอะไรให้จัดตาราง",
        }
        tool_context.state["final_report"] = {**report, "schedule_table": ""}
        return report

    issues = find_issues()
    hard_issues = [i for i in issues if i.get("severity") == "hard"]
    soft_issues = [i for i in issues if i.get("severity") == "soft"]
    verified = len(hard_issues) == 0

    failed_sessions = schedule_result.get("failed_sessions", [])
    fully_complete = verified and len(failed_sessions) == 0

    hard_issues_summary = [
        {
            "type": i.get("type"),
            "fix_session_id": i.get("fix_session_id"),
            "detail": i.get("detail"),
        }
        for i in hard_issues
        if i.get("fix_session_id")
    ]

    report = {
        "status": "ok" if fully_complete else "incomplete",
        "fully_complete": fully_complete,
        "rounds_used": schedule_result.get("rounds_used"),
        "hard_issue_count": len(hard_issues),
        "soft_issue_count": len(soft_issues),
        "hard_issues": hard_issues_summary,
        "failed_sessions": failed_sessions,
    }

    # เก็บตารางไว้ใน state เท่านั้น ไม่ส่งกลับให้ LLM อ่าน
    # (ตารางยาวๆ ทำให้ทุก call หลังจากนี้ช้า) — หน้าเว็บโหลดตารางจาก /schedule เอง
    tool_context.state["final_report"] = {**report, "schedule_table": _format_schedule_table()}
    return report


def fix_one_session(tool_context: ToolContext, session_id: str) -> dict:
    """ย้าย session ที่ระบุไปหาช่วงเวลา/ห้องใหม่ที่ไม่ผิดกฎ (ใช้แก้ hard issue เฉพาะจุด)

    ใช้ session_id จาก hard_issues[i]["fix_session_id"] ของ audit_and_report() เท่านั้น
    ห้ามเดา session_id เอง

    Args:
        session_id: รหัส session ที่ต้องการย้าย

    Returns:
        {"success": True, ...} ถ้าย้ายสำเร็จ
        {"success": False, "reason": "..."} ถ้าย้ายไม่ได้
    """
    call_count = tool_context.state.get("manual_fix_call_count", 0)
    if call_count >= MAX_MANUAL_FIX_PER_ROUND:
        return {
            "success": False,
            "reason": (
                f"เรียกแก้ไขเฉพาะจุดครบ {MAX_MANUAL_FIX_PER_ROUND} ครั้งในรอบนี้แล้ว "
                "ไม่ลองแก้เพิ่ม ให้สรุปสถานะปัจจุบันแทน"
            ),
        }
    tool_context.state["manual_fix_call_count"] = call_count + 1
    return move_session(session_id)


# ── Agents ────────────────────────────────────────────────────────────────

data_gather_agent = Agent(
    model=make_model(),
    planner=make_planner(),
    name="DataGatherAgent",
    description="ดึงข้อมูลล่าสุดจาก Supabase ก่อนเริ่มจัดตาราง",
    instruction="เรียก gather_context() แล้วสรุปสั้นๆ 1 บรรทัดว่ามีข้อมูลกี่รายการ",
    tools=[gather_context],
    before_agent_callback=_start_timer,
    after_agent_callback=_stop_timer,
)

assigner_agent = Agent(
    model=make_model(),
    planner=make_planner(),
    name="AssignerAgent",
    description="สั่งจัดตารางเรียนใหม่ทั้งหมด — tool ข้างในจัด + แก้ปัญหาชนกันในตัวเอง",
    instruction="เรียก assign_and_fix_schedule() แล้วสรุปสั้นๆ 1 บรรทัดว่าจัดได้กี่รายการ เหลือปัญหากี่ตัว",
    tools=[assign_and_fix_schedule],
    before_agent_callback=_start_timer,
    after_agent_callback=_stop_timer,
)

# ออกจาก loop ได้เมื่อไม่มี hard issue
# (failed_sessions คือวิชาที่จัดไม่ได้จริง จัดใหม่ก็มักไม่ช่วย ไม่ต้องวนซ้ำ)
# และให้เรียก fix_one_session ทุกตัวพร้อมกันใน turn เดียว
checker_agent = Agent(
    model=make_model(),
    planner=make_planner(),
    name="CheckerAgent",
    description="ตรวจสอบผลลัพธ์ แก้ปัญหาชนกันเฉพาะจุด แล้วตัดสินใจว่าจะจบ loop หรือจัดใหม่",
    instruction="""
        เรียก audit_and_report() ก่อนเสมอ แล้วทำตามนี้:

        กรณี A — status เป็น "no_sections" หรือ hard_issues ว่างเปล่า:
            เรียก exit_loop() ทันที

        กรณี B — hard_issues ไม่ว่าง:
            1. เรียก fix_one_session(session_id) ให้ครบทุกตัวพร้อมกันใน turn เดียว
               โดยใช้ hard_issues[i]["fix_session_id"] เท่านั้น ห้ามเดา session_id
               และห้ามใช้ค่าจาก failed_sessions
            2. เรียก audit_and_report() อีกครั้ง
            3. ถ้า hard_issues ว่างแล้ว: เรียก exit_loop()
               ถ้ายังไม่ว่าง: ห้ามเรียก exit_loop() (ระบบจะจัดใหม่อีกรอบเอง)

        จากนั้นสรุปสั้นๆ ไม่เกิน 3 บรรทัด: จัดสำเร็จหรือไม่ เหลือปัญหาชนกันกี่จุด
        และถ้ามี failed_sessions ให้บอกว่าวิชาไหนจัดไม่ได้พร้อมเหตุผลสั้นๆ
        ห้ามพิมพ์ตารางทั้งหมดออกมา
        """,
    tools=[audit_and_report, fix_one_session, exit_loop],
    before_agent_callback=_start_timer,
    after_agent_callback=_stop_timer,
)

quality_loop = LoopAgent(
    name="QualityLoop",
    sub_agents=[assigner_agent, checker_agent],
    max_iterations=MAX_LOOP_ITERATIONS,
    description="จัดตาราง(+แก้ปัญหาในตัว) -> ตรวจสอบ+แก้เฉพาะจุด วนจนไม่มีปัญหาชนกันหรือครบจำนวนรอบ",
)

scheduling_pipeline = SequentialAgent(
    name="SchedulingPipeline",
    sub_agents=[data_gather_agent, quality_loop],
    description="ดึงข้อมูล -> ( จัดตาราง -> ตรวจสอบ -> แก้เฉพาะจุด )",
    before_agent_callback=_start_timer,
    after_agent_callback=_stop_timer,
)

scheduling_tool = AgentTool(agent=scheduling_pipeline)