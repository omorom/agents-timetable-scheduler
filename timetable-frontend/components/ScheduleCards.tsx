"use client";

// การ์ดที่แสดงในช่องของตารางเรียน (วิชาที่ AI จัด / วิชาที่ล็อก / วิชาศึกษาทั่วไป)
import { GripVertical, Lock } from "lucide-react";
import { ScheduleItem, ExistingItem, getColor } from "./types";
import { PreferredItem } from "./scheduleGridUtils";

export function MergedItemCard({
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

export function ItemCard({
  item,
  groupId,
  dragging,
  isCompact,
  large,
  onDragStart,
  onDragEnd,
  onClick,
}: {
  item: ScheduleItem;
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

export function LockedCard({ item }: { item: ExistingItem }) {
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

export function PreferredCard({
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