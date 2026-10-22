"""
test_chat.py — ส่งคำสั่งทดสอบเข้าแชท Agent ทีละข้อ แล้วบันทึกคำตอบ + เวลาที่ใช้

วิธีรัน (ต้องเปิด backend ไว้อีกหน้าต่างก่อน: uvicorn main:app --reload)
    python -u test_chat.py | Tee-Object chat_result.txt

แต่ละข้อใช้ user_id แยกกัน คำสั่งจะไม่ปนบริบทกัน
คำสั่งทุกข้อเป็นการถามหรือตรวจ ไม่มีการแก้ตารางจริง (แชทตรวจได้ว่าย้ายได้ไหม แต่ไม่ย้ายเอง)
อ้างอาจารย์ผ่านวิชาที่สอน และใช้รหัสห้องจริง เพราะแชทค้นจากชื่อ ไม่ใช่รหัส T12 / id ห้อง
"""

import json
import time
import urllib.request

URL = "http://localhost:8000/chat"

# แก้คำสั่งให้ตรงกับข้อมูลและความสามารถของแชทได้เลย
TESTS = [
    ("ถามข้อมูล", "มีห้องเรียนกี่ห้อง"),
    ("ถามข้อมูล", "อาจารย์ที่สอนวิชา 273252 สอนวิชาอะไรอีกบ้าง"),
    ("ถามตาราง", "วิชา 273252 เรียนวันไหน ห้องอะไร"),
    ("ถามตาราง", "ห้อง SC1-213 วันพุธว่างช่วงไหนบ้าง"),
    ("ตรวจตาราง", "ตารางตอนนี้มีปัญหาอะไรไหม"),
    ("ตรวจตาราง", "กลุ่ม IT ปี 3 มีวันไหนเรียนหนักเกินไปไหม"),
    ("ตรวจการย้าย", "ย้ายวิชา 254374 ไปวันศุกร์ 13:00-15:50 ได้ไหม"),
    ("ตรวจการย้าย (ควรบอกว่าไม่ได้)", "ย้ายวิชา 001101 ไปวันจันทร์ 08:00-10:50 ได้ไหม"),
    ("ขอคำแนะนำ", "ถ้าอยากให้อาจารย์ที่สอนวิชา 273411 ไม่ต้องสอนวันศุกร์ ทำได้ไหม"),
    ("ตรวจตาราง", "ตอนนี้ตารางมีวิชาชนกันไหม"),
]


def ask(message: str, user_id: str) -> tuple[str, float]:
    body = json.dumps({"message": message, "user_id": user_id}).encode("utf-8")
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"}, method="POST")
    started = time.time()
    with urllib.request.urlopen(req, timeout=300) as resp:
        raw = resp.read().decode("utf-8")
    took = time.time() - started
    try:
        data = json.loads(raw)
    except ValueError:
        return raw, took
    if isinstance(data, dict):
        for key in ("response", "reply", "message", "answer", "text"):
            if isinstance(data.get(key), str):
                return data[key], took
    return json.dumps(data, ensure_ascii=False, indent=2), took


def main() -> None:
    run_id = int(time.time())
    times = []
    for i, (kind, message) in enumerate(TESTS, 1):
        print(f"\n===== ข้อ {i}/{len(TESTS)} [{kind}] =====")
        print(f"คำสั่ง: {message}")
        try:
            answer, took = ask(message, f"chat-test-{run_id}-{i}")
        except Exception as e:  # noqa: BLE001
            print(f"error: {e}")
            continue
        times.append(took)
        print(f"เวลา: {took:.1f} วินาที")
        print("คำตอบ:")
        print(answer)
        print("ผล (จดเอง): [ ] ถูก  [ ] ผิด   หมายเหตุ: ")

    if times:
        print(f"\n===== สรุป =====")
        print(f"ส่งคำสั่งสำเร็จ {len(times)}/{len(TESTS)} ข้อ | "
              f"เวลาเฉลี่ย {sum(times) / len(times):.1f} วินาที (เร็วสุด {min(times):.1f} / ช้าสุด {max(times):.1f})")
        print("ค่าใช้จ่ายดูจากบรรทัด [cost] ในหน้าต่าง uvicorn")


if __name__ == "__main__":
    main()