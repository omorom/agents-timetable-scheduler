// ค่าคงที่ + ฟังก์ชันช่วยที่ใช้ร่วมกันระหว่าง ScheduleGrid / ScheduleCards / ScheduleModals
import { DAY_ABBR } from "./types";

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

export interface DropTarget {
  day: string;
  slotIndex: number;
  slot: string;
  timeslotId: string;
}

export const LUNCH_SLOT = "12:00-12:50";
const START_HOUR = 8;
const END_HOUR = 16;

export const pad = (n: number) => n.toString().padStart(2, "0");
export const hourOf = (t: string) => parseInt(t.split(":")[0], 10);
export const dayOf = (x: { day: string }) => DAY_ABBR[x.day] ?? x.day;

export const DISPLAY_SLOTS = Array.from(
  { length: END_HOUR - START_HOUR + 1 },
  (_, i) => `${pad(START_HOUR + i)}:00-${pad(START_HOUR + i)}:50`
);

export function findSpan(startTime: string, endTime: string): { startIdx: number; span: number } | null {
  const slotHours = DISPLAY_SLOTS.map(hourOf);
  const startIdx = slotHours.indexOf(hourOf(startTime));
  if (startIdx === -1) return null;

  const endHour = hourOf(endTime);
  let span = 0;
  for (let i = startIdx; i < slotHours.length && slotHours[i] < endHour; i++) span++;
  return { startIdx, span: span || 1 };
}

export function blockLabelOf(startTime: string, endTime: string): string {
  const span = findSpan(startTime, endTime);
  if (!span) return `${startTime}-${endTime}`;
  const startLabel = DISPLAY_SLOTS[span.startIdx].split("-")[0];
  const endLabel = DISPLAY_SLOTS[span.startIdx + span.span - 1].split("-")[1];
  return `${startLabel}-${endLabel}`;
}

// สีของช่อง "วางได้" ระหว่างลากวิชา:
// - ปกติ (drop): พื้นขาว + เส้นประบาง + เครื่องหมาย + จางๆ — เดิมพื้นส้มทุกช่องพร้อมกัน ทำให้ทั้งตารางดูเหลือง
// - ช่องที่เมาส์ชี้อยู่ (dropHover): ค่อยขึ้นพื้นสีอ่อน + เส้นเข้ม ให้เห็นชัดว่าจะวางตรงไหน
// - วางทับวิชาอื่นเพื่อสลับ (swapHover): เส้นเข้มแบบเดียวกัน แต่พื้นขาวโปร่ง ยังมองเห็นวิชาข้างใต้
export const HEADER_THEME: Record<
  "orange" | "purple",
  {
    gradient: string;
    lunchBg: string;
    accent: string;
    divider: string;
    drop: string;
    dropHover: string;
    swapHover: string;
    plus: string;
    plusHover: string;
  }
> = {
  orange: {
    gradient: "bg-linear-to-r from-orange-500 to-orange-400",
    lunchBg: "bg-orange-300/70",
    accent: "bg-orange-500",
    divider: "border-orange-400/40",
    drop: "border border-dashed border-orange-200",
    dropHover: "border border-dashed border-orange-400 bg-orange-50",
    swapHover: "border border-dashed border-orange-400 bg-white/75",
    plus: "text-orange-300",
    plusHover: "text-orange-500",
  },
  purple: {
    gradient: "bg-linear-to-r from-purple-600 to-purple-500",
    lunchBg: "bg-purple-400/70",
    accent: "bg-purple-600",
    divider: "border-purple-500/40",
    drop: "border border-dashed border-purple-200",
    dropHover: "border border-dashed border-purple-400 bg-purple-50",
    swapHover: "border border-dashed border-purple-400 bg-white/75",
    plus: "text-purple-300",
    plusHover: "text-purple-500",
  },
};