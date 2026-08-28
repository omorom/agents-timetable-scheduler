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

const ALL_GROUPS = ["Y1", "Y2", "Y3", "Y4"];

const GROUP_LABEL: Record<string, string> = {
  Y1: "ปี 1",
  Y2: "ปี 2",
  Y3: "ปี 3",
  Y4: "ปี 4",
};

const TYPE_LABEL: Record<string, string> = {
  GENERAL: "ศึกษาทั่วไป",
  CORE: "วิชาสาขา",
  ELECTIVE: "วิชาเลือก",
};

const TYPE_CHIP: Record<string, string> = {
  GENERAL: "bg-purple-50 text-purple-600",
  CORE: "bg-emerald-50 text-emerald-600",
  ELECTIVE: "bg-blue-50 text-blue-600",
};

// แปลง group_id (Y1, Y2, ...) เป็น "ปี 1", "ปี 2" ... สำหรับแสดงผล
export function yearLabel(group_id?: string | null): string {
  if (!group_id) return "ทุกชั้นปี";
  const match = group_id.match(/^Y(\d+)$/i);
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
  const [groupFilter, setGroupFilter] = useState<string>("ALL");
  const [semesterFilter, setSemesterFilter] = useState<string>("ALL");

  const semesterOptions = useMemo(() => {
    const set = new Set<number>();
    subjects.forEach((s) => { if (s.semester != null) set.add(s.semester); });
    return Array.from(set).sort((a, b) => a - b);
  }, [subjects]);

  const filteredSubjects = useMemo(() => {
    const q = search.trim().toLowerCase();
    return subjects.filter((s) => {
      const matchesType = typeFilter === "ALL" || s.subject_type === typeFilter;
      const matchesGroup = groupFilter === "ALL" || s.group_id === groupFilter;
      const matchesSemester = semesterFilter === "ALL" || String(s.semester ?? "") === semesterFilter;
      const matchesSearch =
        !q ||
        s.subject_id.toLowerCase().includes(q) ||
        s.name_thai.toLowerCase().includes(q) ||
        (s.name_english || "").toLowerCase().includes(q);
      return matchesType && matchesGroup && matchesSemester && matchesSearch;
    });
  }, [subjects, search, typeFilter, groupFilter, semesterFilter]);

  return (
    <>
      <div className="relative mb-4">
        <Search size={17} className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-300" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="พิมพ์รหัสวิชาหรือชื่อวิชา"
          className="w-full border border-gray-200 rounded-lg pl-11 pr-4 py-3 text-sm outline-none bg-white focus:border-orange-300 focus:ring-4 focus:ring-orange-50 transition-all placeholder:text-gray-400"
        />
      </div>

      <div className="grid grid-cols-3 gap-3 mb-2">
        <div>
          <label className="block text-[11px] font-semibold text-gray-400 uppercase tracking-wide mb-1.5">
            ประเภทวิชา
          </label>
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as typeof typeFilter)}
            className="w-full border border-gray-200 rounded-md px-3 py-1.5 text-sm outline-none bg-white focus:border-orange-300 focus:ring-4 focus:ring-orange-50 transition-all text-gray-600"
          >
            <option value="ALL">ทุกประเภท</option>
            <option value="GENERAL">ศึกษาทั่วไป</option>
            <option value="CORE">วิชาสาขา</option>
            <option value="ELECTIVE">วิชาเลือก</option>
          </select>
        </div>

        <div>
          <label className="block text-[11px] font-semibold text-gray-400 uppercase tracking-wide mb-1.5">
            ชั้นปี
          </label>
          <select
            value={groupFilter}
            onChange={(e) => setGroupFilter(e.target.value)}
            className="w-full border border-gray-200 rounded-md px-3 py-1.5 text-sm outline-none bg-white focus:border-orange-300 focus:ring-4 focus:ring-orange-50 transition-all text-gray-600"
          >
            <option value="ALL">ทุกชั้นปี</option>
            {ALL_GROUPS.map((g) => (
              <option key={g} value={g}>{yearLabel(g)}</option>
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
            className="w-full border border-gray-200 rounded-md px-3 py-1.5 text-sm outline-none bg-white focus:border-orange-300 focus:ring-4 focus:ring-orange-50 transition-all text-gray-600"
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
              <th className="text-left px-4 py-2.5 text-[11px] font-semibold text-gray-400 uppercase tracking-wide">ชั้นปี</th>
              <th className="text-left px-4 py-2.5 text-[11px] font-semibold text-gray-400 uppercase tracking-wide">ภาคเรียน</th>
              <th className="text-right px-4 py-2.5 text-[11px] font-semibold text-gray-400 uppercase tracking-wide whitespace-nowrap">ประเภท</th>
            </tr>
          </thead>
          <tbody>
            {filteredSubjects.length === 0 ? (
              <tr>
                <td colSpan={5} className="text-center text-sm text-gray-400 py-8">
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
                      <span>{s.name_thai}</span>
                      {!isLocked && sectionCount > 0 && (
                        <span
                          className={`ml-2 text-[10px] font-semibold px-1.5 py-0.5 rounded ${TYPE_CHIP[s.subject_type] ?? "bg-gray-50 text-gray-500"}`}
                        >
                          {sectionCount} section
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-[13px] text-gray-500">{yearLabel(s.group_id)}</td>
                    <td className="px-4 py-3 text-[13px] text-gray-500">{s.semester != null ? `ภาค ${s.semester}` : "-"}</td>
                    <td className="px-4 py-3 text-right whitespace-nowrap">
                      {isLocked ? (
                        <span className="text-[11px] font-bold px-2.5 py-1 rounded-full bg-gray-100 text-gray-400 whitespace-nowrap">
                          เปิดสอนแล้ว
                        </span>
                      ) : (
                        <span className={`text-[11px] font-bold px-2.5 py-1 rounded-full whitespace-nowrap ${TYPE_CHIP[s.subject_type] ?? "bg-gray-50 text-gray-600"}`}>
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