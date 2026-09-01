"use client";

import { useState, useEffect } from "react";
import { GripVertical, Lock, Check, X, Loader2, Plus, ZoomIn } from "lucide-react";
import { ScheduleItem, ExistingItem, Timeslot, DAYS, DAY_TH, DAY_ABBR, getColor, API_BASE } from "./types";
import EditScheduleModal from "./EditScheduleModal";

export interface PreferredItem {
  subject_id: string;
  subject_name: string;
  subject_name_english?: string;
  description_thai?: string;
  description_english?: string;
  subject_type?: string;
  semester?: number;
  subject_selected_id: number;
  group_id: string;
  timeslot_id: number;
  day: string;
  start_time: string;
  end_time: string;
}

interface Props {
  items: ScheduleItem[];
  existing: ExistingItem[];
  preferred?: PreferredItem[];
  year: string;
  groupName?: string;
  timeslots: Timeslot[];
  onRefresh?: () => void;
  theme?: "orange" | "purple"; // สีหัวตาราง: orange = CS (ค่าเริ่มต้น), purple = IT
}

interface DropTarget {
  day: string;
  slotIndex: number;
  slot: string;
  timeslotId: string;
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

function blockLabelOf(startTime: string, endTime: string): string {
  const span = findSpan(startTime, endTime);
  if (!span) return `${startTime}-${endTime}`;
  const startLabel = DISPLAY_SLOTS[span.startIdx].split("-")[0];
  const endLabel = DISPLAY_SLOTS[span.startIdx + span.span - 1].split("-")[1];
  return `${startLabel}-${endLabel}`;
}

type CellState =
  | { kind: "empty"; span: number }
  | { kind: "lunch" }
  | { kind: "covered" }
  | { kind: "item"; items: ScheduleItem[]; span: number }
  | { kind: "locked"; item: ExistingItem; span: number };

function place(cells: CellState[], startIdx: number, span: number, cell: CellState, onlyIfEmpty: boolean) {
  if (onlyIfEmpty && cells[startIdx].kind !== "empty") return;
  cells[startIdx] = cell;
  for (let i = startIdx + 1; i < startIdx + span; i++) {
    if (!onlyIfEmpty || cells[i].kind === "empty") cells[i] = { kind: "covered" };
  }
}

function placeItem(cells: CellState[], startIdx: number, span: number, item: ScheduleItem) {
  const existing = cells[startIdx];
  if (existing.kind === "item") {
    existing.items.push(item);
    return;
  }
  cells[startIdx] = { kind: "item", items: [item], span };
  for (let i = startIdx + 1; i < startIdx + span; i++) {
    cells[i] = { kind: "covered" };
  }
}

function Toast({ toast }: { toast: { msg: string; type: "error" | "success" } | null }) {
  if (!toast) return null;
  return (
    <div
      className={`fixed top-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2.5 pl-3 pr-4 py-2.5
        bg-white rounded-lg shadow-md border-l-[3px] animate-fade-up
        ${toast.type === "error" ? "border-red-500" : "border-emerald-500"}`}
    >
      {toast.type === "success" ? (
        <Check size={15} className="text-emerald-500 shrink-0" strokeWidth={2.5} />
      ) : (
        <X size={15} className="text-red-500 shrink-0" strokeWidth={2.5} />
      )}
      <span className="text-[13px] font-medium text-gray-700">{toast.msg}</span>
    </div>
  );
}

function ConfirmMoveModal({
  pendingItem,
  dropTarget,
  loading,
  onCancel,
  onConfirm,
}: {
  pendingItem: ScheduleItem;
  dropTarget: DropTarget;
  loading: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    // z-[60] ไม่ใช่ z-50 เหมือนตัวอื่น — ต้องสูงกว่า modal "ขยายตาราง" (expanded)
    // เพราะตอนกดขยายตารางแล้วลากย้ายวิชาข้างใน modal นั้น ConfirmMoveModal ต้อง
    // ลอยทับอยู่บนสุดเสมอ ไม่งั้นจะโดน modal ขยาย (ซึ่ง render ทีหลังใน JSX แต่
    // z-index เท่ากัน) บังไว้ข้างหลัง กดอะไรไม่ได้เพราะมองไม่เห็น
    <div className="fixed inset-0 bg-black/30 backdrop-blur-[2px] z-[60] flex items-center justify-center animate-fade-up">
      <div className="bg-white rounded-2xl shadow-2xl p-6 w-96 mx-4">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h3 className="text-[15px] font-bold text-gray-900">ยืนยันการย้ายวิชา</h3>
            <p className="text-xs text-gray-400 mt-0.5">โปรดตรวจสอบข้อมูลก่อนดำเนินการ</p>
          </div>
          <button onClick={onCancel} className="text-gray-300 hover:text-gray-500 transition-colors cursor-pointer">
            <X size={18} />
          </button>
        </div>

        <div className="bg-slate-50 rounded-xl p-4 mb-4 space-y-3 text-sm border border-slate-100">
          <div className="flex items-start justify-between gap-2">
            <span className="text-gray-400 shrink-0">วิชา</span>
            <span className="font-semibold text-gray-800 text-right">{pendingItem.subject_name}</span>
          </div>
          <div className="border-t border-slate-200" />
          <div className="flex items-center justify-between">
            <span className="text-gray-400">เวลาเดิม</span>
            <span className="text-gray-600 text-[13px]">
              {DAY_TH[dayOf(pendingItem)] ?? pendingItem.day} {blockLabelOf(pendingItem.start_time, pendingItem.end_time)}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-gray-400">เวลาใหม่</span>
            <span className="font-semibold text-orange-600 text-[13px]">
              {DAY_TH[dropTarget.day] ?? dropTarget.day} {dropTarget.slot}
            </span>
          </div>
        </div>

        <div className="flex gap-2.5">
          <button
            onClick={onCancel}
            className="flex-1 py-2.5 rounded-xl border border-gray-200 text-gray-600 text-sm font-semibold hover:bg-gray-50 cursor-pointer transition-colors"
          >
            ยกเลิก
          </button>
          <button
            onClick={onConfirm}
            disabled={loading}
            className="flex-1 py-2.5 rounded-xl bg-orange-500 hover:bg-orange-600 text-white text-sm font-semibold cursor-pointer disabled:bg-orange-200 transition-colors flex items-center justify-center gap-1.5"
          >
            {loading ? <><Loader2 size={14} className="animate-spin" /> กำลังย้าย...</> : "ตกลง"}
          </button>
        </div>
      </div>
    </div>
  );
}

function MergedItemCard({
  items,
  groupId,
  dragging,
  large,
  onDragStart,
  onDragEnd,
  onClickItem,
}: {
  items: ScheduleItem[];
  groupId: string;
  dragging: (item: ScheduleItem) => boolean;
  large?: boolean;
  onDragStart: (item: ScheduleItem) => void;
  onDragEnd: () => void;
  onClickItem: (item: ScheduleItem) => void;
}) {
  const first = items[0];
  const color = getColor(first.subject_id, groupId);
  const anyDragging = items.some((it) => dragging(it));

  return (
    <div
      style={{ backgroundColor: color.bg }}
      className={`h-full select-none overflow-hidden flex flex-col justify-center
        transition-all duration-150 ${anyDragging ? "opacity-40 scale-95" : "hover:brightness-95"}`}
    >
      <div className={large ? "px-2 pt-1 pb-0.5 shrink-0" : "px-1.5 pt-0.5 pb-0.5 shrink-0"}>
        <div style={{ color: color.text }} className={`font-extrabold leading-tight truncate ${large ? "text-[13px]" : "text-[12.5px]"}`}>
          {first.subject_id}
        </div>
        <div className={`text-gray-500 leading-tight truncate ${large ? "text-[10px]" : "text-[9px]"}`}>
          {first.subject_name}
        </div>
      </div>

      <div className="flex min-h-0">
        {items.map((it) => (
          <div
            key={it.session_id}
            draggable
            onDragStart={() => onDragStart(it)}
            onDragEnd={onDragEnd}
            onClick={() => onClickItem(it)}
            className={`flex-1 min-w-0 cursor-pointer active:cursor-grabbing hover:bg-black/5 transition-colors
              flex items-center justify-start text-left ${large ? "px-2 py-1" : "px-1.5 py-0"} ${dragging(it) ? "opacity-40" : ""}`}
          >
            <span className={`truncate ${large ? "text-[10.5px]" : "text-[8.5px]"}`}>
              <span className="text-gray-400 font-medium uppercase tracking-wide">{it.session_type || "LEC"}</span>
              {it.room_id && (
                <span className="font-semibold text-gray-600"> · {it.room_id}</span>
              )}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ItemCard({
  item,
  span,
  groupId,
  dragging,
  isCompact,
  large,
  onDragStart,
  onDragEnd,
  onClick,
}: {
  item: ScheduleItem;
  span: number;
  groupId: string;
  dragging: boolean;
  isCompact?: boolean;
  large?: boolean;
  onDragStart: () => void;
  onDragEnd: () => void;
  onClick: () => void;
}) {
  const color = getColor(item.subject_id, groupId);

  return (
    <div
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onClick={onClick}
      style={{ backgroundColor: color.bg }}
      className={`h-full select-none min-w-0 flex flex-col justify-center
        transition-all duration-150 group relative cursor-pointer active:cursor-grabbing
        ${large ? "px-2 py-1" : isCompact ? "px-1.5 py-0.5" : "px-1.5 py-1"}
        ${dragging ? "opacity-40 scale-95" : "hover:brightness-95"}`}
    >
      <span className="absolute top-1 right-1 opacity-0 group-hover:opacity-50 transition-opacity">
        <GripVertical size={large ? 14 : 11} className="text-gray-500" />
      </span>
      <div
        style={{ color: color.text }}
        className={`font-extrabold leading-tight truncate pr-3 ${large ? "text-[13px]" : "text-[12.5px]"}`}
      >
        {item.subject_id}
      </div>
      <div className={`text-gray-500 leading-tight truncate mt-0.5 ${large ? "text-[10px]" : "text-[9px]"}`}>
        {item.subject_name}
      </div>
      <div className={`text-gray-400 font-medium uppercase tracking-wide leading-none truncate ${large ? "text-[9.5px] mt-1" : "text-[8px] mt-0.5"}`}>
        {item.session_type || "LEC"}
        {item.room_id && <span className="normal-case"> · {item.room_id}</span>}
      </div>
    </div>
  );
}

function LockedCard({ item }: { item: ExistingItem }) {
  return (
    <div className="bg-slate-100 border border-dashed border-slate-300 rounded-lg px-2 py-1 h-full flex flex-col justify-between">
      <div className="flex items-start justify-between gap-1">
        <div className="text-slate-500 text-[10px] font-semibold leading-tight truncate flex-1">
          {item.subject_name || "ไม่ว่าง"}
        </div>
        <Lock size={10} className="text-slate-400 shrink-0 mt-0.5" />
      </div>
      {(item.teacher_name || item.room_id) && (
        <div className="text-slate-400 text-[8px] truncate">
          {[item.teacher_name, item.room_id].filter(Boolean).join(" · ")}
        </div>
      )}
    </div>
  );
}

function PreferredCard({
  subjectIds,
  onClick,
}: {
  subjectIds: PreferredItem[];
  onClick?: () => void;
}) {
  return (
    <div
      onClick={onClick}
      className={`bg-gray-100 px-1.5 py-1 h-full flex flex-col items-start justify-start gap-0 overflow-hidden text-left
        ${onClick ? "cursor-pointer hover:bg-gray-150 transition-colors" : ""}`}
      title={subjectIds.map((s) => s.subject_name).join(", ")}
    >
      <div className="text-gray-400 shrink-0 w-full">
        <span className="text-[7.5px] font-bold uppercase tracking-wide block truncate">ศึกษาทั่วไป</span>
      </div>
      {subjectIds.slice(0, 2).map((s) => (
        <div key={s.subject_id} className="text-[9px] font-semibold text-gray-600 truncate leading-tight w-full mt-0.5">
          {s.subject_name}
        </div>
      ))}
      {subjectIds.length > 2 && (
        <div className="text-[8px] text-gray-400 shrink-0">+{subjectIds.length - 2} วิชา</div>
      )}
    </div>
  );
}

const TYPE_LABEL: Record<string, string> = {
  GENERAL: "ศึกษาทั่วไป",
  CORE: "วิชาแกน",
  ELECTIVE: "วิชาเลือก",
};

function SubjectDetailModal({ subjects, onClose }: { subjects: PreferredItem[]; onClose: () => void }) {
  return (
    <div
      // z-[60] เหมือน ConfirmMoveModal — เปิดจากข้างในตารางขยายได้เหมือนกัน
      // (คลิกการ์ด "ศึกษาทั่วไป" ตอนตารางขยายอยู่) ต้องลอยทับ modal ขยายเสมอ
      className="fixed inset-0 bg-black/30 backdrop-blur-[2px] z-[60] flex items-center justify-center animate-fade-up p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between px-6 pt-5 pb-4 border-b border-gray-100 sticky top-0 bg-white">
          <h3 className="text-[15px] font-bold text-gray-900">รายละเอียดวิชา</h3>
          <button onClick={onClose} className="text-gray-300 hover:text-gray-500 transition-colors cursor-pointer">
            <X size={18} />
          </button>
        </div>

        <div className="px-6 py-4 space-y-5">
          {subjects.map((s) => (
            <div key={s.subject_id} className="pb-5 border-b border-gray-50 last:border-0 last:pb-0">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-[13px] font-mono text-gray-400">{s.subject_id}</span>
                {s.subject_type && (
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-purple-50 text-purple-600">
                    {TYPE_LABEL[s.subject_type] ?? s.subject_type}
                  </span>
                )}
                {s.semester != null && (
                  <span className="text-[10px] text-gray-400">ภาคเรียนที่ {s.semester}</span>
                )}
              </div>
              <p className="text-[15px] font-bold text-gray-900 mb-0.5">{s.subject_name}</p>
              {s.subject_name_english && (
                <p className="text-[13px] text-gray-400 mb-2">{s.subject_name_english}</p>
              )}
              {s.description_thai && (
                <p className="text-[13px] text-gray-600 leading-relaxed">{s.description_thai}</p>
              )}
              {s.description_english && (
                <p className="text-[12px] text-gray-400 leading-relaxed mt-1.5">{s.description_english}</p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

const HEADER_THEME: Record<"orange" | "purple", { gradient: string; lunchBg: string; accent: string; dropBg: string; dropBorder: string; divider: string }> = {
  orange: {
    gradient: "bg-linear-to-r from-orange-500 to-orange-400",
    lunchBg: "bg-orange-300/70",
    accent: "bg-orange-500",
    dropBg: "bg-orange-50/40",
    dropBorder: "border-orange-300",
    divider: "border-orange-400/40",
  },
  purple: {
    gradient: "bg-linear-to-r from-purple-600 to-purple-500",
    lunchBg: "bg-purple-400/70",
    accent: "bg-purple-600",
    dropBg: "bg-purple-50/40",
    dropBorder: "border-purple-400",
    divider: "border-purple-500/40",
  },
};

export default function ScheduleGrid({ items, existing, preferred = [], year, groupName, timeslots, onRefresh, theme = "orange" }: Props) {
  const t = HEADER_THEME[theme];
  const [dragging, setDragging] = useState<ScheduleItem | null>(null);
  const [pendingItem, setPendingItem] = useState<ScheduleItem | null>(null);
  const [dropTarget, setDropTarget] = useState<DropTarget | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: "error" | "success" } | null>(null);
  const [loading, setLoading] = useState(false);
  const [viewingSubjects, setViewingSubjects] = useState<PreferredItem[] | null>(null);
  const [editingItem, setEditingItem] = useState<ScheduleItem | null>(null);
  const [expanded, setExpanded] = useState(false);

  const slotToId: Record<string, string> = {};
  for (const t of timeslots) {
    const startHour = hourOf(t.start_time);
    const endHour = hourOf(t.end_time);
    DISPLAY_SLOTS.forEach((slot, idx) => {
      if (hourOf(slot) >= startHour && hourOf(slot) < endHour) {
        slotToId[`${dayOf(t)}-${idx}`] = String(t.timeslot_id);
      }
    });
  }

  useEffect(() => {
    function forceReset() {
      setDragging(null);
    }
    window.addEventListener("dragend", forceReset);
    window.addEventListener("drop", forceReset);
    return () => {
      window.removeEventListener("dragend", forceReset);
      window.removeEventListener("drop", forceReset);
    };
  }, []);

  function buildPreferredSlotSubjects(day: string): Record<number, PreferredItem[]> {
    const slotSubjects: Record<number, PreferredItem[]> = {};
    for (const p of preferred.filter((p) => p.group_id === year && dayOf(p) === day)) {
      const span = findSpan(p.start_time, p.end_time);
      if (!span) continue;
      for (let i = span.startIdx; i < span.startIdx + span.span; i++) {
        if (!slotSubjects[i]) slotSubjects[i] = [];
        slotSubjects[i].push(p);
      }
    }
    return slotSubjects;
  }

  function buildPreferredSpans(day: string): {
    spans: Record<number, { subjects: PreferredItem[]; span: number }>;
    covered: Set<number>;
    occupied: Set<number>;
  } {
    const slotSubjects = buildPreferredSlotSubjects(day);
    const spans: Record<number, { subjects: { subject_id: string; subject_name: string }[]; span: number }> = {};
    const covered = new Set<number>();
    const occupied = new Set<number>(Object.keys(slotSubjects).map(Number));
    const key = (list: { subject_id: string }[]) => list.map((s) => s.subject_id).sort().join(",");

    const indices = Object.keys(slotSubjects).map(Number).sort((a, b) => a - b);
    for (const idx of indices) {
      if (covered.has(idx)) continue;
      const subjectsHere = slotSubjects[idx];
      const thisKey = key(subjectsHere);
      let span = 1;
      while (slotSubjects[idx + span] && key(slotSubjects[idx + span]) === thisKey) {
        covered.add(idx + span);
        span++;
      }
      spans[idx] = { subjects: subjectsHere, span };
    }
    return { spans, covered, occupied };
  }

  function buildDayCells(day: string, preferredOccupied: Set<number>): CellState[] {
    const cells: CellState[] = DISPLAY_SLOTS.map((slot) =>
      slot === LUNCH_SLOT ? { kind: "lunch" } : { kind: "empty", span: 1 }
    );

    for (const item of items.filter((it) => dayOf(it) === day)) {
      const span = findSpan(item.start_time, item.end_time);
      if (span) placeItem(cells, span.startIdx, span.span, item);
    }

    for (const ex of existing.filter((e) => e.group_id === year && dayOf(e) === day)) {
      const span = findSpan(ex.start_time, ex.end_time);
      if (span) place(cells, span.startIdx, span.span, { kind: "locked", item: ex, span: span.span }, true);
    }

    const blockGroups = new Map<number, number[]>();
    for (const t of timeslots.filter((t) => dayOf(t) === day)) {
      const idx = DISPLAY_SLOTS.findIndex((s) => hourOf(s) === hourOf(t.start_time));
      if (idx === -1) continue;
      if (!blockGroups.has(t.block_id)) blockGroups.set(t.block_id, []);
      blockGroups.get(t.block_id)!.push(idx);
    }
    for (const indices of blockGroups.values()) {
      if (indices.length < 2) continue;
      const sortedIdx = [...indices].sort((a, b) => a - b);
      if (sortedIdx.some((i) => DISPLAY_SLOTS[i] === LUNCH_SLOT)) continue;
      if (sortedIdx.some((i) => preferredOccupied.has(i))) continue;
      place(cells, sortedIdx[0], sortedIdx.length, { kind: "empty", span: sortedIdx.length }, true);
    }

    return cells;
  }

  function showToast(msg: string, type: "error" | "success") {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3000);
  }

  function handleDrop(day: string, slotIndex: number) {
    const slot = DISPLAY_SLOTS[slotIndex];
    const timeslotId = slotToId[`${day}-${slotIndex}`];
    if (!dragging || slot === LUNCH_SLOT || !timeslotId) return;

    const isSameSlot = dayOf(dragging) === day && hourOf(dragging.start_time) === hourOf(slot);
    setDragging(null);
    if (isSameSlot) return;

    const durationHours = hourOf(dragging.end_time) - hourOf(dragging.start_time);
    const startHour = hourOf(slot);
    const fullSlotLabel = `${pad(startHour)}:00-${pad(startHour + durationHours - 1)}:50`;

    setPendingItem(dragging);
    setDropTarget({ day, slotIndex, slot: fullSlotLabel, timeslotId });
    setConfirmOpen(true);
  }

  async function confirmMove() {
    if (!pendingItem || !dropTarget) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/move`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: pendingItem.session_id, timeslot_id: dropTarget.timeslotId }),
      });

      if (!res.ok) {
        showToast("ย้ายไม่สำเร็จ", "error");
      } else {
        showToast("ย้ายสำเร็จแล้ว", "success");
        onRefresh?.();
      }
    } catch {
      showToast("ย้ายไม่สำเร็จ", "error");
    } finally {
      setLoading(false);
      setConfirmOpen(false);
      setDropTarget(null);
      setPendingItem(null);
    }
  }

  function cancelMove() {
    setConfirmOpen(false);
    setDropTarget(null);
    setDragging(null);
    setPendingItem(null);
  }

  function renderTable(large: boolean = false) {
    return (
      <div className="border border-gray-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className={`w-full border-collapse table-fixed ${large ? "min-w-160" : ""}`}>
            <thead>
              <tr>
                <th className={`${t.gradient} text-white text-left font-semibold whitespace-nowrap
                  ${large ? "px-4 py-3 text-xs w-27.5 min-w-27.5" : "px-2 py-2 text-[12px] w-20"}`}>
                  วัน/เวลา
                </th>
                {DISPLAY_SLOTS.map((slot) => (
                  <th
                    key={slot}
                    className={`text-white text-center font-semibold border-l ${t.divider} whitespace-nowrap
                      ${large ? "px-2 py-3 text-[11px] min-w-24" : "px-0.5 py-2 text-[9px]"}
                      ${slot === LUNCH_SLOT ? t.lunchBg : t.gradient}`}
                  >
                    {slot}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {DAYS.map((day, di) => (
                <tr key={day} className="bg-white">
                  <td className={`border-b border-gray-200 border-r border-r-gray-200 ${large ? "px-4 py-2" : "px-2 py-1.5"}`}>
                    <div className={`font-bold text-gray-800 ${large ? "text-[14px]" : "text-[12px]"}`}>{DAY_TH[day]}</div>
                    <div className={`text-gray-400 font-medium ${large ? "text-[10px]" : "text-[8.5px]"}`}>{day}</div>
                  </td>

                  {(() => {
                    const { spans: preferredSpans, covered: preferredCovered, occupied: preferredOccupied } = buildPreferredSpans(day);
                    return buildDayCells(day, preferredOccupied).map((cell, i) => {
                      if (cell.kind === "covered") return null;
                      if (cell.kind === "empty" && preferredCovered.has(i)) return null;

                      const slot = DISPLAY_SLOTS[i];
                      const isLunch = cell.kind === "lunch";
                      const preferredHere = cell.kind === "empty" ? preferredSpans[i] : undefined;
                      const isDroppable = !!dragging && cell.kind === "empty" && !preferredHere && !!slotToId[`${day}-${i}`];
                      const span = preferredHere ? preferredHere.span : "span" in cell ? cell.span : 1;

                      return (
                        <td
                          key={slot}
                          colSpan={span}
                          className={`relative border border-gray-200 align-top transition-colors duration-150
    ${large ? "h-18" : "h-14"}
    ${isLunch ? "bg-slate-50" : ""}
    ${isDroppable ? t.dropBg : ""}`}
                          onDragOver={(e) => !isLunch && e.preventDefault()}
                          onDrop={() => handleDrop(day, i)}
                        >
                          {cell.kind === "empty" && !preferredHere && !isDroppable && !isLunch && span > 1 &&
                            Array.from({ length: span - 1 }).map((_, di2) => (
                              <div
                                key={di2}
                                className="absolute top-0 bottom-0 w-px bg-gray-200 pointer-events-none"
                                style={{ left: `${((di2 + 1) / span) * 100}%` }}
                              />
                            ))}

                          {isLunch && (
                            <div className="h-full flex items-center justify-center">
                              <span className={`text-gray-300 font-medium tracking-widest uppercase ${large ? "text-[9px]" : "text-[7.5px]"}`}>พักเที่ยง</span>
                            </div>
                          )}

                          {cell.kind === "empty" && isDroppable && (
                            <div className={`h-full flex items-center justify-center rounded-md ${theme === "purple" ? "bg-purple-100/70" : "bg-orange-100/70"} transition-colors duration-150`}>
                              <Plus size={large ? 16 : 13} className={theme === "purple" ? "text-purple-500" : "text-orange-500"} strokeWidth={2.25} />
                            </div>
                          )}

                          {cell.kind === "empty" && preferredHere && (
                            <PreferredCard
                              subjectIds={preferredHere.subjects}
                              onClick={() => setViewingSubjects(preferredHere.subjects)}
                            />
                          )}

                          {cell.kind === "item" && (() => {
                            const sameSubject = cell.items.every((it) => it.subject_id === cell.items[0].subject_id);
                            if (cell.items.length > 1 && sameSubject) {
                              return (
                                <MergedItemCard
                                  items={cell.items}
                                  groupId={year}
                                  large={large}
                                  dragging={(it) =>
                                    dragging?.session_id === it.session_id || pendingItem?.session_id === it.session_id
                                  }
                                  onDragStart={(it) => setDragging(it)}
                                  onDragEnd={() => setDragging(null)}
                                  onClickItem={(it) => setEditingItem(it)}
                                />
                              );
                            }
                            return (
                              <div className="h-full flex gap-1">
                                {cell.items.map((it) => (
                                  <div key={it.session_id} className="flex-1 min-w-0 h-full">
                                    <ItemCard
                                      item={it}
                                      span={cell.span}
                                      groupId={year}
                                      isCompact={cell.items.length > 1}
                                      large={large}
                                      dragging={
                                        dragging?.session_id === it.session_id ||
                                        pendingItem?.session_id === it.session_id
                                      }
                                      onDragStart={() => setDragging(it)}
                                      onDragEnd={() => setDragging(null)}
                                      onClick={() => setEditingItem(it)}
                                    />
                                  </div>
                                ))}
                              </div>
                            );
                          })()}

                          {cell.kind === "locked" && <LockedCard item={cell.item} />}
                        </td>
                      );
                    });
                  })()}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  return (
    <div className="mb-2 relative">
      <Toast toast={toast} />

      {confirmOpen && pendingItem && dropTarget && (
        <ConfirmMoveModal
          pendingItem={pendingItem}
          dropTarget={dropTarget}
          loading={loading}
          onCancel={cancelMove}
          onConfirm={confirmMove}
        />
      )}

      {expanded && (
        <div
          className="fixed inset-0 bg-black/50 backdrop-blur-[2px] z-50 flex items-center justify-center p-4 animate-fade-up"
          onClick={() => setExpanded(false)}
        >
          <div
            className="bg-white rounded-2xl shadow-2xl w-full max-w-6xl max-h-[90vh] flex flex-col overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 shrink-0">
              <div className="flex items-center gap-3">
                <div className={`w-1 h-5 ${t.accent} rounded-full`} />
                <h2 className="text-[16px] font-bold text-gray-900">
                  ตารางเรียน{groupName ? groupName : `ชั้นปีที่ ${year === "Y1" ? "1" : "2"}`}
                </h2>
              </div>
              <button
                onClick={() => setExpanded(false)}
                className="text-gray-300 hover:text-gray-500 transition-colors cursor-pointer"
              >
                <X size={20} />
              </button>
            </div>
            <div className="p-6 overflow-auto">
              {renderTable(true)}
            </div>
          </div>
        </div>
      )}

      {viewingSubjects && (
        <SubjectDetailModal subjects={viewingSubjects} onClose={() => setViewingSubjects(null)} />
      )}

      {editingItem && (
        <EditScheduleModal
          item={editingItem}
          onClose={() => setEditingItem(null)}
          onSaved={() => {
            showToast("บันทึกการแก้ไขสำเร็จ", "success");
            onRefresh?.();
          }}
        />
      )}

      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className={`w-1 h-5 ${t.accent} rounded-full`} />
          <h2 className="text-[15px] font-bold text-gray-900">
            ตารางเรียน{groupName ? groupName : `ชั้นปีที่ ${year === "Y1" ? "1" : "2"}`}
          </h2>
        </div>
        <button
          onClick={() => setExpanded(true)}
          title="ขยายตาราง"
          className="flex items-center justify-center w-7 h-7 rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors cursor-pointer"
        >
          <ZoomIn size={15} />
        </button>
      </div>

      {renderTable()}
    </div>
  );
}