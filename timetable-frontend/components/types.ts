export interface ScheduleItem {
  subject_id: string;
  subject_name: string;
  session_id: string;
  room_id: string;
  timeslot_id: number;
  day: string;
  start_time: string;
  end_time: string;
  session_type?: string;
  teacher_name?: string;
  // ─── เพิ่มใหม่: สำหรับ modal ดูรายละเอียด/แก้ไขอาจารย์-ห้อง ───
  teacher_key?: string | null;   // teacher_id ตัวจริง (เดี่ยว) ไว้ preselect dropdown
  room_key?: string;             // room_id ตัวจริง (room_id ใน ScheduleItem ด้านบนถูกแปลงเป็นชื่อห้องไปแล้ว)
  section?: string | null;
  subject_name_english?: string | null;
  description_thai?: string | null;
  description_english?: string | null;
  subject_type?: string | null;
  semester?: number | null;
  // ──────────────────────────────────────────────────────────
}

export interface ExistingItem {
  id: number;
  timeslot_id: number;
  day: string;
  start_time: string;
  end_time: string;
  subject_id: string | null;
  subject_name: string | null;
  teacher_id: string | null;
  teacher_name: string | null;
  room_id: string | null;
  group_id: string | null;
}

export interface Timeslot {
  timeslot_id: string;
  block_id: number;
  day: string;
  start_time: string;
  end_time: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  time: string;
}

// ─── เพิ่มใหม่: สำหรับ dropdown เลือกอาจารย์/ห้อง ใน modal แก้ไข ───
export interface Teacher {
  teacher_id: string;
  teacher_name: string;
}

export interface Room {
  room_id: string;
  room_name: string;
  capacity?: number;
}
// ──────────────────────────────────────────────────────────

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];

export const DAY_TH: Record<string, string> = {
  Monday: "จันทร์",
  Tuesday: "อังคาร",
  Wednesday: "พุธ",
  Thursday: "พฤหัสบดี",
  Friday: "ศุกร์",
};

export const DAY_ABBR: Record<string, string> = {
  MON: "Monday", TUE: "Tuesday", WED: "Wednesday",
  THU: "Thursday", FRI: "Friday", SAT: "Saturday", SUN: "Sunday",
};

// ═══════════════════════════════════════════════════════════════
// getColor — กำหนดสีให้แต่ละวิชา โดยหาช่องว่างที่กว้างที่สุดบนวงล้อสี
// เสมอ (ไม่ใช่ hash แบบสุ่มมั่วๆ) รับประกันว่าสีห่างจากทุกสีเดิมมากที่สุด
// ═══════════════════════════════════════════════════════════════

export interface SubjectColor {
  bg: string;
  border: string;
  text: string;
}

const colorCache = new Map<string, SubjectColor>();
const usedHues: number[] = [];

function pickNextHue(): number {
  if (usedHues.length === 0) {
    usedHues.push(0);
    return 0;
  }

  const sorted = [...usedHues].sort((a, b) => a - b);
  let maxGap = -1;
  let gapStart = 0;

  for (let i = 0; i < sorted.length; i++) {
    const curr = sorted[i];
    const next = i === sorted.length - 1 ? sorted[0] + 360 : sorted[i + 1];
    const gap = next - curr;
    if (gap > maxGap) {
      maxGap = gap;
      gapStart = curr;
    }
  }

  const newHue = (gapStart + maxGap / 2) % 360;
  usedHues.push(newHue);
  return newHue;
}

export function getColor(subjectId: string): SubjectColor {
  const cached = colorCache.get(subjectId);
  if (cached) return cached;

  const hue = pickNextHue();

  const color: SubjectColor = {
    bg: `hsl(${hue}, 85%, 96%)`,
    border: `hsl(${hue}, 65%, 45%)`,
    text: `hsl(${hue}, 70%, 30%)`,
  };

  colorCache.set(subjectId, color);
  return color;
}