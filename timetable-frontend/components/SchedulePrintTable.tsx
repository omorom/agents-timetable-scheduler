"use client";

import { ScheduleItem, DAY_TH } from "./types";

interface Group {
  group_id: string;
  group_name: string;
  total_students: number;
  major: string; // 'CS' | 'IT'
}

const DAY_ORDER: Record<string, number> = { Monday: 0, Tuesday: 1, Wednesday: 2, Thursday: 3, Friday: 4 };

function yearNumber(group_id: string): string {
  const match = group_id.match(/Y(\d+)$/i);
  return match ? match[1] : "?";
}

// ป้ายย่อสำหรับตาราง print (เช่น "CS Y4", "IT Y4") — ใช้ major code ตรง ๆ ไม่ map
// เป็นชื่อเต็มภาษาไทย เพราะคอลัมน์แคบ ต้องการอ่านไว และหนึ่งแถวอาจมีหลายชั้นปี/สาขา
function shortYearLabel(group_id: string, major: string): string {
  return `${major} Y${yearNumber(group_id)}`;
}

type PrintRow = ScheduleItem & { group_labels: string[]; teacher_lines: string[] };

// แปลง scheduleByGroup ให้เป็น row เดียวแบน ๆ เรียงตามรายวิชา (subject_id) แล้ว
// LECTURE ก่อน LAB แล้ววัน/เวลา — session เดียวกันที่ปรากฏในหลายกลุ่ม (เช่น LECTURE
// รวมข้ามชั้นปี/สาขา) ถูกยุบเหลือแถวเดียว พร้อมรวมชั้นปีทั้งหมดที่เรียนไว้ในเซลล์เดียว
// (รู้ว่าเป็น session เดียวกันจาก session_id ที่ backend ส่งมาตรงกัน)
function buildPrintRows(groups: Group[], scheduleByGroup: Record<string, ScheduleItem[]>): PrintRow[] {
  const bySession = new Map<string, PrintRow>();

  for (const g of groups) {
    const groupLabel = shortYearLabel(g.group_id, g.major);
    for (const item of scheduleByGroup[g.group_id] ?? []) {
      const existingRow = bySession.get(item.session_id);
      if (existingRow) {
        if (!existingRow.group_labels.includes(groupLabel)) {
          existingRow.group_labels.push(groupLabel);
        }
        continue;
      }
      // teacher_name จาก backend เป็น string เดียว join อาจารย์หลายคนด้วย ", " —
      // แยกกลับเป็นบรรทัดต่ออาจารย์ในเซลล์เดียวกัน (ไม่แยกคนละแถว)
      const teacherLines = (item.teacher_name ?? "")
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      bySession.set(item.session_id, {
        ...item,
        group_labels: [groupLabel],
        teacher_lines: teacherLines.length > 0 ? teacherLines : ["-"],
      });
    }
  }

  const typeRank = (t?: string) => (t === "LECTURE" ? 0 : t === "LAB" ? 1 : 2);

  return Array.from(bySession.values()).sort((a, b) => {
    if (a.subject_id !== b.subject_id) return a.subject_id.localeCompare(b.subject_id);
    const typeDiff = typeRank(a.session_type) - typeRank(b.session_type);
    if (typeDiff !== 0) return typeDiff;
    const dayDiff = (DAY_ORDER[a.day] ?? 9) - (DAY_ORDER[b.day] ?? 9);
    if (dayDiff !== 0) return dayDiff;
    return a.start_time.localeCompare(b.start_time);
  });
}

// ความกว้างคอลัมน์ตายตัว (% ของตาราง) — ให้คอลัมน์ยาว (ชื่อวิชา, อาจารย์สอน) มีที่
// พอหายใจ และคอลัมน์สั้น (ชั้นปี, วัน, เวลา, ห้อง, ประเภท, ที่นั่ง) ไม่กว้างเกินจำเป็น
// เดิมปล่อยให้ browser คำนวณเองทำให้แต่ละคอลัมน์ชิดกันจนดูอึดอัด
const COLUMNS: { label: string; width: string; align?: "left" | "center" }[] = [
  { label: "รหัสวิชา", width: "8%" },
  { label: "ชื่อวิชา", width: "22%" },
  { label: "อาจารย์สอน", width: "18%" },
  { label: "ชั้นปี", width: "9%", align: "center" },
  { label: "วัน", width: "8%", align: "center" },
  { label: "เวลา", width: "10%", align: "center" },
  { label: "ห้อง", width: "9%", align: "center" },
  { label: "ประเภท", width: "8%", align: "center" },
  { label: "ที่นั่ง", width: "8%", align: "center" },
];

// ตาราง list สำหรับพิมพ์/Export PDF เท่านั้น (ซ่อนบนจอด้วย .print-only ใน page.tsx)
export default function SchedulePrintTable({
  groups,
  scheduleByGroup,
}: {
  groups: Group[];
  scheduleByGroup: Record<string, ScheduleItem[]>;
}) {
  const printRows = buildPrintRows(groups, scheduleByGroup);

  return (
    <div id="schedule-print-table" className="print-only">
      <h1 className="text-lg font-bold text-gray-900 mb-1">ตารางเรียน</h1>
      <p className="text-xs text-gray-500 mb-4">ภาควิชาวิทยาการคอมพิวเตอร์และเทคโนโลยีสารสนเทศ</p>
      <table className="w-full text-[12px] border-collapse table-fixed">
        <colgroup>
          {COLUMNS.map((c) => (
            <col key={c.label} style={{ width: c.width }} />
          ))}
        </colgroup>
        <thead>
          <tr className="bg-gray-100">
            {COLUMNS.map((c) => (
              <th
                key={c.label}
                className={`border border-gray-300 px-3 py-2 whitespace-nowrap ${
                  c.align === "center" ? "text-center" : "text-left"
                }`}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {printRows.length === 0 ? (
            <tr>
              <td colSpan={COLUMNS.length} className="border border-gray-300 px-3 py-4 text-center text-gray-400">
                ยังไม่มีข้อมูลตารางเรียน
              </td>
            </tr>
          ) : (
            printRows.map((r) => (
              <tr key={r.session_id}>
                <td className="border border-gray-300 px-3 py-2">{r.subject_id}</td>
                <td className="border border-gray-300 px-3 py-2">{r.subject_name}</td>
                <td className="border border-gray-300 px-3 py-2">
                  {r.teacher_lines.map((name, i) => (
                    <div key={i}>{name}</div>
                  ))}
                </td>
                <td className="border border-gray-300 px-3 py-2 text-center">
                  {r.group_labels.map((label, i) => (
                    <div key={i}>{label}</div>
                  ))}
                </td>
                <td className="border border-gray-300 px-3 py-2 text-center">{DAY_TH[r.day] ?? r.day}</td>
                <td className="border border-gray-300 px-3 py-2 text-center whitespace-nowrap">
                  {r.start_time}-{r.end_time}
                </td>
                <td className="border border-gray-300 px-3 py-2 text-center">{r.room_id || "-"}</td>
                <td className="border border-gray-300 px-3 py-2 text-center">{r.session_type || "-"}</td>
                <td className="border border-gray-300 px-3 py-2 text-center">{r.max_capacity ?? "-"}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}