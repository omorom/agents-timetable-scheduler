"""
pipeline_steps.py — งานส่วน Python ของแต่ละ Agent ใน scheduling_agent.py

ทุกฟังก์ชันรับ state (อ่าน/เขียนแบบ dict) ไม่ผูกกับ ADK — เทสต์ได้ตรงๆ
  gather_step()     DataGatherAgent: ดึงข้อมูลจาก Supabase + ล้าง state รอบก่อน + ตรวจข้อมูล
  assign_step()     AssignerAgent:   Greedy จัดทั้งตาราง / แก้เฉพาะจุดตามที่ CheckerAgent เลือก
  prepare_decision() CheckerAgent:   ตรวจกฎ + วิเคราะห์ + เตรียมตัวเลือกให้ LLM เลือก
  build_summary()   ข้อความสรุปสุดท้าย (รวมเหตุผลที่ Agent ตัดสินใจทุกรอบ)
"""

import time

from .load_data import refresh_cache, get_cached_data
from .auto_assign import auto_assign_all, retry_failed_sessions
from .assignment_store import get_current_schedule
from .find_issues import find_issues
from .data_check import check_data_readiness
from .retry_hints import empty_hints
from . import failure_analysis, soft_improve
# รอบที่ 1 Greedy จัดทั้งตาราง รอบถัดไปแก้เฉพาะจุด (รอบที่แย่กว่าเดิมถูกทิ้งเสมอ)
MAX_ATTEMPTS = 4
MAX_DATA_ISSUES_FOR_LLM = 15


def _subject_names() -> dict:
    return {s["subject_id"]: s.get("name_thai") or s.get("name_english") or s["subject_id"]
            for s in get_cached_data()["subjects"]}


def _schedule_table() -> str:
    data = get_cached_data()
    names = _subject_names()
    ts = {str(t["timeslot_id"]): t for t in data["timeslots"]}
    rooms = {r["room_id"]: r["room_name"] for r in data["rooms"]}
    lines = []
    for item in get_current_schedule():
        rows = sorted((ts[str(t)] for t in item.get("timeslot_ids", []) if str(t) in ts), key=lambda t: t["start_time"])
        when = f"{rows[0]['day']} {rows[0]['start_time']}-{rows[-1]['end_time']}" if rows else "-"
        sec = f" (section {item['section']})" if item.get("section") else ""
        lines.append(f"- {names.get(item['subject_id'], item['subject_id'])} [{item['session_type']}]{sec}: "
                     f"{rooms.get(item['room_id'], item['room_id'])}, {when}")
    return "\n".join(lines)


# ───────────── DataGatherAgent ─────────────

def gather_step(state) -> dict:
    data = refresh_cache()   # ดึงจาก Supabase ใหม่ทุกครั้ง
    summary = {
        "teacher_count": len(data["teachers"]),
        "room_count": len(data["rooms"]),
        "section_count": len(data["sections"]),
        "has_sections": len(data["sections"]) > 0,
    }
    for key, value in {
        "context_summary": summary, "retry_hints": empty_hints(), "attempt_no": 0, "attempt_log": [],
        "fix_options": {}, "pending_moves": [], "soft_options": {}, "pending_soft_fixes": [],
        "final_report": {}, "data_review": "", "last_diagnosis": {}, "last_soft_review": [],
    }.items():
        state[key] = value
    failure_analysis.reset_best()

    state["data_issues"] = check_data_readiness() if summary["has_sections"] else []
    summary["data_issue_count"] = len(state["data_issues"])
    return summary


# ───────────── AssignerAgent ─────────────

