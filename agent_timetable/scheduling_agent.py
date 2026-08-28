from google.adk.agents import Agent, SequentialAgent, LoopAgent
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.tool_context import ToolContext

from .tools.scheduling.load_data import refresh_cache, get_cached_data
from .tools.scheduling.auto_assign import auto_assign_all
from .tools.scheduling.assignment_store import get_current_schedule, move_session
from .tools.scheduling.find_issues import find_issues

GEMINI_MODEL = "gemini-2.5-flash"
MAX_FIX_ROUNDS = 3
MAX_LOOP_ITERATIONS = 3


def _split_issues(issues: list[dict]) -> dict:
    hard = [i for i in issues if i.get("severity") == "hard"]
    soft = [i for i in issues if i.get("severity") == "soft"]
    return {
        "issue_count": len(hard),
        "hard_issues": hard,
        "soft_issue_count": len(soft),
        "soft_issues": soft,
    }


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


def _fix_all_sessions(hard_issues: list[dict]) -> dict:
    fixed, failed, seen = [], [], set()
    for issue in hard_issues:
        session_id = issue.get("fix_session_id")
        if not session_id or session_id in seen:
            continue
        seen.add(session_id)
        result = move_session(session_id)
        if result.get("success"):
            fixed.append(session_id)
        else:
            failed.append({"session_id": session_id, "reason": result.get("reason")})
    return {"fixed_session_ids": fixed, "failed": failed}


def gather_context(tool_context: ToolContext) -> dict:
    # ดึงข้อมูลล่าสุดจาก Supabase แล้วสรุปสั้นๆ ว่ามีข้อมูลกี่รายการที่ต้องใช้จัดตาราง
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


# ── 2. AssignerAgent (ใน loop) ────────────────────────────────────────────

def assign_and_fix_schedule(tool_context: ToolContext) -> dict:
    ## จัดตารางเรียนใหม่ทั้งหมด + แก้ไขปัญหา "ชนกัน" (hard issues) ข้างในตัวเอง
    context = tool_context.state.get("context_summary", {})
    if not context.get("has_sections"):
        result = {
            "assigned_count": 0, "failed_count": 0, "failed_sessions": [],
            "issue_count": 0, "soft_issue_count": 0,
            "rounds_used": 0, "converged": False, "no_sections": True,
        }
        tool_context.state["schedule_result"] = result
        return result

    assign_result = auto_assign_all()
    issues = _split_issues(find_issues())

    rounds_used = 1
    while issues["issue_count"] > 0 and rounds_used < MAX_FIX_ROUNDS:
        _fix_all_sessions(issues["hard_issues"])
        issues = _split_issues(find_issues())
        rounds_used += 1

    result = {
        "assigned_count": assign_result["assigned_count"],
        "failed_count": assign_result["failed_count"],
        "failed_sessions": assign_result["failed"],
        "issue_count": issues["issue_count"],
        "soft_issue_count": issues["soft_issue_count"],
        "rounds_used": rounds_used,
        "converged": issues["issue_count"] == 0,
        "no_sections": False,
    }
    tool_context.state["schedule_result"] = result
    return result


# ── 3. CheckerAgent (ใน loop — ตัดสินใจ exit_loop หรือวนต่อ) ──────────────

def audit_and_report(tool_context: ToolContext) -> dict:
    # ตรวจสอบผลลัพธ์จริงอีกครั้ง + สรุปสั้นๆ ว่าจัดได้กี่รายการ เหลือปัญหา/วิชาที่จัดไม่ได้กี่ตัว
    schedule_result = tool_context.state.get("schedule_result", {})

    if schedule_result.get("no_sections"):
        report = {
            "status": "no_sections",
            "message": "ไม่มีวิชาที่เปิดสอนในระบบเลย ไม่มีอะไรให้จัดตาราง",
            "schedule_table": "",
        }
        tool_context.state["final_report"] = report
        return report

    issues = _split_issues(find_issues())
    verified = issues["issue_count"] == 0

    failed_sessions = schedule_result.get("failed_sessions", [])
    fully_complete = verified and len(failed_sessions) == 0

    report = {
        "status": "ok" if fully_complete else "incomplete",
        "fully_complete": fully_complete,
        "issue_count": issues["issue_count"],
        "soft_issue_count": issues["soft_issue_count"],
        "failed_sessions": failed_sessions,
        "schedule_table": _format_schedule_table(),
    }
    tool_context.state["final_report"] = report
    return report


