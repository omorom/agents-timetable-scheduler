"use client";

import { useMemo, useState } from "react";
import { Search } from "lucide-react";

export interface Subject {
  subject_id: string;
  name_thai: string;
  name_english?: string;
  subject_type: "GENERAL" | "CORE" | "ELECTIVE";
  group_id?: string | null;
  semester?: number | null;
}

type MajorFilter = "ALL" | "CS" | "IT";

// group_id แยกตามสาขา — CS: Y1..Y4, IT: IT-Y1..IT-Y4 (มี prefix กันชนกับของ CS)
const CS_GROUPS = ["Y1", "Y2", "Y3", "Y4"];
const IT_GROUPS = ["IT-Y1", "IT-Y2", "IT-Y3", "IT-Y4"];

const MAJOR_LABELS: Record<Exclude<MajorFilter, "ALL">, string> = {
  CS: "วิทยาการคอมพิวเตอร์ (CS)",
  IT: "เทคโนโลยีสารสนเทศ (IT)",
};

const TYPE_LABEL: Record<string, string> = {
  GENERAL: "ศึกษาทั่วไป",
  CORE: "วิชาสาขา",
  ELECTIVE: "วิชาเลือก",
};

// เดาสาขาจาก group_id ตรงๆ (prefix "IT-" บอกอยู่แล้ว ไม่มี prefix = CS)
function majorOf(group_id?: string | null): "CS" | "IT" | null {
  if (!group_id) return null;
  return group_id.toUpperCase().startsWith("IT-") ? "IT" : "CS";
}

// ดึงแค่เลขปีล้วนๆ จากท้าย group_id ใช้ตอนกรองแบบ "ทุกสาขา" (ไม่สนใจ prefix)
function yearNumber(group_id?: string | null): string {
  if (!group_id) return "";
  const match = group_id.match(/Y(\d+)$/i);
  return match ? match[1] : "";
}

// แปลง group_id (Y1, IT-Y1, ...) เป็น "ปี 1", "ปี 2" ... สำหรับแสดงผล
// แก้จาก ^Y(\d+)$ เดิมที่ match ได้แค่ "Y1..Y4" ของ CS อย่างเดียว ทำให้ "IT-Y1" หลุด parse ไม่ได้
export function yearLabel(group_id?: string | null): string {
  if (!group_id) return "-";
  const match = group_id.match(/Y(\d+)$/i);
  return match ? `ปี ${match[1]}` : group_id;
}

interface Props {
  subjects: Subject[];
  academicYear: string;
  existingByKey: Record<string, Set<string>>;
  sectionCountByKey: Record<string, number>;
  onSelect: (s: Subject) => void;
}

