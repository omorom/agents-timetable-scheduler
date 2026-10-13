"""
agent_tools.py — ด่านกลางระหว่าง AI กับระบบ

  1) Tool ที่ AI เรียกเพื่อส่งคำตอบกลับมา (AI ตอบเป็นข้อความอิสระไม่ได้ ต้องเรียกฟังก์ชันเหล่านี้)
     Python ตรวจทุกค่าที่ AI ส่งมา: รหัสที่ไม่มีอยู่จริงถูกตัดทิ้ง AI จึงแต่งทางแก้ใหม่เองไม่ได้
       - ฝั่ง DataGather: recommend
       - ฝั่ง Checker:    suggest_retry, suggest_soft_fixes, exit_loop
  2) ทางสำรองที่ Python ใช้แทน เมื่อ AI ตอบไม่ตรงรูปแบบ (ไม่เรียก tool / ส่งค่าว่าง)
       - fallback_decision, fallback_options
  3) ตัวเตรียมข้อมูลให้ AI เลือก: build_option_map
"""

from google.adk.tools.tool_context import ToolContext

from .tools.scheduling.load_data import get_cached_data
from .tools.scheduling.retry_hints import merge_hints
from .tools.scheduling.pipeline_steps import MAX_DATA_ISSUES_FOR_LLM

MAX_OPTIONS_PER_ATTEMPT = 3      # Checker: เลือกวิธีแก้ได้ไม่เกินกี่ตัวต่อรอบ
MAX_DATA_OPTIONS = 3             # DataGather: ทางเลือกที่แสดงให้ผู้ใช้ไม่เกินกี่ข้อ
MAX_REASON_CHARS = 120
CONTINUE_ID = "CONTINUE"
CONTINUE_TEXT = "จัดต่อเลย แล้วลากวางวิชาที่ข้ามไปเองทีหลัง"


# ───────────── ฝั่ง Checker ─────────────

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


# ───────────── ฝั่ง DataGather ─────────────

def _clean_option(text) -> str:
    """ทำให้ทางแก้แต่ละข้ออ่านเป็นประโยคเดี่ยว: ตัด "หรือ" นำหน้า (มาจาก alt ที่เขียนไว้ต่อท้ายทางแก้หลัก)
    ตัดเลขข้อ / ขีด / "ค่ะ" ท้าย"""
    s = str(text or "").strip()
    s = s.lstrip("-•*0123456789.) ").strip()
    s = s.removeprefix("หรือ").strip()
    s = s.removesuffix("ค่ะ").strip()
    return s


def build_option_map(issues: list) -> dict[str, dict]:
    """ทางแก้ทั้งหมดที่ Python คำนวณไว้ ให้รหัส A1, A2, ... (ข้อความห้ามเปลี่ยน — AI เลือกได้แค่รหัส)
    + ทาง "จัดต่อเลย" (CONTINUE) เสมอ"""
    out: dict[str, dict] = {}
    seen: set[str] = set()
    blocking = [i for i in issues or [] if i.get("severity") == "blocking"][:MAX_DATA_ISSUES_FOR_LLM]
    for issue in blocking:
        for raw in (issue.get("suggestion"), issue.get("alt")):
            text = _clean_option(raw)
            if not text or text in seen:
                continue
            seen.add(text)
            out[f"A{len(out) + 1}"] = {"text": text, "issue": issue.get("title") or issue.get("detail") or ""}
    out[CONTINUE_ID] = {"text": CONTINUE_TEXT, "issue": ""}
    return out


def recommend(tool_context: ToolContext, decision: str, message: str,
              option_ids: list[str], reasons: list[str]) -> dict:
    """ส่งคำแนะนำให้ผู้ใช้ก่อนจัดตาราง

    decision: "fix_first" = ควรแก้ข้อมูลก่อนกดจัด / "ok_to_continue" = จัดต่อได้เลย แล้วจัดวิชาที่เหลือเองทีหลัง
    message: ข้อความถึงผู้ใช้ 1-2 ประโยค
    option_ids: รหัสทางเลือก 2-3 ตัว (จากรายการที่ให้) เรียงจากที่แนะนำที่สุด
    reasons: เหตุผลสั้นๆ ของแต่ละทางเลือก เรียงตรงกับ option_ids
    """
    if decision not in ("fix_first", "ok_to_continue"):
        return {"accepted": False, "reason": "decision ต้องเป็น fix_first หรือ ok_to_continue"}
    if not (message or "").strip():
        return {"accepted": False, "reason": "message ว่าง"}

    option_map = tool_context.state.get("data_option_map") or {}
    reasons = list(reasons or [])
    chosen, used = [], set()
    for idx, oid in enumerate(option_ids or []):
        oid = str(oid).strip()
        if oid not in option_map or oid in used:   # รหัสที่ไม่มีจริง / ซ้ำ -> ตัดทิ้ง (AI แต่งทางแก้เองไม่ได้)
            continue
        used.add(oid)
        reason = _clean_option(reasons[idx] if idx < len(reasons) else "")[:MAX_REASON_CHARS]
        chosen.append({"id": oid, "text": option_map[oid]["text"], "reason": reason})
        if len(chosen) >= MAX_DATA_OPTIONS:
            break
    if not chosen:
        return {"accepted": False, "reason": "option_ids ไม่ตรงกับรายการที่ให้ ใช้ได้เฉพาะ: " + ", ".join(option_map)}

    tool_context.state["data_decision"] = decision
    tool_context.state["data_review"] = message.strip()
    tool_context.state["data_options"] = chosen
    tool_context.actions.skip_summarization = True   # ได้คำตอบแล้ว ไม่ต้องให้ LLM พูดต่อ
    return {"accepted": True}


def fallback_options(option_map: dict, decision: str) -> list[dict]:
    """ทางเลือกสำรองจาก Python (ใช้เมื่อ LLM ไม่ได้ส่ง options มา) — ทางแก้ 2 ข้อแรก + จัดต่อ ไม่มีเหตุผลประกอบ"""
    fixes = [oid for oid in option_map if oid != CONTINUE_ID][:MAX_DATA_OPTIONS - 1]
    ids = ([CONTINUE_ID] + fixes) if decision == "ok_to_continue" else (fixes + [CONTINUE_ID])
    return [{"id": oid, "text": option_map[oid]["text"], "reason": ""} for oid in ids if oid in option_map]


def fallback_decision(skip_impact: list) -> str:
    """ใช้เมื่อ LLM ตอบเป็นข้อความแต่ไม่เรียก tool recommend (คำตัดสินจึงหายไป)
    ตัดสินด้วยกฎเดียวกับใน prompt: มีวิชาบังคับจัดไม่ได้ หรือจัดไม่ได้ตั้งแต่ 3 วิชา -> ควรแก้ก่อน
    หน้าเว็บจะได้แสดงปุ่มแบบเดียวกับตอนที่ LLM เรียก tool เสมอ
    """
    impact = skip_impact or []
    must_fix = any(not i.get("elective") for i in impact) or len(impact) >= 3
    return "fix_first" if must_fix else "ok_to_continue"