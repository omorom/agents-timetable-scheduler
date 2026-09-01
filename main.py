from dotenv import load_dotenv

load_dotenv(dotenv_path="agent_timetable/.env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import (
    base_data,
    subjects,
    subject_selected,
    schedule,
    unavailability,
    room_unavailability_import,
    chat,
    generate,
)


app = FastAPI(title="Schedule API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(base_data.router)
app.include_router(subjects.router)
app.include_router(subject_selected.router)
app.include_router(schedule.router)
app.include_router(room_unavailability_import.router)  # ต้องมาก่อน unavailability.router!
app.include_router(unavailability.router)               # มี /room-unavailability/{room_id} แบบ generic
app.include_router(chat.router)
app.include_router(generate.router)


@app.get("/")
def root():
    return {"status": "ok"}