"use client";

import { useState, useEffect, useCallback } from "react";
import { Check, Ban } from "lucide-react";
import { Timeslot, DAYS, DAY_TH, DAY_ABBR, API_BASE } from "./types";

interface Props {
  timeslots: Timeslot[];
  selected: Set<string>;
  onToggle: (timeslotId: string) => void;
  /** ถ้ารู้ชั้นปีแล้ว (subjects.group_id ผูกตายตัว หรือเลือก manual มาแค่ 1 ชั้นปี)
   * จะดึง schedule + preferred-timeslots มา grey-out คาบที่ชั้นปีนี้ถูกใช้ไปแล้ว */
  groupId?: string | null;
  /** ตอนแก้ไข record เดิม ไม่ต้องเอา record ของตัวเองมานับว่า "ถูกล็อกไปแล้ว" */
  excludeSubjectSelectedId?: number | null;
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

type CellState =
  | { kind: "lunch" }
  | { kind: "covered" }
  | { kind: "slot"; timeslotId: string; span: number; blocked: boolean };

export default function PreferredTimeslotGrid({
  timeslots,
  selected,
  onToggle,
  groupId,
  excludeSubjectSelectedId,
}: Props) {
  const [blockedByClass, setBlockedByClass] = useState<Set<string>>(new Set());
  const [blockedByOtherGeneral, setBlockedByOtherGeneral] = useState<Set<string>>(new Set());

  const loadBlockedSlots = useCallback(async () => {
    if (!groupId) {
      setBlockedByClass(new Set());
      setBlockedByOtherGeneral(new Set());
      return;
    }
    try {
      const [scheduleRes, preferredRes] = await Promise.all([
        fetch(`${API_BASE}/schedule`),
        fetch(`${API_BASE}/preferred-timeslots`),
      ]);
      const scheduleData: Record<string, { timeslot_id: number }[]> = await scheduleRes.json();
      const preferredData: {
        group_id: string;
        timeslot_id: number;
        subject_selected_id?: number;
      }[] = await preferredRes.json();

      // ชั้นปีนี้มีวิชาอื่นเรียนอยู่แล้วคาบไหนบ้าง (จากตารางที่ AI จัดไปแล้วรอบก่อน)
      const groupSchedule = scheduleData?.[groupId] ?? [];
      setBlockedByClass(new Set(groupSchedule.map((s) => String(s.timeslot_id))));

      // ชั้นปีนี้ถูกวิชา GENERAL อื่น "ล็อก" คาบไหนไปแล้วบ้าง (ไม่นับ record ของตัวเองตอนแก้ไข)
      const lockedByOthers = (Array.isArray(preferredData) ? preferredData : [])
        .filter((p) => p.group_id === groupId)
        .filter((p) => !excludeSubjectSelectedId || p.subject_selected_id !== excludeSubjectSelectedId)
        .map((p) => String(p.timeslot_id));
      setBlockedByOtherGeneral(new Set(lockedByOthers));
    } catch {
      setBlockedByClass(new Set());
      setBlockedByOtherGeneral(new Set());
    }
  }, [groupId, excludeSubjectSelectedId]);

  useEffect(() => { loadBlockedSlots(); }, [loadBlockedSlots]);

  function isBlocked(timeslotId: string) {
    return blockedByClass.has(timeslotId) || blockedByOtherGeneral.has(timeslotId);
  }

  function buildDayCells(day: string): CellState[] {
    const cells: CellState[] = DISPLAY_SLOTS.map((slot) =>
      slot === LUNCH_SLOT ? { kind: "lunch" } : { kind: "covered" }
    );

    for (const t of timeslots.filter((t) => dayOf(t) === day)) {
      const span = findSpan(t.start_time, t.end_time);
      if (!span) continue;
      const id = String(t.timeslot_id);
      cells[span.startIdx] = { kind: "slot", timeslotId: id, span: span.span, blocked: isBlocked(id) };
      for (let i = span.startIdx + 1; i < span.startIdx + span.span; i++) {
        cells[i] = { kind: "covered" };
      }
    }
    return cells;
  }

  return (
    <div>
      <div className="flex items-center gap-4 mb-2 text-[11px] text-gray-400">
        <span className="flex items-center gap-1">
          <span className="w-2.5 h-2.5 rounded-sm bg-green-100 border border-green-300" /> คาบที่มีการจัดการเรียนการสอน
        </span>
        {groupId && (
          <span className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-sm bg-gray-200 border border-gray-300" /> คาบที่มีการจัดการเรียนการสอนไปแล้ว
          </span>
        )}
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

                    if (cell.kind === "lunch") {
                      return (
                        <td key={slot} className="p-1.5 border border-gray-100 h-16 align-top bg-slate-50">
                          <div className="h-full flex items-center justify-center">
                            <span className="text-[9px] text-gray-300 font-medium tracking-widest uppercase">พักเที่ยง</span>
                          </div>
                        </td>
                      );
                    }

                    const isSelected = selected.has(cell.timeslotId);

                    if (cell.blocked) {
                      const reason = blockedByClass.has(cell.timeslotId)
                        ? "ชั้นปีนี้มีวิชาอื่นเรียนอยู่แล้ว"
                        : "คาบนี้ถูกวิชาศึกษาทั่วไปอื่นล็อกไปแล้ว";
                      return (
                        <td
                          key={slot}
                          colSpan={cell.span}
                          className="p-1.5 border border-gray-100 h-16 bg-gray-100 cursor-not-allowed"
                          title={reason}
                        >
                          <div className="h-full flex items-center justify-center">
                            <Ban size={16} className="text-gray-300" />
                          </div>
                        </td>
                      );
                    }

                    return (
                      <td
                        key={slot}
                        colSpan={cell.span}
                        onClick={() => onToggle(cell.timeslotId)}
                        className={`p-1.5 border border-gray-100 h-16 align-middle transition-colors duration-150 cursor-pointer select-none
                          ${isSelected ? "bg-green-100 hover:bg-green-200" : "hover:bg-orange-50"}`}
                      >
                        <div className="h-full flex items-center justify-center">
                          {isSelected && <Check size={20} className="text-green-600" strokeWidth={3} />}
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