def assign_step(state) -> dict:
    """รับคำสั่งจาก CheckerAgent (pending_moves / pending_soft_fixes) แล้วให้ Greedy ลงมือ"""
    if not (state.get("context_summary") or {}).get("has_sections"):
        state["schedule_result"] = {"failed_count": 0, "failed_sessions": [], "no_sections": True}
        return state["schedule_result"]

    attempt_no = (state.get("attempt_no") or 0) + 1
    state["attempt_no"] = attempt_no
    previous = failure_analysis.best_result()
    moves = state.get("pending_moves") or []
    soft_fixes = state.get("pending_soft_fixes") or []
    state["pending_moves"], state["pending_soft_fixes"] = [], []

    started = time.time()
    if previous is None:
        res, mode = auto_assign_all(), "full"
    elif soft_fixes:
        res, mode = soft_improve.apply_soft_fixes(soft_fixes, previous.get("failed_sessions", [])), "improve_quality"
    else:
        res = retry_failed_sessions(state.get("retry_hints") or empty_hints(), previous.get("failed_sessions", []), moves)
        mode = "retry_failed_only"
    print(f"[timing] attempt {attempt_no} {mode} (Python): {time.time() - started:.1f}s")

    result = {
        "failed_count": res["failed_count"],
        "failed_sessions": res["failed"],
        "remaining_hard_issue_count": res["remaining_hard_issue_count"],
        "remaining_soft_issue_count": res["remaining_soft_issue_count"],
        "rounds_used": res["rounds_used"],
        "no_sections": False,
    }
    improved = failure_analysis.keep_if_best(result)
    if not improved:
        result = failure_analysis.restore_best() or result   # แย่ลง -> คืนรอบที่ดีที่สุด

    state["attempt_log"] = list(state.get("attempt_log") or []) + [{
        "attempt": attempt_no, "mode": mode, "kept": improved,
        "score": list(failure_analysis.schedule_score(res)), "moves": res.get("moves", []),
    }]
    state["schedule_result"] = result
    return result


# ───────────── CheckerAgent ─────────────

def _audit(state) -> dict:
    sr = state.get("schedule_result") or {}
    if sr.get("no_sections"):
        report = {"status": "no_sections", "message": "ไม่มีวิชาที่เปิดสอนในระบบเลย ไม่มีอะไรให้จัดตาราง"}
        state["final_report"] = report
        return report

    issues = find_issues()
    hard = [i for i in issues if i.get("severity") == "hard"]
    failed = sr.get("failed_sessions", [])
    attempt_no = state.get("attempt_no") or 0
    report = {
        "status": "ok" if not hard and not failed else "incomplete",
        "fully_complete": not hard and not failed,
        "attempts_used": attempt_no,
        "attempts_left": max(0, MAX_ATTEMPTS - attempt_no),
        "rounds_used": sr.get("rounds_used"),
        "hard_issue_count": len(hard),
        "soft_issue_count": sum(1 for i in issues if i.get("severity") == "soft"),
        "hard_issues": [{"type": i.get("type"), "fix_session_id": i.get("fix_session_id"), "detail": i.get("detail")}
                        for i in hard if i.get("fix_session_id")],
        "failed_sessions": failed,
    }
    state["final_report"] = {
        **report,
        "attempt_log": state.get("attempt_log", []),
        "data_issues": state.get("data_issues", []),
        "data_review": state.get("data_review", ""),
        "schedule_table": _schedule_table(),   # เก็บไว้ใน state เท่านั้น ไม่ส่งให้ LLM อ่าน
    }
    return report


def _diagnose(state) -> dict:
    hard = [i for i in find_issues() if i.get("severity") == "hard"]
    diag = failure_analysis.diagnose((state.get("schedule_result") or {}).get("failed_sessions", []), hard)
    state["fix_options"] = diag.pop("_option_map")
    state["last_diagnosis"] = {v: sorted({d["subject"] for d in diag["failed"] if d["verdict"] == v})
                               for v in ("data_problem", "needs_manual")}
    return diag


