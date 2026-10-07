"use client";

import { ScheduleItem, DAY_TH } from "./types";

interface Group {
  group_id: string;
  group_name: string;
  total_students: number;
  major: string; // 'CS' | 'IT'
}

// วิชาที่ AI จัดไม่ได้ (ยังไม่มีวัน/เวลา/ห้อง) — ใช้ข้อมูลชุดเดียวกับกระดิ่งแจ้งเตือน
// field ส่วนใหญ่เป็น optional เผื่อแหล่งข้อมูลส่งมาไม่ครบ ช่องไหนไม่มีจะแสดง "-"
export interface UnscheduledItem {
  session_id?: string;
  subject_id: string;
  subject_name?: string;
  session_type?: string | null;
  section?: string | null;
  group_ids?: string[] | null;
  reason?: string;
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

// เดา major จาก group_id เมื่อหาใน groups ไม่เจอ (prefix "IT-" = IT, ไม่มี prefix = CS)
function labelFromGroupId(group_id: string, groups: Group[]): string {
  const g = groups.find((x) => x.group_id === group_id);
  const major = g?.major ?? (group_id.toUpperCase().startsWith("IT-") ? "IT" : "CS");
  return shortYearLabel(group_id, major);
}

function splitTeachers(teacherName?: string | null): string[] {
  const lines = (teacherName ?? "")
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
  return lines.length > 0 ? lines : ["-"];
}

const typeRank = (t?: string) => (t === "LECTURE" ? 0 : t === "LAB" ? 1 : 2);

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
      bySession.set(item.session_id, {
        ...item,
        group_labels: [groupLabel],
        teacher_lines: splitTeachers(item.teacher_name),
      });
    }
  }

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

// ตารางวิชาที่จัดไม่ได้ — ใช้เฉพาะข้อมูลที่ failed_sessions จาก backend มีจริง
// (ไม่มีอาจารย์/ที่นั่ง/วัน/เวลา/ห้อง) แล้วเพิ่มคอลัมน์ "สาเหตุ" แทน
const UNSCHEDULED_COLUMNS: { label: string; width: string; align?: "left" | "center" }[] = [
  { label: "รหัสวิชา", width: "10%" },
  { label: "ชื่อวิชา", width: "30%" },
  { label: "ชั้นปี", width: "14%", align: "center" },
  { label: "ประเภท", width: "14%", align: "center" },
  { label: "สาเหตุ", width: "32%" },
];

function TableHead({ columns }: { columns: typeof COLUMNS }) {
  return (
    <>
      <colgroup>
        {columns.map((c) => (
          <col key={c.label} style={{ width: c.width }} />
        ))}
      </colgroup>
      <thead>
        <tr className="bg-gray-100">
          {columns.map((c) => (
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
    </>
  );
}

// ตาราง list สำหรับพิมพ์/Export PDF เท่านั้น (ซ่อนบนจอด้วย .print-only ใน page.tsx)
export default function SchedulePrintTable({
  groups,
  scheduleByGroup,
  unscheduled = [],
}: {
  groups: Group[];
  scheduleByGroup: Record<string, ScheduleItem[]>;
  /** วิชาที่จัดไม่ได้ — ไม่ส่ง หรือส่ง [] มา = ไม่แสดงส่วนท้าย */
  unscheduled?: UnscheduledItem[];
}) {
  const printRows = buildPrintRows(groups, scheduleByGroup);

  const unscheduledRows = [...unscheduled].sort((a, b) => {
    if (a.subject_id !== b.subject_id) return a.subject_id.localeCompare(b.subject_id);
    const typeDiff = typeRank(a.session_type ?? undefined) - typeRank(b.session_type ?? undefined);
    if (typeDiff !== 0) return typeDiff;
    return (a.section ?? "").localeCompare(b.section ?? "");
  });

  return (
    <div id="schedule-print-table" className="print-only">
      <h1 className="text-lg font-bold text-gray-900 mb-1">ตารางเรียน</h1>
      <p className="text-xs text-gray-500 mb-4">ภาควิชาวิทยาการคอมพิวเตอร์และเทคโนโลยีสารสนเทศ</p>
      <table className="w-full text-[12px] border-collapse table-fixed">
        <TableHead columns={COLUMNS} />
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

      {/* ── วิชาที่ยังไม่ได้จัดลงตาราง (แสดงเฉพาะเมื่อมี) ── */}
      {unscheduledRows.length > 0 && (
        <div className="mt-8" style={{ breakInside: "avoid" }}>
          <h2 className="text-[14px] font-bold text-gray-900 mb-1">
            รายวิชาที่ยังไม่ได้จัดลงตาราง ({unscheduledRows.length} รายการ)
          </h2>
          <p className="text-xs text-gray-500 mb-3">
            รายวิชาเหล่านี้ระบบยังจัดวัน เวลา และห้องเรียนให้ไม่ได้ ต้องจัดเพิ่มก่อนใช้งานตารางจริง
          </p>
          <table className="w-full text-[12px] border-collapse table-fixed">
            <TableHead columns={UNSCHEDULED_COLUMNS} />
            <tbody>
              {unscheduledRows.map((r, idx) => (
                <tr key={r.session_id ?? `${r.subject_id}-${r.session_type}-${idx}`}>
                  <td className="border border-gray-300 px-3 py-2">{r.subject_id}</td>
                  <td className="border border-gray-300 px-3 py-2">{r.subject_name || "-"}</td>
                  <td className="border border-gray-300 px-3 py-2 text-center">
                    {r.group_ids && r.group_ids.length > 0
                      ? r.group_ids.map((gid) => <div key={gid}>{labelFromGroupId(gid, groups)}</div>)
                      : "-"}
                  </td>
                  <td className="border border-gray-300 px-3 py-2 text-center">
                    {r.session_type || "-"}
                    {r.section && <div className="text-[11px] text-gray-500">section {r.section}</div>}
                  </td>
                  <td className="border border-gray-300 px-3 py-2">{r.reason || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}