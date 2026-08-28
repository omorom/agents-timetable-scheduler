"use client";

import { useState, useEffect, useCallback } from "react";
import { X, Loader2, Lock } from "lucide-react";
import { Timeslot, DAYS, DAY_TH, DAY_ABBR, API_BASE } from "./types";

interface Props {
  kind: "teacher" | "room";
  entityId: string;
}

const LUNCH_SLOT = "12:00-12:50";
const START_HOUR = 8;
const END_HOUR = 16;

const pad = (n: number) => n.toString().padStart(2, "0");
const hourOf = (t: string) => parseInt(t.split(":")[0], 10);
const dayOf = (x: { day: string }) => DAY_ABBR[x.day] ?? x.day;

const DISPLAY_SLOTS = Array.from(
  { length: END_HOUR - START_HOUR + 1 },
  (_, i) => `${pad(START_HOUR + i)}:00-${pad(START_HOUR + i)}:50`
);

function findSpan(startTime: string, endTime: string): { startIdx: number; span: number } | null {
  const slotHours = DISPLAY_SLOTS.map(hourOf);
  const startIdx = slotHours.indexOf(hourOf(startTime));
  if (startIdx === -1) return null;
  const endHour = hourOf(endTime);
  let span = 0;
  for (let i = startIdx; i < slotHours.length && slotHours[i] < endHour; i++) span++;
  return { startIdx, span: span || 1 };
}

// สถานะของแต่ละ timeslot ที่ได้จาก endpoint /schedule-grid
type SlotStatus = "teaching" | "unavailable" | "free";

type CellState =
  | { kind: "lunch" }
  | { kind: "covered" }
  | { kind: "slot"; timeslotId: string; span: number; status: SlotStatus; subjectId: string | null };

