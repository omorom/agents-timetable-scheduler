"use client";

// ตารางเรียนของ 1 กลุ่มนิสิต — วาดกริด + จัดการลากย้าย/สลับวิชา
// การ์ดในช่องอยู่ที่ ScheduleCards.tsx, หน้าต่างยืนยัน/รายละเอียดอยู่ที่ ScheduleModals.tsx,
// ค่าคงที่และฟังก์ชันช่วยอยู่ที่ scheduleGridUtils.ts
import { useState, useEffect } from "react";
import { X, Plus, ZoomIn, ArrowLeftRight } from "lucide-react";
import { ScheduleItem, ExistingItem, Timeslot, DAYS, DAY_TH, API_BASE } from "./types";
import EditScheduleModal from "./EditScheduleModal";
import { MergedItemCard, ItemCard, LockedCard, PreferredCard } from "./ScheduleCards";
import { Toast, ConfirmMoveModal, ConfirmSwapModal, SubjectDetailModal } from "./ScheduleModals";
import {
  PreferredItem,
  DropTarget,
  LUNCH_SLOT,
  DISPLAY_SLOTS,
  HEADER_THEME,
  pad,
  hourOf,
  dayOf,
  findSpan,
} from "./scheduleGridUtils";

// ไฟล์อื่น (เช่น page.tsx) import PreferredItem จากไฟล์นี้อยู่ — export ต่อไว้ให้ไม่ต้องแก้ที่อื่น
export type { PreferredItem } from "./scheduleGridUtils";

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

// อ่าน error message จาก response ของ backend (detail) ถ้า parse ไม่ได้ใช้ fallback
async function errorMessageOf(res: Response, fallback: string): Promise<string> {
  try {
    const data = await res.json();
    return data?.detail || fallback;
  } catch {
    return fallback;
  }
}

