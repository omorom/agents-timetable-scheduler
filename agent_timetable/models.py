"""
models.py
ตั้งค่าโมเดลที่ทุก agent ใช้ร่วมกัน

- ถ้ามี OPENROUTER_API_KEY ใน .env → ใช้ OpenRouter (ผ่าน LiteLLM)
- ถ้าไม่มี แต่มี GOOGLE_API_KEY      → ใช้ Gemini ตรงจาก Google แบบเดิม
"""

import os

from google.adk.planners import BuiltInPlanner
from google.genai import types

try:
    # เผื่อรันผ่าน uvicorn ที่ไม่ได้โหลด .env ให้เอง (adk web โหลดให้อยู่แล้ว)
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/google/gemini-2.5-flash")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

USE_OPENROUTER = bool(OPENROUTER_API_KEY)

if not USE_OPENROUTER and not GOOGLE_API_KEY:
    raise RuntimeError("ไม่พบทั้ง OPENROUTER_API_KEY และ GOOGLE_API_KEY ใน .env ต้องมีอย่างน้อย 1 ตัว")

if USE_OPENROUTER:
    # import เฉพาะตอนใช้ จะได้ไม่ต้องลง litellm ถ้าใช้ Gemini ตรงอย่างเดียว
    from google.adk.models.lite_llm import LiteLlm
    print(f"[models] ใช้ OpenRouter: {OPENROUTER_MODEL}")
else:
    print(f"[models] ใช้ Gemini ตรง: {GEMINI_MODEL}")


def make_model(reasoning: bool = False):
    """โมเดลสำหรับใส่ใน Agent(model=...)

    Args:
        reasoning: False = ปิดการคิดก่อนตอบ (เร็วกว่า) / True = เปิด
    """
    if USE_OPENROUTER:
        return LiteLlm(
            model=OPENROUTER_MODEL,
            api_key=OPENROUTER_API_KEY,
            extra_body={"reasoning": {"enabled": reasoning}},
        )
    # Gemini ตรง: ADK รับเป็นชื่อโมเดลธรรมดา แล้วอ่าน GOOGLE_API_KEY จาก env เอง
    return GEMINI_MODEL


def make_planner(reasoning: bool = False):
    """planner สำหรับใส่ใน Agent(planner=...)

    Gemini ตรงต้องปิด thinking ผ่าน planner ส่วน OpenRouter ปิดใน make_model() แล้ว
    เลยคืน None (= ไม่ใช้ planner)
    """
    if USE_OPENROUTER or reasoning:
        return None
    return BuiltInPlanner(thinking_config=types.ThinkingConfig(thinking_budget=0))