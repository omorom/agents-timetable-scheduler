"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { RefreshCw, AlertCircle, BookOpen, Plus, Trash2, Search, Loader2 } from "lucide-react";
import { API_BASE } from "../../components/types";
import SubjectSelectedFormModal from "../../components/SubjectSelectedFormModal";

interface Subject {
  subject_id: string;
  name_thai: string;
  name_english?: string;
  subject_type: "GENERAL" | "CORE" | "ELECTIVE";
  group_id?: string | null;
  semester?: number | null;
  [key: string]: unknown;
}

interface Teacher {
  teacher_id: string;
  teacher_name: string;
}

interface SubjectSelected {
  id: number;
  subjects: Subject;
  teachers: Teacher[];
  group_ids: string[];
  max_capacity?: number | null;
  academic_year: number;
  [key: string]: unknown;
}

type TypeFilter = "ALL" | "GENERAL" | "CORE" | "ELECTIVE";
const ALL_GROUPS = ["Y1", "Y2", "Y3", "Y4"];

function yearLabel(group_id: string): string {
  const match = group_id.match(/^Y(\d+)$/i);
  return match ? `ปี ${match[1]}` : group_id;
}

const TYPE_LABEL: Record<string, string> = {
  GENERAL: "ศึกษาทั่วไป",
  CORE: "วิชาสาขา",
  ELECTIVE: "วิชาเลือก",
};

const TYPE_BADGE: Record<string, string> = {
  GENERAL: "bg-purple-50 text-purple-600",
  CORE: "bg-emerald-50 text-emerald-600",
  ELECTIVE: "bg-blue-50 text-blue-600",
};