def prepare_decision(state) -> tuple[str | None, dict | None]:
    """คืน (mode, brief): "retry" = แก้วิชาที่จัดไม่ได้ / "soft" = ปรับ LAB ที่อยู่ก่อน LECTURE
    / None = ไม่มีอะไรให้ตัดสินใจ (หยุด loop ไม่ต้องเรียก LLM)
    """
    state["pending_moves"], state["pending_soft_fixes"] = [], []
    report = _audit(state)
    if report["status"] == "no_sections" or report["attempts_left"] <= 0:
        return None, None

    if not report["fully_complete"]:
        diag = _diagnose(state)
        if not diag.get("retry_cannot_help") and (
                diag["hard_issues"] or any(d["verdict"] == "retry_may_help" for d in diag["failed"])):
            keep = ("subject_id", "subject", "session_type", "verdict", "why", "options")
            return "retry", {
                "attempts_left": report["attempts_left"],
                "failed": [{k: d[k] for k in keep if d.get(k)} for d in diag["failed"]],
                "hard_issues": [{k: i.get(k) for k in ("subject_id", "subject", "detail")} for i in diag["hard_issues"]],
                "data_problems_found_before_scheduling": [
                    f"{i['subject']}: {i['detail']}" if i.get("subject") else i["detail"]
                    for i in (state.get("data_issues") or [])[:MAX_DATA_ISSUES_FOR_LLM]
                ],
            }

    if report["soft_issue_count"]:
        review = soft_improve.review_soft_issues()
        state["soft_options"] = review.pop("_option_map")
        state["last_soft_review"] = [{"verdict": i["verdict"], "why": i.get("why")} for i in review["issues"]]
        if any(i["verdict"] == "can_improve" for i in review["issues"]):
            return "soft", {"soft_issue_count": review["soft_issue_count"], "issues": review["issues"]}

    return None, None


def build_summary(state) -> str:
    report = state.get("final_report") or {}
    if report.get("status") == "no_sections":
        return report.get("message", "ไม่มีวิชาที่เปิดสอนในระบบเลย")

    attempts = report.get("attempts_used", 0)
    if report.get("fully_complete"):
        lines = [f"จัดตารางครบทุกวิชา ไม่มีปัญหาชนกัน (ใช้ {attempts} รอบ)"]
    else:
        lines = [f"จัดตารางเสร็จ เหลือวิชาที่จัดไม่ได้ {len(report.get('failed_sessions', []))} รายการ "
                 f"และปัญหาชนกัน {report.get('hard_issue_count', 0)} จุด (ใช้ {attempts} รอบ)"]

    # การตัดสินใจของ CheckerAgent แต่ละรอบ + ผลที่เกิดขึ้นจริง
    log = state.get("attempt_log") or []
    done = {e["attempt"]: e for e in log if "attempt" in e}
    for e in log:
        if "declined_after_attempt" in e:
            lines.append(f"• CheckerAgent ตัดสินใจไม่แก้ต่อ: {e['reason']}")
        elif "advice_for_attempt" in e:
            result = done.get(e["advice_for_attempt"])
            outcome = "" if result is None else (" → ตารางดีขึ้น" if result["kept"]
                                                 else " → ลองแล้วไม่ดีขึ้น ระบบคืนตารางเดิม")
            lines.append(f"• CheckerAgent: {e['reason']}{outcome}")

    if report.get("soft_issue_count"):
        why = sorted({i["why"] for i in state.get("last_soft_review") or [] if i.get("why")})
        lines.append(f"LAB ที่ยังอยู่ก่อนวัน LECTURE: {report['soft_issue_count']} จุด"
                     + (f" ({'; '.join(why)})" if why else ""))

    names = _subject_names()
    failed = sorted({names.get(f.get("subject_id"), f.get("subject_id") or "-") for f in report.get("failed_sessions", [])})
    diag = state.get("last_diagnosis") or {}
    for title, items in (("ยังจัดไม่ได้", failed),
                         ("ติดข้อมูล ต้องแก้ข้อมูลก่อน", diag.get("data_problem")),
                         ("ต้องลากวางเองในหน้าตาราง", diag.get("needs_manual"))):
        if items:
            lines.append(f"{title}: {', '.join(items)}")

    if (state.get("data_review") or "").strip():
        lines.append("ผลตรวจข้อมูลก่อนจัด (DataGatherAgent):\n" + state["data_review"].strip())
    return "\n".join(lines)