"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { Check, Ban, AlertTriangle } from "lucide-react";
import { Timeslot, DAYS, DAY_TH, DAY_ABBR, API_BASE } from "./types";

interface Props {
  timeslots: Timeslot[];
  selected: Set<string>;
  onToggle: (timeslotId: string) => void;
  /** ชั้นปีที่เรียนวิชานี้ (เลือกได้หลายชั้นปี) จะดึง schedule + preferred-timeslots
   * ของทุกชั้นปีมารวมกัน คาบไหนที่ "ชั้นปีใดชั้นปีหนึ่ง" ไม่ว่าง ถือว่าเลือกไม่ได้ */
  groupIds?: string[];
  /** แบบเดิม (ชั้นปีเดียว) ยังใช้ได้ เผื่อหน้าอื่นยังส่ง groupId มาอยู่ */
  groupId?: string | null;
  /** ตอนแก้ไข record เดิม ไม่ต้องเอา record ของตัวเองมานับว่า "ถูกล็อกไปแล้ว" */
  excludeSubjectSelectedId?: number | null;
  /** แปลง group_id เป็นชื่อที่แสดงใน tooltip เช่น "CS ปี 1" (ไม่ส่ง = ใช้ yearShort) */
  labelOf?: (groupId: string) => string;
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

// "Y1" -> "ปี 1"
function yearShort(groupId: string): string {
  const m = groupId.match(/^Y(\d+)$/i);
  return m ? `ปี ${m[1]}` : groupId;
}

// timeslot_id -> ชั้นปีที่ติดคาบนี้ (แยกตามเหตุผล)
type BlockMap = Map<string, Set<string>>;

function addTo(map: BlockMap, timeslotId: string, groupId: string) {
  if (!map.has(timeslotId)) map.set(timeslotId, new Set());
  map.get(timeslotId)!.add(groupId);
}

type CellState =
  | { kind: "lunch" }
  | { kind: "covered" }
  | { kind: "slot"; timeslotId: string; span: number };

export default function PreferredTimeslotGrid({
  timeslots,
  selected,
  onToggle,
  groupIds,
  groupId,
  excludeSubjectSelectedId,
  labelOf,
}: Props) {
  const label = labelOf ?? yearShort;
  // รวม prop ใหม่ (หลายชั้นปี) กับ prop เดิม (ชั้นปีเดียว) ให้เป็น list เดียว
  const groups = useMemo(() => {
    const list = groupIds && groupIds.length > 0 ? groupIds : groupId ? [groupId] : [];
    return Array.from(new Set(list)).sort();
  }, [groupIds, groupId]);
  // ใช้ string เป็น dependency กัน array ใหม่ทุก render ทำให้ fetch วนซ้ำ
  const groupsKey = groups.join(",");

  const [blockedByClass, setBlockedByClass] = useState<BlockMap>(new Map());
  const [blockedByOtherGeneral, setBlockedByOtherGeneral] = useState<BlockMap>(new Map());

  const loadBlockedSlots = useCallback(async () => {
    const targetGroups = groupsKey ? groupsKey.split(",") : [];
    if (targetGroups.length === 0) {
      setBlockedByClass(new Map());
      setBlockedByOtherGeneral(new Map());
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

      // ทุกชั้นปีที่เลือก มีวิชาอื่นเรียนอยู่แล้วคาบไหนบ้าง (จากตารางที่ AI จัดไปแล้ว)
      const byClass: BlockMap = new Map();
      for (const g of targetGroups) {
        const rows = scheduleData?.[g] ?? scheduleData?.[g.toLowerCase()] ?? [];
        for (const s of rows) addTo(byClass, String(s.timeslot_id), g);
      }
      setBlockedByClass(byClass);

      // ทุกชั้นปีที่เลือก ถูกวิชา GENERAL อื่นล็อกคาบไหนไปแล้วบ้าง (ไม่นับ record ของตัวเองตอนแก้ไข)
      const byGeneral: BlockMap = new Map();
      const groupSet = new Set(targetGroups);
      for (const p of Array.isArray(preferredData) ? preferredData : []) {
        if (!groupSet.has(p.group_id)) continue;
        if (excludeSubjectSelectedId && p.subject_selected_id === excludeSubjectSelectedId) continue;
        addTo(byGeneral, String(p.timeslot_id), p.group_id);
      }
      setBlockedByOtherGeneral(byGeneral);
    } catch {
      setBlockedByClass(new Map());
      setBlockedByOtherGeneral(new Map());
    }
  }, [groupsKey, excludeSubjectSelectedId]);

  useEffect(() => { loadBlockedSlots(); }, [loadBlockedSlots]);

  // ชั้นปีที่ติดคาบนี้ (รวมทั้งสองเหตุผล) เรียงตามลำดับชั้นปี
  function blockedGroupsOf(timeslotId: string): string[] {
    const set = new Set<string>([
      ...(blockedByClass.get(timeslotId) ?? []),
      ...(blockedByOtherGeneral.get(timeslotId) ?? []),
    ]);
    return Array.from(set).sort();
  }

  // ข้อความ tooltip แยกรายชั้นปีว่าติดเพราะอะไร
  function reasonOf(timeslotId: string): string {
    return blockedGroupsOf(timeslotId)
      .map((g) => {
        const reasons: string[] = [];
        if (blockedByClass.get(timeslotId)?.has(g)) reasons.push("มีวิชาอื่นเรียนอยู่แล้ว");
        if (blockedByOtherGeneral.get(timeslotId)?.has(g)) reasons.push("ถูกวิชาศึกษาทั่วไปอื่นล็อกไว้");
        return `${label(g)}: ${reasons.join(", ")}`;
      })
      .join("\n");
  }

  function buildDayCells(day: string): CellState[] {
    const cells: CellState[] = DISPLAY_SLOTS.map((slot) =>
      slot === LUNCH_SLOT ? { kind: "lunch" } : { kind: "covered" }
    );

    for (const t of timeslots.filter((t) => dayOf(t) === day)) {
      const span = findSpan(t.start_time, t.end_time);
      if (!span) continue;
      cells[span.startIdx] = { kind: "slot", timeslotId: String(t.timeslot_id), span: span.span };
      for (let i = span.startIdx + 1; i < span.startIdx + span.span; i++) {
        cells[i] = { kind: "covered" };
      }
    }
    return cells;
  }

  return (
    <div>
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
                    const blockedGroups = blockedGroupsOf(cell.timeslotId);
                    const isBlocked = blockedGroups.length > 0;

                    // เลือกไว้แล้ว แต่พอเพิ่มชั้นปีทีหลังกลับชน → เตือนสีแดง และกดเพื่อเอาออกได้
                    if (isBlocked && isSelected) {
                      return (
                        <td
                          key={slot}
                          colSpan={cell.span}
                          onClick={() => onToggle(cell.timeslotId)}
                          className="p-1.5 border border-gray-100 h-16 bg-red-50 hover:bg-red-100 cursor-pointer select-none transition-colors"
                          title={`${reasonOf(cell.timeslotId)}\nคลิกเพื่อเอาคาบนี้ออก`}
                        >
                          <div className="h-full flex flex-col items-center justify-center gap-0.5">
                            <AlertTriangle size={15} className="text-red-500" />
                            <span className="text-[9px] font-semibold text-red-500 leading-none">ชน</span>
                          </div>
                        </td>
                      );
                    }

                    if (isBlocked) {
                      return (
                        <td
                          key={slot}
                          colSpan={cell.span}
                          className="p-1.5 border border-gray-100 h-16 bg-gray-100 cursor-not-allowed"
                          title={reasonOf(cell.timeslotId)}
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