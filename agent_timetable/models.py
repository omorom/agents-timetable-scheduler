import os
from google.adk.planners import BuiltInPlanner
from google.genai import types

try:
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
    from google.adk.models.lite_llm import LiteLlm
    print(f"[models] ใช้ OpenRouter: {OPENROUTER_MODEL}")
else:
    print(f"[models] ใช้ Gemini ตรง: {GEMINI_MODEL}")


def make_model(reasoning: bool = False):
    if USE_OPENROUTER:
        return LiteLlm(
            model=OPENROUTER_MODEL,
            api_key=OPENROUTER_API_KEY,
            extra_body={"reasoning": {"enabled": reasoning}},
        )
    return GEMINI_MODEL


def make_planner(reasoning: bool = False):
    if USE_OPENROUTER or reasoning:
        return None
    return BuiltInPlanner(thinking_config=types.ThinkingConfig(thinking_budget=0))


