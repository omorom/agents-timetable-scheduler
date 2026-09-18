from google.adk.agents import Agent, SequentialAgent, LoopAgent
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.tool_context import ToolContext

from .tools.scheduling.load_data import refresh_cache, get_cached_data
from .tools.scheduling.auto_assign import auto_assign_all
from .tools.scheduling.assignment_store import get_current_schedule, move_session
from .tools.scheduling.find_issues import find_issues

GEMINI_MODEL = "gemini-2.5-flash"
# safety-net รอบนอก — ปกติควรจบตั้งแต่ iteration แรกอยู่แล้ว เพราะ
# auto_assign_all() วน fix 3 รอบในตัวเองก่อนคืนผลลัพธ์แล้ว (ดู auto_assign.py)
# ตัวนี้ไว้เผื่อกรณี fix 3 รอบข้างในยังไม่พอจริงๆ ให้ reset แล้วจัดใหม่ทั้งชุด
# ด้วยลำดับสุ่มต่างจากเดิม (auto_assign_all มี randomization ในการเลือก candidate)
MAX_LOOP_ITERATIONS = 3

# จำกัดจำนวนครั้งที่ CheckerAgent เรียก move_session() ได้ต่อ 1 รอบตรวจสอบ
# กันไว้ไม่ให้ LLM เรียกวนไม่รู้จบถ้าดื้อ หรือถ้ามี hard_issues เยอะผิดปกติ
# (ปกติควรมีแค่ 0-3 ตัวต่อรอบ เพราะ auto_assign_all() แก้ไปเกือบหมดแล้ว)
MAX_MANUAL_FIX_PER_ROUND = 5


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


# ── 2. AssignerAgent ───────────────────────────────────────────────────
# หมายเหตุ: auto_assign_all() ตอนนี้จัด + วน fix hard issues สูงสุด 3 รอบ
# "ในตัวเองแล้ว" (Python ล้วน ดู auto_assign.py) เรียกครั้งเดียวจบ ไม่ต้องมี
# LoopAgent ครอบข้างนอกอีกชั้น ประหยัด Gemini quota ไปมาก (จากเดิมวนได้
# สูงสุด 3 รอบ x เรียก LLM หลายครั้งต่อรอบ เหลือแค่เรียก LLM 1 ครั้งตรงนี้)

def assign_and_fix_schedule(tool_context: ToolContext) -> dict:
    ## จัดตารางเรียนใหม่ทั้งหมด — auto_assign_all() แก้ปัญหา "ชนกัน" (hard issues)
    ## จนจบในตัวเองแล้ว (วนสูงสุด 3 รอบ) ไม่ต้องมี loop ครอบข้างนอกอีก
    context = tool_context.state.get("context_summary", {})
    if not context.get("has_sections"):
        result = {
            "assigned_count": 0, "failed_count": 0, "failed_sessions": [],
            "remaining_hard_issue_count": 0, "remaining_soft_issue_count": 0,
            "rounds_used": 0, "converged": False, "no_sections": True,
        }
        tool_context.state["schedule_result"] = result
        return result

    assign_result = auto_assign_all()

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


# ── 3. CheckerAgent (ใน loop — ตัดสินใจ exit_loop / fix เฉพาะจุด / วนต่อ) ──

def exit_loop(tool_context: ToolContext) -> dict:
    """เรียก tool นี้เมื่อจัดตารางสำเร็จครบถ้วนแล้ว (fully_complete == True) เพื่อหยุด loop"""
    tool_context.actions.escalate = True
    return {}


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

    issues = find_issues()
    hard_issues = [i for i in issues if i.get("severity") == "hard"]
    soft_issues = [i for i in issues if i.get("severity") == "soft"]
    verified = len(hard_issues) == 0

    failed_sessions = schedule_result.get("failed_sessions", [])
    fully_complete = verified and len(failed_sessions) == 0

    # แก้ไข (สำคัญ): เดิมส่งกลับแค่ hard_issue_count (ตัวเลขนับจำนวนเฉยๆ) ทำให้
    # CheckerAgent ไม่มีทางรู้เลยว่า session ไหนคือต้นเหตุ ต่อให้มี tool move_session
    # อยู่ในมือก็เรียกไม่ถูก เพราะไม่มี session_id ให้หยิบใช้
    # ตอนนี้ส่ง hard_issues เต็มๆ กลับไปด้วย (แต่ละอันมี fix_session_id ติดมาอยู่แล้ว
    # จาก find_issues() — ดู find_issues.py) พร้อม detail สั้นๆ ให้ CheckerAgent อ่าน
    # แล้วตัดสินใจว่าจะเรียก move_session(fix_session_id) ตัวไหนบ้าง
    hard_issues_summary = [
        {
            "type": i.get("type"),
            "fix_session_id": i.get("fix_session_id"),
            "detail": i.get("detail"),
        }
        for i in hard_issues
        if i.get("fix_session_id")  # กันเผื่อ fix_session_id เป็น None (หา session ต้นเหตุไม่ได้จริงๆ)
    ]

    report = {
        "status": "ok" if fully_complete else "incomplete",
        "fully_complete": fully_complete,
        "rounds_used": schedule_result.get("rounds_used"),
        "hard_issue_count": len(hard_issues),
        "soft_issue_count": len(soft_issues),
        "hard_issues": hard_issues_summary,   # ← ใหม่: รายละเอียดพร้อม session_id ที่ใช้ move_session() ได้จริง
        "failed_sessions": failed_sessions,
        "schedule_table": _format_schedule_table(),
    }
    tool_context.state["final_report"] = report
    return report


