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
// getColor / primeSubjectColors — กำหนดสีให้แต่ละวิชาจาก palette ที่เลือกมือ
//
// [แก้] สีผูกกับ "รหัสวิชา" ไม่ใช่ "ลำดับที่เจอในตาราง" อีกต่อไป
// เดิมแจกสีตามลำดับที่ render เจอ (จันทร์เช้า -> ศุกร์เย็น) พอผู้ใช้ลากย้ายวิชา
// แล้วโหลดตารางใหม่ ลำดับที่เจอเปลี่ยน -> สีเลื่อนทั้งตาราง (ทั้งที่ย้ายแค่วิชาเดียว)
// ตอนนี้เรียงรหัสวิชาก่อนแจกสี ผลขึ้นกับ "ชุดวิชาของแต่ละชั้นปี" อย่างเดียว
// ย้ายวิชาไปคาบไหนก็ได้สีเดิม (สีจะเปลี่ยนก็ต่อเมื่อเพิ่ม/ลบวิชาออกจากชั้นปีนั้น)
//
// 1) primeSubjectColors(scheduleByGroup) — เรียกครั้งเดียวตอนโหลดข้อมูลตารางใหม่
//    (ก่อน render การ์ด) แจกสีให้ "ทุกวิชา" ล่วงหน้า:
//    - วิชาที่สอนมากกว่า 1 ชั้นปี (เช่น LECTURE รวม CS+IT) ได้สีเดียวกันทุกชั้นปี
//    - วิชาที่สอนชั้นปีเดียว ได้สีที่ยังไม่ถูกใช้ในชั้นปีนั้น (กันสีซ้ำในตารางเดียวกัน)
//    ทั้งสองแบบเรียงตามรหัสวิชาเสมอ จึงได้ผลเหมือนเดิมทุกครั้ง
//
// 2) getColor(subjectId, groupId) — ใช้ตอน render แค่อ่านสีที่แจกไว้แล้ว
//    ถ้าไม่เจอ (เช่น ลืมเรียก prime) ใช้ hash ของรหัสวิชาแทน ซึ่งก็คงที่เหมือนกัน
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

const byCode = (a: string, b: string) => a.localeCompare(b, undefined, { numeric: true });

function hashIndex(s: string): number {
  let h = 0;
  for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return h % PALETTE.length;
}

// เรียกทุกครั้งที่โหลด/รีเฟรชตารางใหม่ (ก่อน render) — เคลียร์ cache เก่าทิ้ง แล้วแจกสีใหม่
// ทั้งหมดแบบเรียงตามรหัสวิชา (ไม่ขึ้นกับตำแหน่งในตาราง)
export function primeSubjectColors(scheduleByGroup: Record<string, ScheduleItem[]>) {
  colorCache.clear();

  const groupsBySubject = new Map<string, Set<string>>();
  const subjectsByGroup = new Map<string, Set<string>>();
  for (const [groupId, items] of Object.entries(scheduleByGroup)) {
    for (const item of items) {
      if (!item.subject_id) continue;
      (groupsBySubject.get(item.subject_id) ?? groupsBySubject.set(item.subject_id, new Set()).get(item.subject_id)!).add(groupId);
      (subjectsByGroup.get(groupId) ?? subjectsByGroup.set(groupId, new Set()).get(groupId)!).add(item.subject_id);
    }
  }

  const usedByGroup = new Map<string, Set<number>>();
  const used = (groupId: string) =>
    usedByGroup.get(groupId) ?? usedByGroup.set(groupId, new Set()).get(groupId)!;

  // ขั้น 1: วิชาที่สอนหลายชั้นปี — สีเดียวกันทุกชั้นปี (เรียงตามรหัสวิชา)
  const shared = [...groupsBySubject.keys()].filter((id) => groupsBySubject.get(id)!.size > 1).sort(byCode);
  shared.forEach((subjectId, i) => {
    const idx = i % PALETTE.length;
    for (const groupId of groupsBySubject.get(subjectId)!) {
      colorCache.set(`${groupId}::${subjectId}`, PALETTE[idx]);
      used(groupId).add(idx);
    }
  });

  // ขั้น 2: วิชาที่สอนชั้นปีเดียว — ไล่แจกสีที่ยังว่างในชั้นปีนั้น (เรียงตามรหัสวิชา)
  for (const groupId of [...subjectsByGroup.keys()].sort(byCode)) {
    const taken = used(groupId);
    let idx = 0;
    const singles = [...subjectsByGroup.get(groupId)!].filter((id) => groupsBySubject.get(id)!.size <= 1).sort(byCode);
    for (const subjectId of singles) {
      // หาสีที่ยังไม่ถูกใช้ในชั้นปีนี้ ถ้าใช้ครบทุกสีแล้วค่อยวนซ้ำ
      for (let tries = 0; tries < PALETTE.length && taken.has(idx); tries++) idx = (idx + 1) % PALETTE.length;
      colorCache.set(`${groupId}::${subjectId}`, PALETTE[idx]);
      taken.add(idx);
      idx = (idx + 1) % PALETTE.length;
    }
  }
}

export function getColor(subjectId: string, groupId: string): SubjectColor {
  // ไม่แจกสีเพิ่มตอน render (เดิมแจกตามลำดับที่เจอ ซึ่งทำให้สีเปลี่ยนเมื่อย้ายวิชา)
  return colorCache.get(`${groupId}::${subjectId}`) ?? PALETTE[hashIndex(subjectId)];
}