export default function ScheduleGrid({ items, existing, preferred = [], year, groupName, timeslots, onRefresh, theme = "orange" }: Props) {
  const t = HEADER_THEME[theme];
  const [dragging, setDragging] = useState<ScheduleItem | null>(null);
  // ช่องที่เมาส์ลากผ่านอยู่ตอนนี้ (key = "วัน-index") ใช้ไฮไลต์เฉพาะช่องนั้น
  const [dragOverKey, setDragOverKey] = useState<string | null>(null);
  const [toast, setToast] = useState<{ msg: string; type: "error" | "success" } | null>(null);
  const [viewingSubjects, setViewingSubjects] = useState<PreferredItem[] | null>(null);
  const [editingItem, setEditingItem] = useState<ScheduleItem | null>(null);
  const [expanded, setExpanded] = useState(false);

  // ย้ายวิชาไปช่องว่าง
  const [pendingItem, setPendingItem] = useState<ScheduleItem | null>(null);
  const [dropTarget, setDropTarget] = useState<DropTarget | null>(null);
  const [moveLoading, setMoveLoading] = useState(false);
  const [moveError, setMoveError] = useState<string | null>(null);

  // สลับวิชา: a = วิชาที่ลาก, b = วิชาที่ถูกวางทับ
  const [pendingSwap, setPendingSwap] = useState<{ a: ScheduleItem; b: ScheduleItem } | null>(null);
  const [swapLoading, setSwapLoading] = useState(false);
  const [swapError, setSwapError] = useState<string | null>(null);

  const slotToId: Record<string, string> = {};
  for (const ts of timeslots) {
    const startHour = hourOf(ts.start_time);
    const endHour = hourOf(ts.end_time);
    DISPLAY_SLOTS.forEach((slot, idx) => {
      if (hourOf(slot) >= startHour && hourOf(slot) < endHour) {
        slotToId[`${dayOf(ts)}-${idx}`] = String(ts.timeslot_id);
      }
    });
  }

  useEffect(() => {
    function forceReset() {
      setDragging(null);
      setDragOverKey(null);
    }
    window.addEventListener("dragend", forceReset);
    window.addEventListener("drop", forceReset);
    return () => {
      window.removeEventListener("dragend", forceReset);
      window.removeEventListener("drop", forceReset);
    };
  }, []);

  // ─── สร้างช่องของแต่ละวัน ─────────────────────────────────────

  function buildPreferredSpans(day: string): {
    spans: Record<number, { subjects: PreferredItem[]; span: number }>;
    covered: Set<number>;
    occupied: Set<number>;
  } {
    const slotSubjects: Record<number, PreferredItem[]> = {};
    for (const p of preferred.filter((p) => p.group_id === year && dayOf(p) === day)) {
      const span = findSpan(p.start_time, p.end_time);
      if (!span) continue;
      for (let i = span.startIdx; i < span.startIdx + span.span; i++) {
        (slotSubjects[i] ??= []).push(p);
      }
    }

    const spans: Record<number, { subjects: PreferredItem[]; span: number }> = {};
    const covered = new Set<number>();
    const occupied = new Set<number>(Object.keys(slotSubjects).map(Number));
    const key = (list: { subject_id: string }[]) => list.map((s) => s.subject_id).sort().join(",");

    for (const idx of Object.keys(slotSubjects).map(Number).sort((a, b) => a - b)) {
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
    for (const ts of timeslots.filter((ts) => dayOf(ts) === day)) {
      const idx = DISPLAY_SLOTS.findIndex((s) => hourOf(s) === hourOf(ts.start_time));
      if (idx === -1) continue;
      if (!blockGroups.has(ts.block_id)) blockGroups.set(ts.block_id, []);
      blockGroups.get(ts.block_id)!.push(idx);
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

  // ─── ย้ายวิชาไปช่องว่าง ─────────────────────────────────────

  function handleDrop(day: string, slotIndex: number) {
    setDragOverKey(null);
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
    setMoveError(null);
  }

  async function confirmMove() {
    if (!pendingItem || !dropTarget) return;
    setMoveLoading(true);
    setMoveError(null);
    try {
      const res = await fetch(`${API_BASE}/move`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: pendingItem.session_id, timeslot_id: dropTarget.timeslotId }),
      });
      if (!res.ok) {
        // ไม่ปิดหน้าต่าง — แสดงเหตุผลในหน้าต่างเดิม ผู้ใช้เห็นบริบทตรงจุดที่เพิ่งกดยืนยัน
        setMoveError(await errorMessageOf(res, "ย้ายไม่สำเร็จ"));
        return;
      }
      showToast("ย้ายสำเร็จแล้ว", "success");
      onRefresh?.();
      cancelMove();
    } catch {
      setMoveError("ย้ายไม่สำเร็จ (เชื่อมต่อ server ไม่ได้)");
    } finally {
      setMoveLoading(false);
    }
  }

  function cancelMove() {
    setDropTarget(null);
    setDragging(null);
    setDragOverKey(null);
    setPendingItem(null);
    setMoveError(null);
  }

  // ─── สลับวิชา (วางทับวิชาอื่น) ─────────────────────────────────

  function handleSwapDrop(target: ScheduleItem) {
    const source = dragging;
    setDragging(null);
    setDragOverKey(null);
    if (!source || source.session_id === target.session_id) return;
    setSwapError(null);
    setPendingSwap({ a: source, b: target });
  }

  async function confirmSwap() {
    if (!pendingSwap) return;
    setSwapLoading(true);
    setSwapError(null);
    try {
      const res = await fetch(`${API_BASE}/swap`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id_a: pendingSwap.a.session_id, session_id_b: pendingSwap.b.session_id }),
      });
      if (!res.ok) {
        setSwapError(await errorMessageOf(res, "สลับไม่สำเร็จ"));
        return;
      }
      showToast("สลับวิชาสำเร็จแล้ว", "success");
      onRefresh?.();
      setPendingSwap(null);
    } catch {
      setSwapError("สลับไม่สำเร็จ (เชื่อมต่อ server ไม่ได้)");
    } finally {
      setSwapLoading(false);
    }
  }

  function cancelSwap() {
    setPendingSwap(null);
    setSwapError(null);
    setDragging(null);
  }

  // ─── วาดตาราง ─────────────────────────────────────────────

  const isBeingMoved = (it: ScheduleItem) =>
    dragging?.session_id === it.session_id || pendingItem?.session_id === it.session_id;

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
              {DAYS.map((day) => (
                <tr key={day} className="bg-white">
                  <td className={`border-b border-gray-200 border-r border-r-gray-200 ${large ? "px-4 py-2" : "px-2 py-1.5"}`}>
                    <div className={`font-bold text-gray-800 ${large ? "text-[14px]" : "text-[12px]"}`}>{DAY_TH[day]}</div>
                    <div className={`text-gray-400 font-medium ${large ? "text-[10px]" : "text-[8.5px]"}`}>{day}</div>
                  </td>
                  {renderDayCells(day, large)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  function renderDayCells(day: string, large: boolean) {
    const { spans: preferredSpans, covered: preferredCovered, occupied: preferredOccupied } = buildPreferredSpans(day);

    return buildDayCells(day, preferredOccupied).map((cell, i) => {
      if (cell.kind === "covered") return null;
      if (cell.kind === "empty" && preferredCovered.has(i)) return null;

      const slot = DISPLAY_SLOTS[i];
      const isLunch = cell.kind === "lunch";
      const preferredHere = cell.kind === "empty" ? preferredSpans[i] : undefined;
      const span = preferredHere ? preferredHere.span : "span" in cell ? cell.span : 1;
      const cellKey = `${day}-${i}`;

      // วางในช่องว่าง = ย้าย
      const isDroppable = !!dragging && cell.kind === "empty" && !preferredHere && !!slotToId[cellKey];
      const isDropHovered = isDroppable && dragOverKey === cellKey;

      // วางทับวิชาอื่น = สลับเวลา (เฉพาะช่องที่มีวิชาเดียว และไม่ใช่วิชาที่กำลังลากเอง)
      const swapTarget =
        !!dragging && cell.kind === "item" && cell.items.length === 1 && cell.items[0].session_id !== dragging.session_id
          ? cell.items[0]
          : null;
      const isSwapHovered = !!swapTarget && dragOverKey === cellKey;

      return (
        <td
          key={slot}
          colSpan={span}
          className={`relative border border-gray-200 align-top transition-colors duration-150
            ${large ? "h-18" : "h-14"} ${isLunch ? "bg-slate-50" : ""}`}
          onDragOver={(e) => {
            if (isLunch) return;
            e.preventDefault();
            if ((isDroppable || swapTarget) && dragOverKey !== cellKey) setDragOverKey(cellKey);
          }}
          onDragLeave={() => {
            if (dragOverKey === cellKey) setDragOverKey(null);
          }}
          onDrop={() => (swapTarget ? handleSwapDrop(swapTarget) : handleDrop(day, i))}
        >
          {isSwapHovered && (
            <div className={`absolute inset-0.5 z-10 flex items-center justify-center gap-1 rounded-md pointer-events-none ${t.swapHover}`}>
              <ArrowLeftRight size={large ? 16 : 13} className={t.plusHover} strokeWidth={2.25} />
              <span className={`font-semibold ${t.plusHover} ${large ? "text-[11px]" : "text-[9.5px]"}`}>สลับ</span>
            </div>
          )}

          {cell.kind === "empty" && !preferredHere && !isDroppable && !isLunch && span > 1 &&
            Array.from({ length: span - 1 }).map((_, di) => (
              <div
                key={di}
                className="absolute top-0 bottom-0 w-px bg-gray-200 pointer-events-none"
                style={{ left: `${((di + 1) / span) * 100}%` }}
              />
            ))}

          {isLunch && (
            <div className="h-full flex items-center justify-center">
              <span className={`text-gray-300 font-medium tracking-widest uppercase ${large ? "text-[9px]" : "text-[7.5px]"}`}>พักเที่ยง</span>
            </div>
          )}

          {isDroppable && (
            <div
              className={`absolute inset-1 flex items-center justify-center rounded-md pointer-events-none
                transition-colors duration-150 ${isDropHovered ? t.dropHover : t.drop}`}
            >
              <Plus size={large ? 16 : 13} className={isDropHovered ? t.plusHover : t.plus} strokeWidth={2.25} />
            </div>
          )}

          {preferredHere && (
            <PreferredCard subjectIds={preferredHere.subjects} onClick={() => setViewingSubjects(preferredHere.subjects)} />
          )}

          {cell.kind === "item" && renderItems(cell.items, large)}

          {cell.kind === "locked" && <LockedCard item={cell.item} />}
        </td>
      );
    });
  }

  function renderItems(cellItems: ScheduleItem[], large: boolean) {
    const sameSubject = cellItems.every((it) => it.subject_id === cellItems[0].subject_id);
    if (cellItems.length > 1 && sameSubject) {
      return (
        <MergedItemCard
          items={cellItems}
          groupId={year}
          large={large}
          dragging={isBeingMoved}
          onDragStart={(it) => setDragging(it)}
          onDragEnd={() => setDragging(null)}
          onClickItem={(it) => setEditingItem(it)}
        />
      );
    }
    return (
      <div className="h-full flex gap-1">
        {cellItems.map((it) => (
          <div key={it.session_id} className="flex-1 min-w-0 h-full">
            <ItemCard
              item={it}
              groupId={year}
              isCompact={cellItems.length > 1}
              large={large}
              dragging={isBeingMoved(it)}
              onDragStart={() => setDragging(it)}
              onDragEnd={() => setDragging(null)}
              onClick={() => setEditingItem(it)}
            />
          </div>
        ))}
      </div>
    );
  }

  const title = `ตารางเรียน${groupName ? groupName : `ชั้นปีที่ ${year === "Y1" ? "1" : "2"}`}`;

  return (
    <div className="mb-2 relative">
      <Toast toast={toast} />

      {pendingItem && dropTarget && (
        <ConfirmMoveModal
          pendingItem={pendingItem}
          dropTarget={dropTarget}
          loading={moveLoading}
          error={moveError}
          onCancel={cancelMove}
          onConfirm={confirmMove}
        />
      )}

      {pendingSwap && (
        <ConfirmSwapModal
          a={pendingSwap.a}
          b={pendingSwap.b}
          loading={swapLoading}
          error={swapError}
          onCancel={cancelSwap}
          onConfirm={confirmSwap}
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
                <h2 className="text-[16px] font-bold text-gray-900">{title}</h2>
              </div>
              <button
                onClick={() => setExpanded(false)}
                className="text-gray-300 hover:text-gray-500 transition-colors cursor-pointer"
              >
                <X size={20} />
              </button>
            </div>
            <div className="p-6 overflow-auto">{renderTable(true)}</div>
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
          <h2 className="text-[15px] font-bold text-gray-900">{title}</h2>
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