export default function UnavailabilityGrid({ kind, entityId }: Props) {
  const [timeslots, setTimeslots] = useState<Timeslot[]>([]);
  // เดิมเป็น Set<string> (unavailable อย่างเดียว) เปลี่ยนเป็น Map เก็บ status ต่อ timeslot
  const [statusMap, setStatusMap] = useState<Map<string, SlotStatus>>(new Map());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [blockedMsg, setBlockedMsg] = useState("");

  const idParam = kind === "teacher" ? "teacher_id" : "room_id";
  const basePath = kind === "teacher" ? "teacher-unavailability" : "room-unavailability";
  void idParam; // เผื่อใช้ debug/แสดงผลภายหลัง ไม่กระทบ logic ปัจจุบัน

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      // เปลี่ยนจาก fetch `${basePath}/${entityId}` (list unavailability อย่างเดียว)
      // มาเรียก `${basePath}/${entityId}/schedule-grid` ที่คืน status ครบ 3 แบบ
      // (รวม timetable_ai เข้ามาแล้วฝั่ง backend)
      const [tRes, gRes] = await Promise.all([
        fetch(`${API_BASE}/timeslots`),
        fetch(`${API_BASE}/${basePath}/${entityId}/schedule-grid`),
      ]);
      const [tData, gData] = await Promise.all([tRes.json(), gRes.json()]);

      setTimeslots(Array.isArray(tData) ? tData : []);

      const gList: { timeslot_id: string | number; status: SlotStatus }[] = Array.isArray(gData) ? gData : [];
      setStatusMap(new Map(gList.map((g) => [String(g.timeslot_id), g.status])));
    } catch {
      setError("ไม่สามารถโหลดข้อมูลได้ กรุณาตรวจสอบการเชื่อมต่อ API");
    } finally {
      setLoading(false);
    }
  }, [basePath, entityId]);

  useEffect(() => { load(); }, [load]);

  async function toggle(timeslotId: string, status: SlotStatus) {
    // ห้าม toggle ช่องที่ "สอนอยู่แล้ว" — ต้องไปแก้ที่หน้าตารางหลักแทน
    if (status === "teaching") {
      setBlockedMsg("ช่วงเวลานี้มีสอนอยู่แล้ว ต้องการเปลี่ยนกรุณาไปที่หน้าตารางหลัก");
      window.setTimeout(() => setBlockedMsg(""), 2500);
      return;
    }
    if (saving) return; // กันกดรัวๆ ระหว่างบันทึกยังไม่เสร็จ
    setSaving(timeslotId);
    setError("");

    // อัปเดตหน้าจอทันที (optimistic) แล้วค่อยยืนยันกับ backend
    const wasUnavailable = status === "unavailable";
    setStatusMap((prev) => {
      const next = new Map(prev);
      next.set(timeslotId, wasUnavailable ? "free" : "unavailable");
      return next;
    });

    try {
      const res = await fetch(`${API_BASE}/${basePath}/${entityId}/toggle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ timeslot_id: Number(timeslotId) }),
      });
      if (!res.ok) throw new Error("toggle failed");
    } catch {
      // ถ้าบันทึกไม่สำเร็จ ย้อนสถานะกลับ
      setStatusMap((prev) => {
        const next = new Map(prev);
        next.set(timeslotId, wasUnavailable ? "unavailable" : "free");
        return next;
      });
      setError("บันทึกไม่สำเร็จ กรุณาลองใหม่");
    } finally {
      setSaving(null);
    }
  }

  function buildDayCells(day: string): CellState[] {
    const cells: CellState[] = DISPLAY_SLOTS.map((slot) =>
      slot === LUNCH_SLOT ? { kind: "lunch" } : { kind: "covered" }
    );

    for (const t of timeslots.filter((t) => dayOf(t) === day)) {
      const span = findSpan(t.start_time, t.end_time);
      if (!span) continue;
      const id = String(t.timeslot_id);
      const status = statusMap.get(id) ?? "free";
      cells[span.startIdx] = { kind: "slot", timeslotId: id, span: span.span, status, subjectId: null };
      for (let i = span.startIdx + 1; i < span.startIdx + span.span; i++) {
        cells[i] = { kind: "covered" };
      }
    }

    return cells;
  }

  if (loading) {
    return (
      <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
        <div className="skeleton h-52 w-full rounded-lg" />
      </div>
    );
  }

  return (
    <div>
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-red-600 text-sm mb-4">
          {error}
        </div>
      )}
      {blockedMsg && (
        <div className="bg-gray-50 border border-gray-200 rounded-xl px-4 py-3 text-gray-600 text-sm mb-4">
          {blockedMsg}
        </div>
      )}

      <p className="text-[13px] text-gray-500 mb-3">
        {kind === "room"
          ? "คลิกเลือกช่วงเวลาที่ห้องเรียนนี้ไม่ว่าง"
          : "คลิกเลือกช่วงเวลาที่อาจารย์ไม่สะดวกสอน"}
      </p>

      {/* legend สั้นๆ ให้แยกสีออกว่าอันไหนคืออะไร */}
      <div className="flex items-center gap-4 mb-3 text-[11px] text-gray-500">
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-sm bg-red-50 border border-red-200 inline-block" />
          ไม่สะดวกสอน (ตั้งเอง)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-sm bg-gray-200 border border-gray-300 inline-block" />
          สอนอยู่แล้ว (แก้ที่หน้าตาราง)
        </span>
      </div>

      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse min-w-160 table-fixed">
            <thead>
              <tr>
                <th className="bg-linear-to-r from-orange-500 to-orange-400 text-white text-left px-4 py-3 text-xs font-semibold w-27.5 min-w-27.5">
                  วัน / เวลา
                </th>
                {DISPLAY_SLOTS.map((slot) => (
                  <th
                    key={slot}
                    className={`text-white text-center px-2 py-3 text-[11px] font-semibold border-l border-orange-400/40 min-w-24
                      ${slot === LUNCH_SLOT ? "bg-orange-300/70" : "bg-linear-to-r from-orange-500 to-orange-400"}`}
                  >
                    {slot}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {DAYS.map((day, di) => (
                <tr key={day} className={di % 2 === 0 ? "bg-white" : "bg-slate-50/60"}>
                  <td className="px-4 py-2 border-b border-gray-100 border-r border-r-gray-100">
                    <div className="text-[13px] font-bold text-gray-800">{DAY_TH[day]}</div>
                    <div className="text-[10px] text-gray-400 font-medium">{day}</div>
                  </td>

                  {buildDayCells(day).map((cell, i) => {
                    if (cell.kind === "covered") return null;

                    const slot = DISPLAY_SLOTS[i];
                    const isLunch = cell.kind === "lunch";

                    if (isLunch) {
                      return (
                        <td key={slot} className="p-1.5 border border-gray-100 h-16 align-top bg-slate-50">
                          <div className="h-full flex items-center justify-center">
                            <span className="text-[9px] text-gray-300 font-medium tracking-widest uppercase">พักเที่ยง</span>
                          </div>
                        </td>
                      );
                    }

                    if (cell.kind !== "slot") {
                      return <td key={slot} className="p-1.5 border border-gray-100 h-16 bg-gray-50/40" />;
                    }

                    const isSaving = saving === cell.timeslotId;
                    const { status } = cell;

                    return (
                      <td
                        key={slot}
                        colSpan={cell.span}
                        onClick={() => !isSaving && toggle(cell.timeslotId, status)}
                        className={`p-1.5 border border-gray-100 h-16 align-middle transition-colors duration-150 select-none
                          ${status === "teaching" ? "bg-gray-200 cursor-not-allowed" : ""}
                          ${status === "unavailable" ? "bg-red-50 hover:bg-red-100 cursor-pointer" : ""}
                          ${status === "free" ? "hover:bg-orange-50 cursor-pointer" : ""}`}
                      >
                        <div className="h-full flex items-center justify-center">
                          {isSaving ? (
                            <Loader2 size={16} className="animate-spin text-gray-400" />
                          ) : status === "teaching" ? (
                            <Lock size={16} className="text-gray-500" strokeWidth={2.5} />
                          ) : status === "unavailable" ? (
                            <X size={20} className="text-red-600" strokeWidth={3} />
                          ) : null}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}