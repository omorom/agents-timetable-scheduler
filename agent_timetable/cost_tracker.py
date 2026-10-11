"""
cost_tracker.py — นับ token ที่ agent ใช้ แล้วคิดเป็นเงิน (ดอลลาร์ + บาท)

ใช้กับ Agent ผ่าน after_model_callback (ทำงานหลัง LLM ตอบทุกครั้ง):
    Agent(..., after_model_callback=track_usage)

ตัวเลขเป็น "ค่าประมาณ" จาก token × ราคาที่ตั้งไว้ด้านล่าง ไม่ใช่ยอดเรียกเก็บจริง
(ยอดจริงดูได้ที่ https://openrouter.ai/activity) ราคาเปลี่ยนได้ ตั้งทับได้ใน .env:
    PRICE_INPUT_PER_M=0.30      # ดอลลาร์ ต่อ 1 ล้าน token ขาเข้า
    PRICE_OUTPUT_PER_M=2.50     # ดอลลาร์ ต่อ 1 ล้าน token ขาออก
    USD_TO_THB=33.5             # อัตราแลกเปลี่ยน

ค่าเริ่มต้น = ราคา google/gemini-2.5-flash บน OpenRouter (ต.ค. 2026)
"""

import os

PRICE_INPUT_PER_M = float(os.getenv("PRICE_INPUT_PER_M", "0.30"))
PRICE_OUTPUT_PER_M = float(os.getenv("PRICE_OUTPUT_PER_M", "2.50"))
USD_TO_THB = float(os.getenv("USD_TO_THB", "33.5"))

STATE_KEY = "llm_usage"


def _empty() -> dict:
    return {"calls": 0, "input_tokens": 0, "output_tokens": 0, "by_agent": {}}


def _cost(input_tokens: int, output_tokens: int) -> tuple[float, float]:
    usd = input_tokens / 1e6 * PRICE_INPUT_PER_M + output_tokens / 1e6 * PRICE_OUTPUT_PER_M
    return usd, usd * USD_TO_THB


def reset_usage(callback_context) -> None:
    """เริ่มนับใหม่ (เรียกตอนเริ่มการจัดตารางแต่ละครั้ง)"""
    callback_context.state[STATE_KEY] = _empty()


def track_usage(callback_context, llm_response):
    """after_model_callback: บวก token ของการเรียก LLM ครั้งนี้เข้ายอดรวม (ไม่แก้คำตอบของ LLM)
    ห่อ try ไว้ทั้งหมด: ถ้านับพลาด แค่ข้ามไป ไม่ทำให้การจัดตารางล้ม
    """
    try:
        _track(callback_context, llm_response)
    except Exception as e:  # noqa: BLE001
        print(f"[cost] นับค่าใช้จ่ายไม่สำเร็จ (ไม่กระทบการทำงาน): {e!r}")
    return None   # None = ใช้คำตอบของ LLM ตามเดิม ไม่แก้อะไร


def _track(callback_context, llm_response) -> None:
    meta = getattr(llm_response, "usage_metadata", None)
    if not meta:
        return
    inp = meta.prompt_token_count or 0
    # OpenRouter: completion_tokens รวม token ที่ใช้คิด (reasoning) ไว้แล้ว
    # Gemini ตรง: token ที่ใช้คิดแยกอยู่ใน thoughts_token_count ต้องบวกเพิ่ม (คิดราคาแบบ output)
    out = meta.candidates_token_count or 0
    from .models import USE_OPENROUTER
    if not USE_OPENROUTER:
        out += meta.thoughts_token_count or 0

    usage = dict(callback_context.state.get(STATE_KEY) or _empty())
    usage["calls"] += 1
    usage["input_tokens"] += inp
    usage["output_tokens"] += out
    by_agent = dict(usage.get("by_agent") or {})
    a = dict(by_agent.get(callback_context.agent_name) or {"calls": 0, "input_tokens": 0, "output_tokens": 0})
    a["calls"] += 1
    a["input_tokens"] += inp
    a["output_tokens"] += out
    by_agent[callback_context.agent_name] = a
    usage["by_agent"] = by_agent
    callback_context.state[STATE_KEY] = usage

    _, thb = _cost(inp, out)
    print(f"[cost] {callback_context.agent_name}: in {inp:,} / out {out:,} tokens ~ {thb:.4f} บาท")


def usage_summary(state) -> dict:
    """สรุปยอดรวม (ใส่ใน final_report ให้หน้าเว็บแสดงได้)"""
    usage = state.get(STATE_KEY) or _empty()
    usd, thb = _cost(usage["input_tokens"], usage["output_tokens"])
    by_agent = {}
    for name, a in (usage.get("by_agent") or {}).items():
        a_usd, a_thb = _cost(a["input_tokens"], a["output_tokens"])
        by_agent[name] = {**a, "cost_usd": round(a_usd, 6), "cost_thb": round(a_thb, 4)}
    return {
        "calls": usage["calls"],
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "cost_usd": round(usd, 6),
        "cost_thb": round(thb, 4),
        "by_agent": by_agent,
        "note": "ค่าประมาณจาก token × ราคาที่ตั้งไว้ ยอดจริงดูที่ openrouter.ai/activity",
    }


def print_summary(state) -> None:
    try:
        _print_summary(state)
    except Exception as e:  # noqa: BLE001
        print(f"[cost] สรุปค่าใช้จ่ายไม่สำเร็จ (ไม่กระทบการทำงาน): {e!r}")


def _print_summary(state) -> None:
    s = usage_summary(state)
    print(f"[cost] รวมครั้งนี้: เรียก LLM {s['calls']} ครั้ง, "
          f"in {s['input_tokens']:,} / out {s['output_tokens']:,} tokens "
          f"~ ${s['cost_usd']:.4f} ~ {s['cost_thb']:.2f} บาท")
    for name, a in s["by_agent"].items():
        print(f"[cost]   {name}: {a['calls']} ครั้ง ~ {a['cost_thb']:.4f} บาท")


def track_usage_chat(callback_context, llm_response):
    """after_model_callback สำหรับแชทบอท: นับเหมือน track_usage แล้วพิมพ์ยอดสะสมของแชทนี้ด้วย"""
    track_usage(callback_context, llm_response)
    try:
        s = usage_summary(callback_context.state)
        print(f"[cost] แชทนี้สะสม: เรียก LLM {s['calls']} ครั้ง ~ {s['cost_thb']:.4f} บาท")
    except Exception as e:  # noqa: BLE001
        print(f"[cost] สรุปค่าใช้จ่ายแชทไม่สำเร็จ (ไม่กระทบการทำงาน): {e!r}")
    return None