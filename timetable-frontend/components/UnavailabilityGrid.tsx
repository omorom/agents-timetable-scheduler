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

type SlotStatus = "teaching" | "unavailable" | "free";

// ข้อมูลของ slot ที่ "สอนอยู่แล้ว" — ใช้โชว์ชื่อวิชา + ชั้นปี ในช่องแทนไอคอนล็อกเฉยๆ
interface SlotInfo {
  status: SlotStatus;
  sessionId: string | null;
  subjectId: string | null;
  subjectName: string | null;
  groupId: string | null;
  teacherName: string | null;
}

type CellState =
  | { kind: "lunch" }
  | { kind: "covered" }
  | { kind: "slot"; timeslotId: string; span: number; info: SlotInfo };

export default function UnavailabilityGrid({ kind, entityId }: Props) {
  const [timeslots, setTimeslots] = useState<Timeslot[]>([]);
  const [statusMap, setStatusMap] = useState<Map<string, SlotInfo>>(new Map());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [blockedMsg, setBlockedMsg] = useState("");

  const basePath = kind === "teacher" ? "teacher-unavailability" : "room-unavailability";

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [tRes, gRes] = await Promise.all([
        fetch(`${API_BASE}/timeslots`),
        fetch(`${API_BASE}/${basePath}/${entityId}/schedule-grid`),
      ]);
      const [tData, gData] = await Promise.all([tRes.json(), gRes.json()]);

      setTimeslots(Array.isArray(tData) ? tData : []);

      const gList: {
        timeslot_id: string | number;
        status: SlotStatus;
        session_id: string | null;
        subject_id: string | null;
        subject_name: string | null;
        group_id: string | null;
        teacher_name: string | null;
      }[] = Array.isArray(gData) ? gData : [];

      setStatusMap(
        new Map(
          gList.map((g) => [
            String(g.timeslot_id),
            { status: g.status, sessionId: g.session_id, subjectId: g.subject_id, subjectName: g.subject_name, groupId: g.group_id, teacherName: g.teacher_name },
          ])
        )
      );
    } catch {
      setError("ไม่สามารถโหลดข้อมูลได้ กรุณาตรวจสอบการเชื่อมต่อ API");
    } finally {
      setLoading(false);
    }
  }, [basePath, entityId]);

  useEffect(() => { load(); }, [load]);

  async function toggle(timeslotId: string, status: SlotStatus) {
    if (status === "teaching") {
      setBlockedMsg("ช่วงเวลานี้มีสอนอยู่แล้ว ต้องการเปลี่ยนกรุณาไปที่หน้าตารางหลัก");
      window.setTimeout(() => setBlockedMsg(""), 2500);
      return;
    }
    if (saving) return;
    setSaving(timeslotId);
    setError("");

    const wasUnavailable = status === "unavailable";
    setStatusMap((prev) => {
      const next = new Map(prev);
      const cur = next.get(timeslotId);
      next.set(timeslotId, { ...(cur ?? { sessionId: null, subjectId: null, subjectName: null, groupId: null, teacherName: null }), status: wasUnavailable ? "free" : "unavailable" });
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
      setStatusMap((prev) => {
        const next = new Map(prev);
        const cur = next.get(timeslotId);
        next.set(timeslotId, { ...(cur ?? { sessionId: null, subjectId: null, subjectName: null, groupId: null, teacherName: null }), status: wasUnavailable ? "unavailable" : "free" });
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
      const info = statusMap.get(id) ?? { status: "free" as SlotStatus, sessionId: null, subjectId: null, subjectName: null, groupId: null, teacherName: null };
      cells[span.startIdx] = { kind: "slot", timeslotId: id, span: span.span, info };
      for (let i = span.startIdx + 1; i < span.startIdx + span.span; i++) {
        cells[i] = { kind: "covered" };
      }
    }

    // รวมช่องที่ติดกันและเป็น "วิชาเดียวกันจริงๆ" (session/subject ตรงกัน) เข้าเป็นแท่ง
    // เดียว — เพราะ timeslot ในระบบเก็บเป็นก้อนละ 1 ชม. แต่ session จริงกิน 2 ชม.
    // ติดกันเสมอ (1 block) ถ้าไม่รวม จะเห็นเป็น 2 การ์ดแยกทั้งที่เป็นคาบเดียวกัน
    //
    // หมายเหตุ: merge เฉพาะสถานะ "สอนอยู่แล้ว" (teaching) เท่านั้น ส่วนช่อง
    // "ไม่สะดวกสอน/ไม่ว่าง" (unavailable) ตั้งใจไม่ merge เพราะแต่ละ timeslot
    // เป็นการตั้งค่าส่วนตัวแยกช่องของมันเอง ไม่ควรถูกรวมแท่งกับช่องข้างเคียง
    for (let i = 0; i < cells.length; i++) {
      const cell = cells[i];
      if (cell.kind !== "slot") continue;
      let mergedSpan = cell.span;
      let nextIdx = i + cell.span;
      while (nextIdx < cells.length) {
        const nextCell = cells[nextIdx];
        if (nextCell.kind !== "slot") break;
        // merge เฉพาะ session เดียวกันจริงๆ (session_id ตรงกัน) — ไม่ใช่แค่ subject_id
        // ตรงกันเฉยๆ เพราะอาจารย์คนเดียวกันอาจสอนวิชาเดียวกันคนละ section (เช่น LAB-1
        // ตามด้วย LAB-2 คนละกลุ่มนิสิต) ติดกันพอดี ซึ่งไม่ควรถูกรวมเป็นแท่งเดียว
        // fallback: ถ้าทั้งคู่ไม่มี session_id เลย (เช่น GENERAL ที่ล็อกไว้) ใช้ subjectId แทน
        const sameSubject =
          cell.info.status === "teaching" &&
          nextCell.info.status === "teaching" &&
          (cell.info.sessionId && nextCell.info.sessionId
            ? cell.info.sessionId === nextCell.info.sessionId
            : cell.info.subjectId === nextCell.info.subjectId);
        if (!sameSubject) break;
        mergedSpan += nextCell.span;
        for (let k = nextIdx; k < nextIdx + nextCell.span; k++) {
          cells[k] = { kind: "covered" };
        }
        nextIdx += nextCell.span;
      }
      if (mergedSpan !== cell.span) {
        cells[i] = { ...cell, span: mergedSpan };
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
                        <td key={slot} className="p-1.5 border border-gray-100 h-18 align-top bg-slate-50">
                          <div className="h-full flex items-center justify-center">
                            <span className="text-[9px] text-gray-300 font-medium tracking-widest uppercase">พักเที่ยง</span>
                          </div>
                        </td>
                      );
                    }

                    if (cell.kind !== "slot") {
                      return <td key={slot} className="p-1.5 border border-gray-100 h-18 bg-gray-50/40" />;
                    }

                    const isSaving = saving === cell.timeslotId;
                    const { status, subjectId, subjectName, groupId, teacherName } = cell.info;

                    return (
                      <td
                        key={slot}
                        colSpan={cell.span}
                        onClick={() => !isSaving && toggle(cell.timeslotId, status)}
                        title={status === "teaching" && subjectName ? `${subjectName}${teacherName ? ` · ${teacherName}` : ""}` : undefined}
                        className={`p-1.5 border border-gray-100 h-18 align-middle transition-colors duration-150 select-none
                          ${status === "teaching" ? "bg-slate-50/80 cursor-not-allowed" : ""}
                          ${status === "unavailable" ? "bg-red-50 hover:bg-red-100 cursor-pointer" : ""}
                          ${status === "free" ? "hover:bg-orange-50 cursor-pointer" : ""}`}
                      >
                        <div className="h-full flex items-center justify-center">
                          {isSaving ? (
                            <Loader2 size={16} className="animate-spin text-gray-400" />
                          ) : status === "teaching" ? (
                            subjectName ? (
                              <div className="w-full h-full rounded-lg border border-slate-200 bg-slate-100 px-2 py-1.5 flex flex-col justify-center gap-0.5 overflow-hidden">
                                {subjectId && (
                                  <span className="text-[11px] font-bold text-slate-700 font-mono leading-none shrink-0">{subjectId}</span>
                                )}
                                <span className="text-[9px] text-slate-500 leading-tight line-clamp-2">
                                  {subjectName}
                                </span>
                              </div>
                            ) : (
                              <Lock size={16} className="text-gray-400" strokeWidth={2.5} />
                            )
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