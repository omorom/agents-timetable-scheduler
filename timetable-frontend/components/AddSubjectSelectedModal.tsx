"use client";

import { useState, useEffect, useMemo } from "react";
import { X, Search, Clock, User, Users, Loader2 } from "lucide-react";
import { API_BASE } from "./types";
import PreferredTimeslotGrid from "./PreferredTimeslotGrid";

interface Subject {
  subject_id: string;
  name_thai: string;
  name_english?: string;
  subject_type: "GENERAL" | "CORE" | "ELECTIVE";
  group_id?: string | null;
  semester?: number | null;
}

interface Teacher {
  teacher_id: string;
  teacher_name: string;
}

interface Timeslot {
  timeslot_id: number;
  day: string;
  start_time: string;
  end_time: string;
}

const ALL_GROUPS = ["Y1", "Y2", "Y3", "Y4"];

function yearLabel(group_id?: string | null): string {
  if (!group_id) return "ทุกชั้นปี";
  const match = group_id.match(/^Y(\d+)$/i);
  return match ? `ปี ${match[1]}` : group_id;
}

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

export default function AddSubjectSelectedModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [teachers, setTeachers] = useState<Teacher[]>([]);
  const [timeslots, setTimeslots] = useState<Timeslot[]>([]);

  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<"ALL" | "GENERAL" | "CORE" | "ELECTIVE">("ALL");
  const [groupFilter, setGroupFilter] = useState<string>("ALL");
  const [semesterFilter, setSemesterFilter] = useState<string>("ALL");
  const [selected, setSelected] = useState<Subject | null>(null);

  const [teacherId, setTeacherId] = useState("");
  const [preferredTimeslotIds, setPreferredTimeslotIds] = useState<Set<string>>(new Set());
  const [maxCapacity, setMaxCapacity] = useState("");
  const [academicYear, setAcademicYear] = useState(String(new Date().getFullYear() + 543));
  const [manualGroups, setManualGroups] = useState<string[]>([]);

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function toggleTimeslot(timeslotId: string) {
    setPreferredTimeslotIds((prev) => {
      const next = new Set(prev);
      if (next.has(timeslotId)) next.delete(timeslotId);
      else next.add(timeslotId);
      return next;
    });
  }

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/subjects`).then((r) => r.json()),
      fetch(`${API_BASE}/teachers`).then((r) => r.json()),
      fetch(`${API_BASE}/timeslots`).then((r) => r.json()),
    ])
      .then(([s, t, ts]) => {
        setSubjects(Array.isArray(s) ? s : []);
        setTeachers(Array.isArray(t) ? t : []);
        setTimeslots(Array.isArray(ts) ? ts : []);
      })
      .catch(() => setError("โหลดข้อมูลตั้งต้นไม่สำเร็จ"));
  }, []);

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

  const isGeneral = selected?.subject_type === "GENERAL";
  const needsManualGroup = !!selected && selected.group_id == null;

  // ใช้เช็ค student_unavailability ได้ก็ต่อเมื่อรู้ชั้นปีแน่ชัดแค่ 1 ชั้นปีเท่านั้น
  // (ถ้าผูกตายตัวอยู่แล้ว หรือเลือก manual มาแค่ปีเดียว)
  const resolvedGroupId =
    selected?.group_id ?? (manualGroups.length === 1 ? manualGroups[0] : null);

  function toggleGroup(g: string) {
    setManualGroups((prev) => (prev.includes(g) ? prev.filter((x) => x !== g) : [...prev, g]));
  }

  async function handleSave() {
    if (!selected) return;
    if (needsManualGroup && manualGroups.length === 0) {
      setError("ต้องเลือกชั้นปีที่เปิดสอนอย่างน้อย 1 ชั้นปี");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const cleanTimeslotIds = Array.from(preferredTimeslotIds).map((v) => Number(v));

      const res = await fetch(`${API_BASE}/subject-selected`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subject_id: selected.subject_id,
          teacher_id: isGeneral ? null : teacherId || null,
          study_date: null,
          preferred_timeslot_ids: isGeneral ? cleanTimeslotIds : [],
          max_capacity: isGeneral ? null : maxCapacity ? Number(maxCapacity) : null,
          academic_year: Number(academicYear),
          group_ids: needsManualGroup ? manualGroups : null,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "บันทึกไม่สำเร็จ");
      }
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : "บันทึกไม่สำเร็จ กรุณาลองใหม่");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 bg-black/40 backdrop-blur-[2px] z-50 flex items-center justify-center animate-fade-up p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-2xl w-full max-w-6xl max-h-[90vh] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between px-7 pt-6 pb-5 border-b border-gray-100">
          <div>
            <h3 className="text-[17px] font-bold text-gray-900">เพิ่มรายวิชาที่เปิดสอน</h3>
            <p className="text-[13px] text-gray-400 mt-1">
              {selected ? `${selected.subject_id} · ${selected.name_thai}` : "เลือกวิชาที่ต้องการเปิดสอน"}
            </p>
          </div>
          <button onClick={onClose} className="text-gray-300 hover:text-gray-500 transition-colors cursor-pointer">
            <X size={20} />
          </button>
        </div>

        <div className="px-7 py-5 overflow-y-auto">
          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-2.5 text-red-600 text-[13px] mb-4">
              {error}
            </div>
          )}

          {!selected ? (
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

              {/* แถวตัวกรอง: ประเภทวิชา / ชั้นปี / ภาคการศึกษา */}
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
                  <tbody className="max-h-64 overflow-y-auto">
                    {filteredSubjects.length === 0 ? (
                      <tr>
                        <td colSpan={5} className="text-center text-sm text-gray-400 py-8">
                          ไม่พบวิชาที่ค้นหา
                        </td>
                      </tr>
                    ) : (
                      filteredSubjects.map((s) => (
                        <tr
                          key={s.subject_id}
                          onClick={() => setSelected(s)}
                          className="border-b border-gray-50 last:border-0 hover:bg-orange-50/60 transition-colors cursor-pointer"
                        >
                          <td className="px-4 py-3 text-[13px] font-medium text-orange-600">{s.subject_id}</td>
                          <td className="px-4 py-3 text-[13px] text-gray-700">{s.name_thai}</td>
                          <td className="px-4 py-3 text-[13px] text-gray-500">{yearLabel(s.group_id)}</td>
                          <td className="px-4 py-3 text-[13px] text-gray-500">{s.semester != null ? `ภาค ${s.semester}` : "-"}</td>
                          <td className="px-4 py-3 text-right whitespace-nowrap">
                            <span className={`text-[11px] font-bold px-2.5 py-1 rounded-full whitespace-nowrap ${TYPE_CHIP[s.subject_type] ?? "bg-gray-50 text-gray-600"}`}>
                              {TYPE_LABEL[s.subject_type] ?? s.subject_type}
                            </span>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <div>
              <button
                onClick={() => setSelected(null)}
                className="text-xs text-orange-500 hover:underline mb-4 cursor-pointer"
              >
                ← เลือกวิชาอื่น
              </button>

              {needsManualGroup && (
                <div className="mb-4">
                  <label className="flex items-center gap-1.5 text-xs font-semibold text-gray-500 mb-2">
                    <Users size={13} />
                    ชั้นปีที่เปิดสอนรายวิชา
                  </label>
                  <div className="flex gap-1.5">
                    {ALL_GROUPS.map((g) => (
                      <button
                        key={g}
                        onClick={() => toggleGroup(g)}
                        className={`px-3 py-1.5 rounded-lg text-sm border cursor-pointer transition-colors ${manualGroups.includes(g)
                            ? "border-orange-300 bg-orange-50 text-orange-600"
                            : "border-gray-200 text-gray-500 hover:bg-gray-50"
                          }`}
                      >
                        {g}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {isGeneral ? (
                <div className="mb-4">
                  <label className="flex items-center gap-1.5 text-xs font-semibold text-gray-500 mb-2">
                    <Clock size={13} />
                    คาบที่มีการจัดการเรียนการสอน
                  </label>
                  <PreferredTimeslotGrid
                    timeslots={timeslots}
                    selected={preferredTimeslotIds}
                    onToggle={toggleTimeslot}
                    groupId={resolvedGroupId}
                  />
                </div>
              ) : (
                <div className="max-w-md">
                  <label className="flex items-center gap-1.5 text-xs font-semibold text-gray-500 mb-2">
                    <User size={13} />
                    อาจารย์ผู้สอน
                  </label>
                  <select
                    value={teacherId}
                    onChange={(e) => setTeacherId(e.target.value)}
                    className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm outline-none bg-white focus:border-orange-300 focus:ring-4 focus:ring-orange-50 transition-all text-gray-600"
                  >
                    <option value="">ยังไม่ระบุ</option>
                    {teachers.map((t) => (
                      <option key={t.teacher_id} value={t.teacher_id}>
                        {t.teacher_name}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {!isGeneral && (
                <div className="grid grid-cols-2 gap-3 mb-1 max-w-md">
                  <div>
                    <label className="block text-xs font-semibold text-gray-500 mb-2">จำนวนที่นั่งสูงสุด</label>
                    <input
                      type="number"
                      value={maxCapacity}
                      onChange={(e) => setMaxCapacity(e.target.value)}
                      placeholder="เช่น 75"
                      className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm outline-none bg-white focus:border-orange-300 focus:ring-4 focus:ring-orange-50 transition-all"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-gray-500 mb-2">ปีการศึกษา</label>
                    <input
                      type="number"
                      value={academicYear}
                      onChange={(e) => setAcademicYear(e.target.value)}
                      className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm outline-none bg-white focus:border-orange-300 focus:ring-4 focus:ring-orange-50 transition-all"
                    />
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {selected && (
          <div className="px-7 py-4 border-t border-gray-100 flex gap-2.5 justify-end">
            <button
              onClick={onClose}
              className="px-5 py-2.5 rounded-xl border border-gray-200 text-gray-600 text-sm font-semibold hover:bg-gray-50 cursor-pointer transition-colors"
            >
              ยกเลิก
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-6 py-2.5 rounded-xl bg-orange-500 hover:bg-orange-600 text-white text-sm font-semibold cursor-pointer disabled:bg-orange-200 transition-colors flex items-center justify-center gap-1.5"
            >
              {saving ? (
                <>
                  <Loader2 size={14} className="animate-spin" /> กำลังบันทึก...
                </>
              ) : (
                "บันทึกการเปิดสอน"
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}