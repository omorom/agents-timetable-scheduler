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
  // จำนวนที่เปิดสอน (จำนวนที่นั่ง) ของ section นี้ — backend เติมมาให้ที่ /schedule
  // (ดู routers/schedule.py resolve_capacity) ใช้ตอนแสดงตาราง print/export PDF
  max_capacity?: number | null;
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
// getColor / primeSubjectColors — กำหนดสีให้แต่ละวิชาจาก 12 สีที่เลือกมือ
// แบบ "2 ขั้นตอน":
//
// 1) primeSubjectColors(scheduleByGroup) — เรียกครั้งเดียวตอนโหลดข้อมูล
//    ตารางใหม่ (ก่อน render การ์ดใด ๆ) สแกนหาว่าวิชาไหน "สอนมากกว่า 1
//    ชั้นปี" (เช่น LECTURE ที่ถูกรวมข้ามชั้นปี/สาขา) แล้วจองสีเดียวกันให้
//    ทุกชั้นปีที่วิชานั้นปรากฏไปเลย — กันไม่ให้วิชาเดียวกันดูเหมือนคนละวิชา
//    เพราะสีไม่ตรงกันข้ามตาราง
//
// 2) getColor(subjectId, groupId) — ใช้ตอน render การ์ดจริง ถ้าวิชานั้น
//    ถูกจองสีไว้แล้วจากขั้นตอน 1 (สอนหลายชั้นปี) ก็คืนสีเดิม ถ้ายังไม่มี
//    (วิชาที่สอนแค่ชั้นปีเดียว) จะไล่แจกสีที่ "ยังไม่ถูกจองในชั้นปีนั้น"
//    ให้ — แยกตัวนับต่อชั้นปี (nextIndexByGroup) เพื่อให้วิชาในตาราง
//    เดียวกันกระจายสีให้มากที่สุดเท่าที่เหลือ ไม่ชนกับสีที่ถูกจองไว้แล้ว
//    จากขั้นตอน 1 ในชั้นปีนั้น (usedIndicesByGroup)
// ═══════════════════════════════════════════════════════════════

export interface SubjectColor {
  bg: string;
  border: string;
  text: string;
}

const PALETTE: SubjectColor[] = [
  { bg: "#FDECEF", border: "#F4B6C2", text: "#A5475A" }, // rose
  { bg: "#E8F1FD", border: "#B3CDF0", text: "#3E6199" }, // blue
  { bg: "#FFFBE3", border: "#F2E6A6", text: "#857022" }, // lemon (เหลืองขึ้น)
  { bg: "#F0EBFC", border: "#CBBFEF", text: "#6650A8" }, // lavender
  { bg: "#E7F7EC", border: "#B5E2C2", text: "#3D7A52" }, // mint
  { bg: "#FCE9F3", border: "#F2B9D9", text: "#A34A7C" }, // pink
  { bg: "#FFE8D6", border: "#F8BE94", text: "#A5501F" }, // apricot (ส้มชัดขึ้น)
  { bg: "#E3F6F3", border: "#AEE0D8", text: "#2F7B72" }, // aqua
  { bg: "#ECEEFC", border: "#BEC5F0", text: "#4B55A3" }, // periwinkle
  { bg: "#F8EBFB", border: "#E2BCEB", text: "#8A4A99" }, // orchid
  { bg: "#E6F4FB", border: "#B0D9EE", text: "#33739A" }, // sky
];

// key ของ cache คือ "groupId::subjectId"
const colorCache = new Map<string, SubjectColor>();
// ตัวนับ index สำหรับแจกสีแบบไล่ต่อกลุ่ม (ใช้กับวิชาที่สอนชั้นปีเดียว)
const nextIndexByGroup = new Map<string, number>();
// index ที่ "ถูกจองไปแล้ว" ในแต่ละกลุ่ม (ทั้งจาก primeSubjectColors และจาก
// getColor เอง) กันไม่ให้แจกซ้ำสีเดิมในตารางเดียวกันโดยไม่จำเป็น
const usedIndicesByGroup = new Map<string, Set<number>>();

function markUsed(groupId: string, idx: number) {
  const set = usedIndicesByGroup.get(groupId) ?? new Set<number>();
  set.add(idx);
  usedIndicesByGroup.set(groupId, set);
}

// เรียกทุกครั้งที่โหลด/รีเฟรชตารางใหม่ (ก่อน render) — เคลียร์ cache เก่าทิ้ง
// กันข้อมูลรอบก่อนค้าง แล้วสแกนหาวิชาที่ปรากฏมากกว่า 1 ชั้นปี จองสีเดียวกัน
// ให้ทุกชั้นปีที่วิชานั้นสอนอยู่
export function primeSubjectColors(scheduleByGroup: Record<string, ScheduleItem[]>) {
  colorCache.clear();
  nextIndexByGroup.clear();
  usedIndicesByGroup.clear();

  const groupsBySubject = new Map<string, Set<string>>();
  for (const [groupId, items] of Object.entries(scheduleByGroup)) {
    for (const item of items) {
      const set = groupsBySubject.get(item.subject_id) ?? new Set<string>();
      set.add(groupId);
      groupsBySubject.set(item.subject_id, set);
    }
  }

  let nextGlobalIndex = 0;
  for (const [subjectId, groupIds] of groupsBySubject) {
    if (groupIds.size <= 1) continue; // วิชาชั้นปีเดียว ปล่อยให้ getColor แจกทีหลัง
    const idx = nextGlobalIndex % PALETTE.length;
    nextGlobalIndex++;
    const color = PALETTE[idx];
    for (const groupId of groupIds) {
      colorCache.set(`${groupId}::${subjectId}`, color);
      markUsed(groupId, idx);
    }
  }
}

export function getColor(subjectId: string, groupId: string): SubjectColor {
  const key = `${groupId}::${subjectId}`;
  const cached = colorCache.get(key);
  if (cached) return cached;

  const used = usedIndicesByGroup.get(groupId) ?? new Set<number>();
  let idx = nextIndexByGroup.get(groupId) ?? 0;

  // หา index ที่ยังไม่ถูกจองในกลุ่มนี้ (กันชนกับสีที่ primeSubjectColors
  // จองไว้แล้ว) วนไม่เกินความยาว palette กันลูปไม่รู้จบ
  for (let tries = 0; tries < PALETTE.length && used.has(idx); tries++) {
    idx = (idx + 1) % PALETTE.length;
  }

  const color = PALETTE[idx];
  markUsed(groupId, idx);
  nextIndexByGroup.set(groupId, idx + 1);

  colorCache.set(key, color);
  return color;
}