export default function SubjectSelectedPage() {
  const [rows, setRows] = useState<SubjectSelected[]>([]);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("ALL");
  const [groupFilter, setGroupFilter] = useState<string>("ALL");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showAddModal, setShowAddModal] = useState(false);
  const [editingGroup, setEditingGroup] = useState<SubjectSelected[] | null>(null);
  const [deletingRow, setDeletingRow] = useState<SubjectSelected | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [showClearAllModal, setShowClearAllModal] = useState(false);
  const [clearingAll, setClearingAll] = useState(false);
  // เก็บ index ของ "กลุ่ม" (ไม่ใช่ row) ที่กำลัง hover อยู่ — ใช้แทน CSS :hover ตรงๆ
  // เพราะแต่ละ section ในกลุ่มเดียวกันเป็นคนละ <tr> (merge กันแค่ผ่าน rowSpan) ถ้าใช้
  // hover:bg-* ปกติ จะไฮไลต์แค่ <tr> ที่ mouse อยู่จริง ทำให้คอลัมน์ที่ถูก rowSpan ไป
  // (รหัสวิชา/ชื่อวิชา/ชั้นปี/ประเภท ซึ่งอยู่ใน <tr> แรกของกลุ่มเท่านั้น) ไม่ไฮไลต์ตาม
  // ดูไม่ต่อเนื่องเป็นก้อนเดียวกัน ต้อง sync สถานะ hover ทั้งกลุ่มด้วย state แทน
  const [hoveredGroupIndex, setHoveredGroupIndex] = useState<number | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE}/subject-selected`);
      const data = await res.json();
      setRows(Array.isArray(data) ? data : []);
    } catch {
      setError("ไม่สามารถโหลดข้อมูลได้ กรุณาตรวจสอบการเชื่อมต่อ API");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows.filter((row) => {
      const s = row.subjects;
      const matchesType = typeFilter === "ALL" || s.subject_type === typeFilter;
      const matchesGroup = groupFilter === "ALL" || row.group_ids.includes(groupFilter);
      const matchesSearch =
        !q ||
        s.subject_id.toLowerCase().includes(q) ||
        s.name_thai.toLowerCase().includes(q);
      return matchesType && matchesGroup && matchesSearch;
    });
  }, [rows, search, typeFilter, groupFilter]);

  // จัดกลุ่ม section คู่ขนาน (subject_id + academic_year เดียวกัน คนละอาจารย์) ไว้ด้วยกัน
  // เพื่อโชว์ข้อมูลวิชา/ชั้นปี/ภาคเรียน/ประเภท แค่ครั้งเดียวต่อกลุ่ม (ใช้ rowSpan) แทนที่จะ
  // ซ้ำกันทุกแถว — ไม่แตะโครงสร้างข้อมูลเลย แต่ละ section ยังเป็นคนละ record เหมือนเดิม
  // ยัง edit/delete แยกทีละ section ได้ปกติ (แต่ละแถวย่อยยังคลิกแก้ไข record ของตัวเองอยู่)
  const groupedRows = useMemo(() => {
    const groups = new Map<string, SubjectSelected[]>();
    for (const row of filtered) {
      const key = `${row.subjects.subject_id}-${row.academic_year}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(row);
    }
    return Array.from(groups.values());
  }, [filtered]);

  async function confirmDelete() {
    if (!deletingRow) return;
    setDeleting(true);
    try {
      await fetch(`${API_BASE}/subject-selected/${deletingRow.id}`, { method: "DELETE" });
      setRows((prev) => prev.filter((r) => r.id !== deletingRow.id));
      setDeletingRow(null);
    } catch {
      setError("ลบไม่สำเร็จ กรุณาลองใหม่");
    } finally {
      setDeleting(false);
    }
  }

  async function confirmClearAll() {
    setClearingAll(true);
    try {
      await Promise.all(
        filtered.map((row) =>
          fetch(`${API_BASE}/subject-selected/${row.id}`, { method: "DELETE" })
        )
      );
      const clearedIds = new Set(filtered.map((r) => r.id));
      setRows((prev) => prev.filter((r) => !clearedIds.has(r.id)));
      setShowClearAllModal(false);
    } catch {
      setError("ล้างข้อมูลไม่สำเร็จ กรุณาลองใหม่");
    } finally {
      setClearingAll(false);
    }
  }

  return (
    <main className="flex-1 overflow-y-auto px-6 py-8">
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-red-600 text-sm mb-5 flex items-center gap-2">
          <AlertCircle size={15} className="shrink-0" />
          {error}
        </div>
      )}

      {/* Page title + actions */}
      <div className="flex items-end justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-gray-900">รายวิชาที่เปิดสอน</h1>
          <p className="text-[13px] text-gray-400 mt-0.5">ภาควิชาวิทยาการคอมพิวเตอร์และเทคโนโลยีสารสนเทศ</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={loadData}
            disabled={loading}
            className="flex items-center gap-1.5 bg-white hover:bg-gray-50 text-gray-600 border border-gray-200 rounded-lg px-3.5 py-1.5 text-sm font-medium cursor-pointer transition-colors disabled:opacity-50"
          >
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
            รีเฟรช
          </button>
          <button
            onClick={() => setShowClearAllModal(true)}
            disabled={rows.length === 0}
            className="flex items-center gap-1.5 bg-white hover:bg-red-50 text-red-500 border border-red-200 rounded-lg px-3.5 py-1.5 text-sm font-medium cursor-pointer transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Trash2 size={13} />
            ล้างทั้งหมด
          </button>
          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-1.5 bg-orange-500 hover:bg-orange-600 text-white rounded-lg px-3.5 py-1.5 text-sm font-semibold cursor-pointer transition-colors"
          >
            <Plus size={15} />
            เพิ่มรายวิชา
          </button>
        </div>
      </div>

      {/* Search + type filter */}
      <div className="flex items-center gap-3 mb-4">
        <div className="relative flex-1">
          <Search size={16} className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-300" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="ค้นหารายวิชา เช่น รหัสวิชา, ชื่อวิชา..."
            className="w-full border border-gray-200 rounded-xl pl-11 pr-4 py-3 text-sm outline-none bg-white focus:border-orange-300 focus:ring-4 focus:ring-orange-50 transition-all placeholder:text-gray-400"
          />
        </div>
        <select
          value={groupFilter}
          onChange={(e) => setGroupFilter(e.target.value)}
          className="border border-gray-200 rounded-xl px-4 py-3 text-sm outline-none bg-white focus:border-orange-300 focus:ring-4 focus:ring-orange-50 transition-all text-gray-600"
        >
          <option value="ALL">ทุกชั้นปี</option>
          {ALL_GROUPS.map((g) => (
            <option key={g} value={g}>{yearLabel(g)}</option>
          ))}
        </select>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value as TypeFilter)}
          className="border border-gray-200 rounded-xl px-4 py-3 text-sm outline-none bg-white focus:border-orange-300 focus:ring-4 focus:ring-orange-50 transition-all text-gray-600"
        >
          <option value="ALL">ทั้งหมด</option>
          <option value="GENERAL">ศึกษาทั่วไป</option>
          <option value="CORE">วิชาสาขา</option>
          <option value="ELECTIVE">วิชาเลือก</option>
        </select>
      </div>

      {/* Content */}
      <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-100 text-[13px] font-semibold text-gray-600">
          รายวิชาที่เปิดสอน ({filtered.length}{filtered.length !== rows.length ? ` / ${rows.length}` : ""})
        </div>

        {loading ? (
          <div className="p-5 space-y-2">
            {[1, 2, 3, 4].map((n) => <div key={n} className="skeleton h-10 w-full rounded-lg" />)}
          </div>
        ) : (
          <table className="w-full border-collapse table-fixed">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="text-left px-5 py-2.5 text-[12px] font-medium text-gray-400 w-[10%]">รหัสวิชา</th>
                <th className="text-left px-5 py-2.5 text-[12px] font-medium text-gray-400 w-[22%]">ชื่อวิชา</th>
                <th className="text-left px-5 py-2.5 text-[12px] font-medium text-gray-400 w-[8%]">ชั้นปี</th>
                <th className="text-left px-5 py-2.5 text-[12px] font-medium text-gray-400 w-[10%]">ภาคเรียน</th>
                <th className="text-left px-5 py-2.5 text-[12px] font-medium text-gray-400 w-[20%]">อาจารย์</th>
                <th className="text-right px-5 py-2.5 text-[12px] font-medium text-gray-400 w-[10%]">จำนวนที่นั่ง</th>
                <th className="text-center px-5 py-2.5 text-[12px] font-medium text-gray-400 w-[12%]">ประเภท</th>
                <th className="text-right px-5 py-2.5 text-[12px] font-medium text-gray-400 w-[6%]">จัดการ</th>
              </tr>
            </thead>
            <tbody>
              {groupedRows.length === 0 ? (
                <tr>
                  <td colSpan={8} className="text-center text-sm text-gray-400 py-8">
                    ไม่พบรายวิชา
                  </td>
                </tr>
              ) : (
                groupedRows.map((group, gi) => {
                  const first = group[0];
                  const isMultiSection = group.length > 1;

                  return group.map((row, ri) => (
                    <tr
                      key={row.id}
                      onClick={() => setEditingGroup(group)}
                      onMouseEnter={() => setHoveredGroupIndex(gi)}
                      onMouseLeave={() => setHoveredGroupIndex((cur) => (cur === gi ? null : cur))}
                      className={`transition-colors cursor-pointer align-top
                        ${hoveredGroupIndex === gi ? "bg-orange-50/60" : ""}
                        ${ri === group.length - 1 ? "border-b border-gray-50" : isMultiSection ? "border-b border-dashed border-gray-100" : "border-b border-gray-50"}
                        ${gi === groupedRows.length - 1 && ri === group.length - 1 ? "last:border-0" : ""}`}
                    >
                      {/* คอลัมน์ร่วม: โชว์แค่แถวแรกของกลุ่ม ครอบด้วย rowSpan ให้ครอบคลุมทุก section */}
                      {ri === 0 && (
                        <>
                          <td rowSpan={group.length} className="px-5 py-3 text-[13px] text-orange-600 font-medium border-r border-gray-50/70">
                            {first.subjects.subject_id}
                          </td>
                          <td rowSpan={group.length} className="px-5 py-3 text-[13px] text-gray-700 truncate border-r border-gray-50/70">
                            <div className="flex items-center gap-1.5">
                              <span>{first.subjects.name_thai}</span>
                              {isMultiSection && (
                                <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 shrink-0">
                                  {group.length} sections
                                </span>
                              )}
                            </div>
                          </td>
                          <td rowSpan={group.length} className="px-5 py-3 text-[13px] text-gray-600 border-r border-gray-50/70">
                            {first.group_ids.map(yearLabel).join(", ") || "-"}
                          </td>
                          <td rowSpan={group.length} className="px-5 py-3 text-[13px] text-gray-500 border-r border-gray-50/70">
                            {first.subjects.semester != null ? `ภาคเรียนที่ ${first.subjects.semester}` : "-"}
                          </td>
                        </>
                      )}

                      {/* คอลัมน์เฉพาะ section: อาจารย์ + จำนวนที่นั่ง ต่างกันแต่ละแถว */}
                      <td className="px-5 py-3 text-[13px] text-gray-600">
                        {row.teachers?.length ? (
                          <div className="space-y-0.5">
                            {row.teachers.map((t) => (
                              <div key={t.teacher_id} className="truncate">{t.teacher_name}</div>
                            ))}
                          </div>
                        ) : (
                          "-"
                        )}
                      </td>
                      <td className="px-5 py-3 text-[13px] text-gray-600 text-right">{row.max_capacity ?? "-"}</td>

                      {/* คอลัมน์ร่วมอีกชุด: ประเภท (เหมือนกันทุก section แน่นอน) */}
                      {ri === 0 && (
                        <td rowSpan={group.length} className="px-5 py-3 text-center border-l border-gray-50/70">
                          <span className={`text-[11px] font-bold px-2.5 py-1 rounded-full ${TYPE_BADGE[first.subjects.subject_type] ?? "bg-gray-50 text-gray-600"}`}>
                            {TYPE_LABEL[first.subjects.subject_type] ?? first.subjects.subject_type}
                          </span>
                        </td>
                      )}

                      <td className="px-5 py-3 text-right">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setDeletingRow(row);
                          }}
                          className="text-gray-300 hover:text-red-500 transition-colors cursor-pointer"
                          title="ลบ section นี้"
                        >
                          <Trash2 size={15} />
                        </button>
                      </td>
                    </tr>
                  ));
                })
              )}
            </tbody>
          </table>
        )}
      </div>

      {showAddModal && (
        <SubjectSelectedFormModal
          mode="add"
          onClose={() => setShowAddModal(false)}
          onSaved={() => {
            setShowAddModal(false);
            loadData();
          }}
        />
      )}

      {editingGroup && (
        <SubjectSelectedFormModal
          mode="edit"
          rows={editingGroup}
          onClose={() => setEditingGroup(null)}
          onSaved={() => {
            setEditingGroup(null);
            loadData();
          }}
        />
      )}

      {deletingRow && (
        <div
          className="fixed inset-0 bg-black/30 backdrop-blur-[2px] z-50 flex items-center justify-center animate-fade-up p-4"
          onClick={() => !deleting && setDeletingRow(null)}
        >
          <div className="bg-white rounded-2xl shadow-2xl p-6 w-96" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-[15px] font-bold text-gray-900 mb-1.5">ลบรายวิชานี้ออกจากการเปิดสอน?</h3>
            <p className="text-sm text-gray-500 mb-5 leading-relaxed">
              <span className="font-medium text-gray-700">
                {deletingRow.subjects.subject_id} · {deletingRow.subjects.name_thai}
              </span>
            </p>

            <div className="flex gap-2.5">
              <button
                onClick={() => setDeletingRow(null)}
                disabled={deleting}
                className="flex-1 py-2.5 rounded-xl border border-gray-200 text-gray-600 text-sm font-medium hover:bg-gray-50 cursor-pointer transition-colors disabled:opacity-50"
              >
                ยกเลิก
              </button>
              <button
                onClick={confirmDelete}
                disabled={deleting}
                className="flex-1 py-2.5 rounded-xl bg-red-500 hover:bg-red-600 text-white text-sm font-medium cursor-pointer disabled:opacity-50 transition-colors flex items-center justify-center gap-1.5"
              >
                {deleting ? (
                  <>
                    <Loader2 size={14} className="animate-spin" /> กำลังลบ...
                  </>
                ) : (
                  "ลบ"
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {showClearAllModal && (
        <div
          className="fixed inset-0 bg-black/30 backdrop-blur-[2px] z-50 flex items-center justify-center animate-fade-up p-4"
          onClick={() => !clearingAll && setShowClearAllModal(false)}
        >
          <div className="bg-white rounded-2xl shadow-2xl p-6 w-96" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-[15px] font-bold text-gray-900 mb-1.5">ล้างรายวิชาทั้งหมดออกจากการเปิดสอน?</h3>
            <p className="text-sm text-gray-500 mb-5 leading-relaxed">
              การดำเนินการนี้จะลบรายวิชาที่แสดงอยู่ทั้งหมด และไม่สามารถย้อนกลับได้
            </p>

            <div className="flex gap-2.5">
              <button
                onClick={() => setShowClearAllModal(false)}
                disabled={clearingAll}
                className="flex-1 py-2.5 rounded-xl border border-gray-200 text-gray-600 text-sm font-medium hover:bg-gray-50 cursor-pointer transition-colors disabled:opacity-50"
              >
                ยกเลิก
              </button>
              <button
                onClick={confirmClearAll}
                disabled={clearingAll}
                className="flex-1 py-2.5 rounded-xl bg-red-500 hover:bg-red-600 text-white text-sm font-medium cursor-pointer disabled:opacity-50 transition-colors flex items-center justify-center gap-1.5"
              >
                {clearingAll ? (
                  <>
                    <Loader2 size={14} className="animate-spin" /> กำลังล้าง...
                  </>
                ) : (
                  "ล้างทั้งหมด"
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}