export default function SubjectPickerTable({
  subjects,
  academicYear,
  existingByKey,
  sectionCountByKey,
  onSelect,
}: Props) {
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<"ALL" | "GENERAL" | "CORE" | "ELECTIVE">("ALL");
  const [majorFilter, setMajorFilter] = useState<MajorFilter>("ALL");
  const [groupFilter, setGroupFilter] = useState<string>("ALL");
  const [semesterFilter, setSemesterFilter] = useState<string>("ALL");

  const semesterOptions = useMemo(() => {
    const set = new Set<number>();
    subjects.forEach((s) => { if (s.semester != null) set.add(s.semester); });
    return Array.from(set).sort((a, b) => a - b);
  }, [subjects]);

  // ตัวเลือกปีในดรอปดาวน์ที่สอง:
  // - เลือกสาขาแล้ว (CS/IT) -> โชว์ group_id จริงของสาขานั้น
  // - "ทุกสาขา" -> โชว์แค่เลขปีล้วนๆ (1-4) เพราะปี 1 ของทุกสาขาคือปี 1 เหมือนกัน
  const yearOptions = useMemo(() => {
    if (majorFilter === "CS") return CS_GROUPS;
    if (majorFilter === "IT") return IT_GROUPS;
    return ["1", "2", "3", "4"];
  }, [majorFilter]);

  // สลับสาขาแล้ว reset ตัวกรองปีทิ้ง กันเลือกปีของสาขาเก่าค้างอยู่
  function handleMajorChange(next: MajorFilter) {
    setMajorFilter(next);
    setGroupFilter("ALL");
  }

  const filteredSubjects = useMemo(() => {
    const q = search.trim().toLowerCase();
    return subjects.filter((s) => {
      const matchesType = typeFilter === "ALL" || s.subject_type === typeFilter;
      const matchesMajor = majorFilter === "ALL" || majorOf(s.group_id) === majorFilter;
      // "ทุกสาขา": groupFilter เป็นเลขปีล้วนๆ เทียบกับเลขปีของ group_id
      // เลือกสาขาแล้ว: groupFilter เป็น group_id เต็มๆ เทียบตรงตัว
      const matchesGroup =
        groupFilter === "ALL"
          ? true
          : majorFilter === "ALL"
            ? yearNumber(s.group_id) === groupFilter
            : s.group_id === groupFilter;
      const matchesSemester = semesterFilter === "ALL" || String(s.semester ?? "") === semesterFilter;
      const matchesSearch =
        !q ||
        s.subject_id.toLowerCase().includes(q) ||
        s.name_thai.toLowerCase().includes(q) ||
        (s.name_english || "").toLowerCase().includes(q);
      return matchesType && matchesMajor && matchesGroup && matchesSemester && matchesSearch;
    });
  }, [subjects, search, typeFilter, majorFilter, groupFilter, semesterFilter]);

  return (
    <>
      <div className="relative mb-4">
        <Search size={17} className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-300" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="พิมพ์รหัสวิชาหรือชื่อวิชา"
          className="w-full border border-gray-200 rounded-lg pl-11 pr-4 py-3 text-sm outline-none bg-white focus:border-orange-300 transition-all placeholder:text-gray-400"
        />
      </div>

      <div className="grid grid-cols-4 gap-3 mb-2">
        <div>
          <label className="block text-[11px] font-semibold text-gray-400 uppercase tracking-wide mb-1.5">
            ประเภทวิชา
          </label>
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as typeof typeFilter)}
            className="w-full border border-gray-200 rounded-md px-3 py-1.5 text-sm outline-none bg-white focus:border-orange-300 transition-all text-gray-600"
          >
            <option value="ALL">ทุกประเภท</option>
            <option value="GENERAL">ศึกษาทั่วไป</option>
            <option value="CORE">วิชาสาขา</option>
            <option value="ELECTIVE">วิชาเลือก</option>
          </select>
        </div>

        <div>
          <label className="block text-[11px] font-semibold text-gray-400 uppercase tracking-wide mb-1.5">
            สาขา
          </label>
          <select
            value={majorFilter}
            onChange={(e) => handleMajorChange(e.target.value as MajorFilter)}
            className="w-full border border-gray-200 rounded-md px-3 py-1.5 text-sm outline-none bg-white focus:border-orange-300 transition-all text-gray-600"
          >
            <option value="ALL">ทุกสาขา</option>
            <option value="CS">{MAJOR_LABELS.CS}</option>
            <option value="IT">{MAJOR_LABELS.IT}</option>
          </select>
        </div>

        <div>
          <label className="block text-[11px] font-semibold text-gray-400 uppercase tracking-wide mb-1.5">
            ชั้นปี
          </label>
          <select
            value={groupFilter}
            onChange={(e) => setGroupFilter(e.target.value)}
            className="w-full border border-gray-200 rounded-md px-3 py-1.5 text-sm outline-none bg-white focus:border-orange-300 transition-all text-gray-600"
          >
            <option value="ALL">-</option>
            {yearOptions.map((g) => (
              <option key={g} value={g}>
                {majorFilter === "ALL" ? `ปี ${g}` : yearLabel(g)}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-[11px] font-semibold text-gray-400 uppercase tracking-wide mb-1.5">
            ภาคการศึกษา
          </label>
          <select
            value={semesterFilter}
            onChange={(e) => setSemesterFilter(e.target.value)}
            className="w-full border border-gray-200 rounded-md px-3 py-1.5 text-sm outline-none bg-white focus:border-orange-300 transition-all text-gray-600"
          >
            <option value="ALL">ทุกภาค</option>
            {semesterOptions.map((s) => (
              <option key={s} value={s}>ภาค {s}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="border border-gray-200 rounded-lg overflow-hidden mt-4">
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50">
              <th className="text-left px-4 py-2.5 text-[11px] font-semibold text-gray-400 uppercase tracking-wide">รหัสวิชา</th>
              <th className="text-left px-4 py-2.5 text-[11px] font-semibold text-gray-400 uppercase tracking-wide">ชื่อวิชา</th>
              <th className="text-left px-4 py-2.5 text-[11px] font-semibold text-gray-400 uppercase tracking-wide">สาขา</th>
              <th className="text-left px-4 py-2.5 text-[11px] font-semibold text-gray-400 uppercase tracking-wide">ชั้นปี</th>
              <th className="text-left px-4 py-2.5 text-[11px] font-semibold text-gray-400 uppercase tracking-wide">ภาคเรียน</th>
              <th className="text-right px-4 py-2.5 text-[11px] font-semibold text-gray-400 uppercase tracking-wide whitespace-nowrap">ประเภท</th>
            </tr>
          </thead>
          <tbody>
            {filteredSubjects.length === 0 ? (
              <tr>
                <td colSpan={6} className="text-center text-sm text-gray-400 py-8">
                  ไม่พบวิชาที่ค้นหา
                </td>
              </tr>
            ) : (
              filteredSubjects.map((s) => {
                const key = `${s.subject_id}-${academicYear}`;
                const takenGroups = existingByKey[key];
                const sectionCount = sectionCountByKey[key] ?? 0;
                const isLocked =
                  s.subject_type === "GENERAL" && !!s.group_id && !!takenGroups?.has(s.group_id);

                return (
                  <tr
                    key={s.subject_id}
                    onClick={() => !isLocked && onSelect(s)}
                    className={`border-b border-gray-50 last:border-0 transition-colors
                      ${isLocked ? "bg-gray-50 cursor-not-allowed" : "hover:bg-orange-50/60 cursor-pointer"}`}
                  >
                    <td className={`px-4 py-3 text-[13px] font-medium ${isLocked ? "text-gray-400" : "text-orange-600"}`}>
                      {s.subject_id}
                    </td>
                    <td className={`px-4 py-3 text-[13px] ${isLocked ? "text-gray-400" : "text-gray-700"}`}>
                      <div className="flex items-center gap-1.5">
                        <span>{s.name_thai}</span>
                        {/* เลขจำนวน section แบบสั้น ๆ (แค่ตัวเลขในวงกลม ไม่ใช่ "N sections")
                            เหมือนที่ใช้ในหน้ารายวิชาที่เปิดสอนแล้ว */}
                        {!isLocked && sectionCount > 0 && (
                          <span className="shrink-0 w-4 h-4 flex items-center justify-center rounded-full bg-gray-100 text-gray-500 text-[10px] font-semibold">
                            {sectionCount}
                          </span>
                        )}
                      </div>
                      {s.name_english && (
                        <div className="text-[11px] text-gray-400 mt-0.5">{s.name_english}</div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-[13px] text-gray-500">{majorOf(s.group_id) ?? "-"}</td>
                    <td className="px-4 py-3 text-[13px] text-gray-500">{yearLabel(s.group_id)}</td>
                    <td className="px-4 py-3 text-[13px] text-gray-500">{s.semester != null ? `ภาค ${s.semester}` : "-"}</td>
                    <td className="px-4 py-3 text-right whitespace-nowrap">
                      {isLocked ? (
                        <span className="text-[13px] text-gray-400 whitespace-nowrap">เปิดสอนแล้ว</span>
                      ) : (
                        <span className="text-[13px] text-gray-600 whitespace-nowrap">
                          {TYPE_LABEL[s.subject_type] ?? s.subject_type}
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}