def fix_one_session(tool_context: ToolContext, session_id: str) -> dict:
    """ย้าย session ที่ระบุไปหาช่วงเวลา/ห้องใหม่ที่ไม่ผิดกฎ (ใช้แก้ hard issue เฉพาะจุด)

    ใช้เมื่อ audit_and_report() รายงานว่ามี hard_issues เหลืออยู่ ให้ดึง fix_session_id
    จากแต่ละ issue มาเรียก tool นี้ทีละตัว ห้ามเดา session_id เอง ต้องใช้ค่าที่ได้จาก
    hard_issues ของ audit_and_report() เท่านั้น

    Args:
        session_id: รหัส session ที่ต้องการย้าย (มาจาก hard_issues[i]["fix_session_id"])

    Returns:
        {"success": True, ...} ถ้าย้ายสำเร็จ
        {"success": False, "reason": "..."} ถ้าย้ายไม่ได้ (ไม่มีที่ว่างเหมาะสมเหลือ)
    """
    # นับจำนวนครั้งที่เรียก tool นี้ไปแล้วใน state กันไม่ให้ LLM เรียกวนไม่จำกัด
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

    result = move_session(session_id)
    return result


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
    description="สั่งจัดตารางเรียนใหม่ทั้งหมด — tool ข้างในจัด + แก้ปัญหา 'ชนกัน' จนจบในตัวเอง (ไม่ต้องวนซ้ำจาก LLM)",
    instruction="เรียก assign_and_fix_schedule() แล้วสรุปสั้นๆ ว่าจัดได้กี่รายการ ใช้กี่รอบในการแก้ปัญหา เหลือปัญหา/วิชาที่จัดไม่ได้กี่ตัว",
    tools=[assign_and_fix_schedule],
)

checker_agent = Agent(
    model=GEMINI_MODEL,
    name="CheckerAgent",
    description=(
        "ตรวจสอบผลลัพธ์แบบอิสระ ลองแก้ hard issue ที่เหลือเฉพาะจุดก่อน "
        "แล้วค่อยตัดสินใจว่าควรจบ loop หรือให้ AssignerAgent จัดใหม่ทั้งหมด"
    ),
    instruction="""
        เรียก audit_and_report() เพื่อตรวจสอบผลลัพธ์จริงอีกครั้งก่อนเสมอ

        ถ้า status เป็น "no_sections": เรียก exit_loop() ทันที (ไม่มีอะไรให้จัด ไม่ต้องวนต่อ)

        ถ้า fully_complete เป็น True: เรียก exit_loop() ทันที (จัดสำเร็จครบถ้วนแล้ว)

        ถ้า fully_complete เป็น False แต่มี hard_issues เหลืออยู่ (list ไม่ว่าง):
            1. ไล่เรียก fix_one_session(session_id) ทีละตัว โดยใช้ session_id จาก
               hard_issues[i]["fix_session_id"] เท่านั้น — ห้ามเดา session_id เอง
               และห้ามหยิบจาก failed_sessions มาใช้ (คนละความหมายกัน)
            2. หลังแก้ครบทุก issue ในรายการแล้ว ให้เรียก audit_and_report() ใหม่อีกครั้ง
               เพื่อตรวจสอบว่าตอนนี้สมบูรณ์แล้วหรือยัง
            3. ถ้า fully_complete เป็น True แล้ว: เรียก exit_loop() ทันที
            4. ถ้ายังเป็น False อยู่ (แก้เฉพาะจุดไม่พอ): ห้ามเรียก exit_loop()
               ปล่อยให้ปล่อยให้วนรอบใหม่ (AssignerAgent จะเรียก auto_assign_all()
               ใหม่ทั้งหมด ซึ่งข้างในสุ่มลำดับ candidate ต่างจากรอบก่อน)

        ถ้า fully_complete เป็น False และ hard_issues ว่างเปล่า (ไม่มี hard issue
        เหลือ แต่ยังไม่ fully_complete เพราะมี failed_sessions ที่จัดไม่ได้ตั้งแต่ต้น):
            ห้ามเรียก fix_one_session() (ไม่มี session ให้แก้ เพราะ failed_sessions
            คือวิชาที่ไม่เคยถูกจัดเลย ไม่ใช่ session ที่จัดไปแล้วแต่ผิดกฎ)
            ห้ามเรียก exit_loop() ปล่อยให้วนรอบใหม่เหมือนเดิม

        สรุปสั้นๆ ในทุกกรณีว่าสถานะตอนนี้เป็นอย่างไร (รวม rounds_used จากรอบ fix
        ภายใน auto_assign_all() ด้วย) ถ้ามี failed_sessions ให้บอกว่า
        วิชา/session ไหนบ้างที่จัดไม่ได้ (session_id + เหตุผล) แยกจากปัญหา "ชนกัน"
        ที่เพิ่งแก้เฉพาะจุดไปให้ชัดเจน
        """,
    tools=[audit_and_report, fix_one_session, exit_loop],
)

quality_loop = LoopAgent(
    name="QualityLoop",
    sub_agents=[assigner_agent, checker_agent],
    max_iterations=MAX_LOOP_ITERATIONS,
    description="จัดตาราง(+แก้ปัญหาในตัว) -> ตรวจสอบ+แก้เฉพาะจุด วนจนกว่าจะสำเร็จครบถ้วนหรือครบจำนวนรอบ",
)

# SequentialAgent ชั้นนอกสุด: ดึงข้อมูลครั้งเดียว แล้วค่อยเข้า loop
scheduling_pipeline = SequentialAgent(
    name="SchedulingPipeline",
    sub_agents=[data_gather_agent, quality_loop],
    description="ดึงข้อมูล (ครั้งเดียว) -> จัดตาราง+ตรวจสอบ+แก้เฉพาะจุด (วนซ้ำได้จริง แต่ปกติจบรอบแรก)",
)

scheduling_tool = AgentTool(agent=scheduling_pipeline)