def exit_loop(tool_context: ToolContext) -> dict:
    """เรียก tool นี้เมื่อจัดตารางสำเร็จครบถ้วนแล้ว (fully_complete == True) เพื่อหยุด loop"""
    tool_context.actions.escalate = True
    return {}


# ── Agents ────────────────────────────────────────────────────────────────

data_gather_agent = Agent(
    model=GEMINI_MODEL,
    name="DataGatherAgent",
    description="ดึงข้อมูลล่าสุดจาก Supabase ก่อนเริ่มจัดตาราง",
    instruction="เรียก gather_context() แล้วสรุปสั้นๆ ว่ามีข้อมูลกี่รายการที่ต้องใช้จัดตาราง",
    tools=[gather_context],
)

assigner_agent = Agent(
    model=GEMINI_MODEL,
    name="AssignerAgent",
    description="สั่งจัดตารางเรียนใหม่ทั้งหมด — tool ข้างในแก้ปัญหา 'ชนกัน' เองจนจบในตัว",
    instruction="เรียก assign_and_fix_schedule() แล้วสรุปสั้นๆ ว่าจัดได้กี่รายการ เหลือปัญหา/วิชาที่จัดไม่ได้กี่ตัว",
    tools=[assign_and_fix_schedule],
)

checker_agent = Agent(
    model=GEMINI_MODEL,
    name="CheckerAgent",
    description="ตรวจสอบผลลัพธ์แบบอิสระ ตัดสินใจว่าควรจบ loop หรือให้ AssignerAgent จัดใหม่อีกรอบ",
    instruction="""
        เรียก audit_and_report() เพื่อตรวจสอบผลลัพธ์จริงอีกครั้ง

        ถ้า status เป็น "no_sections": เรียก exit_loop() ทันที (ไม่มีอะไรให้จัด ไม่ต้องวนต่อ)
        ถ้า fully_complete เป็น True: เรียก exit_loop() ทันที (จัดสำเร็จครบถ้วนแล้ว)
        ถ้า fully_complete เป็น False: ห้ามเรียก exit_loop() ปล่อยให้วนรอบใหม่
        (AssignerAgent จะจัดใหม่ทั้งหมดด้วยลำดับสุ่มที่ต่างออกไป อาจสำเร็จมากขึ้น)

        สรุปสั้นๆ ในทุกกรณีว่าสถานะตอนนี้เป็นอย่างไร ถ้ามี failed_sessions ให้บอกว่า
        วิชา/session ไหนบ้างที่จัดไม่ได้ (session_id + เหตุผล) แยกจากปัญหา "ชนกัน" ให้ชัดเจน
        """,
    tools=[audit_and_report, exit_loop],
)

# LoopAgent ชั้นใน: วนแค่ AssignerAgent + CheckerAgent (ไม่รวม DataGatherAgent
# เพราะข้อมูลไม่ได้เปลี่ยนระหว่างรอบ ไม่ต้องดึงซ้ำ ประหยัด LLM call)
quality_loop = LoopAgent(
    name="QualityLoop",
    sub_agents=[assigner_agent, checker_agent],
    max_iterations=MAX_LOOP_ITERATIONS,
    description="จัดตาราง -> ตรวจสอบ วนจนกว่าจะสำเร็จครบถ้วนหรือครบจำนวนรอบ",
)

# SequentialAgent ชั้นนอก: ดึงข้อมูลครั้งเดียว แล้วค่อยเข้า loop
scheduling_pipeline = SequentialAgent(
    name="SchedulingPipeline",
    sub_agents=[data_gather_agent, quality_loop],
    description="ดึงข้อมูล (ครั้งเดียว) -> จัดตาราง+ตรวจสอบ (วนซ้ำได้จริง)",
)

scheduling_tool = AgentTool(agent=scheduling_pipeline)