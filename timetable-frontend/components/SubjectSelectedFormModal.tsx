"use client";

import { useState, useEffect } from "react";
import { X, Clock, User, Users, Loader2 } from "lucide-react";
import { API_BASE, Timeslot } from "./types";
import PreferredTimeslotGrid from "./PreferredTimeslotGrid";
import SubjectPickerTable, { Subject } from "./SubjectPickerTable";
import SectionTeacherEditor, { Teacher, Section, Room, hasAnyDuplicateTeacher } from "./SectionTeacherEditor";

interface Group {
  group_id: string;
  group_name: string;
  total_students: number;
}

interface SubjectSelectedRow {
  id: number;
  subjects: Subject;
  group_ids: string[];
  teachers?: Teacher[];
  max_capacity?: number | null;
  academic_year: number;
  subject_selected_preferred_timeslots?: { timeslot_id: number }[];
  is_lecture_combined?: boolean;
  fixed_room_id?: string | null;
}

const ALL_GROUPS = ["Y1", "Y2", "Y3", "Y4"];

const GROUP_LABEL: Record<string, string> = {
  Y1: "ปี 1",
  Y2: "ปี 2",
  Y3: "ปี 3",
  Y4: "ปี 4",
};

type Props =
  | { mode: "add"; onClose: () => void; onSaved: () => void; rows?: undefined }
  // mode "edit" รับ "ทั้งกลุ่ม" section คู่ขนาน (subject_id + academic_year เดียวกัน) พร้อมกัน
  // ไม่ใช่แค่ record เดียวเหมือนเดิม — ให้แก้ไข/เพิ่ม/ลบ section ได้ครบเหมือนตอน add
  | { mode: "edit"; onClose: () => void; onSaved: () => void; rows: SubjectSelectedRow[] };

export default function SubjectSelectedFormModal(props: Props) {
  const { mode, onClose, onSaved } = props;
  const editingRows = mode === "edit" ? props.rows : null;
  const firstEditingRow = editingRows?.[0] ?? null;
  const isMultiSectionEdit = mode === "edit";

  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [teachers, setTeachers] = useState<Teacher[]>([]);
  const [timeslots, setTimeslots] = useState<Timeslot[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [existingByKey, setExistingByKey] = useState<Record<string, Set<string>>>({});
  const [sectionCountByKey, setSectionCountByKey] = useState<Record<string, number>>({});

  const [selected, setSelected] = useState<Subject | null>(firstEditingRow?.subjects ?? null);

  // สร้าง section เริ่มต้นจากทุก row ในกลุ่ม (ตอน edit) — เก็บ existingId ไว้ในแต่ละ section
  // เพื่อรู้ว่าตอน save ต้อง PATCH ตัวไหน (มี existingId) หรือ POST ใหม่ (ไม่มี existingId
  // เพราะ user กด "เพิ่ม section ใหม่" ระหว่างแก้ไข)
  const [sections, setSections] = useState<Section[]>(
    editingRows && editingRows.length > 0
      ? editingRows.map((r) => ({
          teacherIds: r.teachers && r.teachers.length > 0 ? r.teachers.map((t) => t.teacher_id) : [""],
          maxCapacity: r.max_capacity != null ? String(r.max_capacity) : "",
          fixedRoomId: r.fixed_room_id ?? "",
          existingId: r.id,
        }))
      : [{ teacherIds: [""], maxCapacity: "", fixedRoomId: "" }]
  );
  const [lectureCombined, setLectureCombined] = useState(firstEditingRow?.is_lecture_combined ?? false);
  const [preferredTimeslotIds, setPreferredTimeslotIds] = useState<Set<string>>(
    new Set((firstEditingRow?.subject_selected_preferred_timeslots ?? []).map((t) => String(t.timeslot_id)))
  );
  const [academicYear] = useState(
    firstEditingRow ? String(firstEditingRow.academic_year) : String(new Date().getFullYear() + 543)
  );
  const [manualGroups, setManualGroups] = useState<string[]>(
    firstEditingRow && firstEditingRow.subjects.group_id == null ? firstEditingRow.group_ids : []
  );

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function addSection() {
    setSections((prev) => [
      ...prev,
      {
        teacherIds: [""],
        maxCapacity: fixedGroupStudentCount != null ? String(fixedGroupStudentCount) : "",
        fixedRoomId: "",
      },
    ]);
  }

  function removeSection(idx: number) {
    setSections((prev) => prev.filter((_, i) => i !== idx));
  }

  function updateCapacity(idx: number, value: string) {
    setSections((prev) => prev.map((s, i) => (i === idx ? { ...s, maxCapacity: value } : s)));
  }

  function updateFixedRoom(idx: number, roomId: string) {
    setSections((prev) => prev.map((s, i) => (i === idx ? { ...s, fixedRoomId: roomId } : s)));
  }

  function distributeEvenly() {
    if (fixedGroupStudentCount == null) return;
    const n = sections.length;
    if (n === 0) return;
    const base = Math.floor(fixedGroupStudentCount / n);
    const remainder = fixedGroupStudentCount % n;
    setSections((prev) =>
      prev.map((s, i) => ({ ...s, maxCapacity: String(base + (i < remainder ? 1 : 0)) }))
    );
  }

  function addCoTeacher(sectionIdx: number) {
    setSections((prev) =>
      prev.map((s, i) => (i === sectionIdx ? { ...s, teacherIds: [...s.teacherIds, ""] } : s))
    );
  }

  function updateTeacher(sectionIdx: number, teacherIdx: number, value: string) {
    setSections((prev) =>
      prev.map((s, i) =>
        i === sectionIdx
          ? { ...s, teacherIds: s.teacherIds.map((t, ti) => (ti === teacherIdx ? value : t)) }
          : s
      )
    );
  }

  function removeTeacher(sectionIdx: number, teacherIdx: number) {
    setSections((prev) =>
      prev.map((s, i) =>
        i === sectionIdx ? { ...s, teacherIds: s.teacherIds.filter((_, ti) => ti !== teacherIdx) } : s
      )
    );
  }

  function toggleLectureCombined() {
    setLectureCombined((v) => !v);
  }

  useEffect(() => {
    const requests = [
      fetch(`${API_BASE}/subjects`).then((r) => r.json()),
      fetch(`${API_BASE}/teachers`).then((r) => r.json()),
      fetch(`${API_BASE}/timeslots`).then((r) => r.json()),
      fetch(`${API_BASE}/subject-selected`).then((r) => r.json()),
      fetch(`${API_BASE}/groups`).then((r) => r.json()),
      fetch(`${API_BASE}/rooms`).then((r) => r.json()),
    ];
    Promise.all(requests)
      .then(([s, t, ts, existing, g, rm]) => {
        setSubjects(Array.isArray(s) ? s : []);
        setTeachers(Array.isArray(t) ? t : []);
        setTimeslots(Array.isArray(ts) ? ts : []);
        setGroups(Array.isArray(g) ? g : []);
        setRooms(Array.isArray(rm) ? rm : []);

        const editingIds = new Set((editingRows ?? []).map((r) => r.id));
        const map: Record<string, Set<string>> = {};
        const countMap: Record<string, number> = {};
        for (const row of Array.isArray(existing) ? existing : []) {
          // ตอน edit ไม่ต้องนับ record ของกลุ่มตัวเอง ไม่งั้นจะโดน lock วิชาตัวเองผิด ๆ
          if (mode === "edit" && editingIds.has(row.id)) continue;
          const key = `${row.subject_id}-${row.academic_year}`;
          if (!map[key]) map[key] = new Set();
          for (const g of row.group_ids ?? []) map[key].add(g);
          countMap[key] = (countMap[key] ?? 0) + 1;
        }
        setExistingByKey(map);
        setSectionCountByKey(countMap);
      })
      .catch(() => setError("โหลดข้อมูลตั้งต้นไม่สำเร็จ"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const isGeneral = selected?.subject_type === "GENERAL";
  const needsManualGroup = !!selected && selected.group_id == null;

  const resolvedGroupId = selected?.group_id ?? (manualGroups.length === 1 ? manualGroups[0] : null);

  const fixedGroupStudentCount =
    selected?.group_id != null ? groups.find((g) => g.group_id === selected.group_id)?.total_students : undefined;

  function selectSubject(s: Subject) {
    setSelected(s);
    if (s.group_id != null) {
      const count = groups.find((g) => g.group_id === s.group_id)?.total_students;
      if (count != null) {
        setSections((prev) => prev.map((sec) => (sec.maxCapacity === "" ? { ...sec, maxCapacity: String(count) } : sec)));
      }
    }
  }

  function toggleTimeslot(timeslotId: string) {
    setPreferredTimeslotIds((prev) => {
      const next = new Set(prev);
      if (next.has(timeslotId)) next.delete(timeslotId);
      else next.add(timeslotId);
      return next;
    });
  }

  function toggleGroup(g: string) {
    setManualGroups((prev) => (prev.includes(g) ? prev.filter((x) => x !== g) : [...prev, g]));
  }

  async function handleSave() {
    if (!selected) return;
    if (needsManualGroup && manualGroups.length === 0) {
      setError("กรุณาระบุชั้นปีที่เปิดสอนอย่างน้อย 1 ชั้นปี");
      return;
    }
    if (isGeneral && preferredTimeslotIds.size === 0) {
      setError("กรุณาเลือกคาบที่มีการจัดการเรียนการสอนอย่างน้อย 1 คาบ");
      return;
    }
    if (!isGeneral) {
      const hasEmptyTeacher = sections.some((sec) => sec.teacherIds.filter((id) => id).length === 0);
      if (hasEmptyTeacher) {
        setError("กรุณาระบุอาจารย์ผู้สอนอย่างน้อย 1 คนในแต่ละเซค");
        return;
      }
      const hasEmptyCapacity = sections.some((sec) => !sec.maxCapacity || sec.maxCapacity.trim() === "");
      if (hasEmptyCapacity) {
        setError("กรุณาระบุจำนวนนิสิตของแต่ละ sectiion");
        return;
      }
    }
    if (hasAnyDuplicateTeacher(sections)) {
      setError("มีอาจารย์คนเดียวกันถูกเลือกซ้ำในเซคเดียวกัน กรุณาเลือกอาจารย์ให้ไม่ซ้ำกัน");
      return;
    }
    const combinedFlag = sections.length > 1 ? lectureCombined : false;

    setSaving(true);
    setError("");
    try {
      if (mode === "edit" && isGeneral) {
        // GENERAL: มี record เดียวเสมอ (ไม่มี multi-section) — PATCH ตัวแรกพอ
        const target = editingRows![0];
        const res = await fetch(`${API_BASE}/subject-selected/${target.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            subject_id: selected.subject_id,
            teacher_ids: [],
            study_date: null,
            preferred_timeslot_ids: Array.from(preferredTimeslotIds).map(Number),
            max_capacity: null,
            academic_year: Number(academicYear),
            group_ids: needsManualGroup ? manualGroups : null,
            is_lecture_combined: false,
            fixed_room_id: null,
          }),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || "บันทึกไม่สำเร็จ");
        }
      } else if (mode === "edit") {
        // CORE/ELECTIVE: edit ทั้งกลุ่ม section พร้อมกัน — diff ระหว่าง sections ปัจจุบัน
        // กับ record เดิม: มี existingId -> PATCH, ไม่มี existingId -> POST (section ใหม่ที่
        // เพิ่มระหว่างแก้ไข), record เดิมที่หายไปจาก sections (ถูกลบออกระหว่างแก้ไข) -> DELETE
        const originalIds = new Set(editingRows!.map((r) => r.id));
        const keptIds = new Set(sections.filter((s) => s.existingId != null).map((s) => s.existingId!));
        const removedIds = [...originalIds].filter((id) => !keptIds.has(id));

        for (const sec of sections) {
          const payload = {
            subject_id: selected.subject_id,
            teacher_ids: sec.teacherIds.filter((id) => id),
            study_date: null,
            preferred_timeslot_ids: [],
            max_capacity: sec.maxCapacity ? Number(sec.maxCapacity) : null,
            academic_year: Number(academicYear),
            group_ids: needsManualGroup ? manualGroups : null,
            is_lecture_combined: combinedFlag,
            fixed_room_id: sec.fixedRoomId || null,
          };

          if (sec.existingId != null) {
            const res = await fetch(`${API_BASE}/subject-selected/${sec.existingId}`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(payload),
            });
            if (!res.ok) {
              const body = await res.json().catch(() => ({}));
              throw new Error(body.detail || "บันทึกไม่สำเร็จ");
            }
          } else {
            const res = await fetch(`${API_BASE}/subject-selected`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(payload),
            });
            if (!res.ok) {
              const body = await res.json().catch(() => ({}));
              throw new Error(body.detail || "บันทึกไม่สำเร็จ");
            }
          }
        }

        // ลบ section ที่ถูกเอาออกระหว่างแก้ไข (มีอยู่ในกลุ่มเดิม แต่ไม่อยู่ใน sections แล้ว)
        for (const id of removedIds) {
          await fetch(`${API_BASE}/subject-selected/${id}`, { method: "DELETE" });
        }
      } else if (isGeneral) {
        const res = await fetch(`${API_BASE}/subject-selected`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            subject_id: selected.subject_id,
            teacher_ids: [],
            study_date: null,
            preferred_timeslot_ids: Array.from(preferredTimeslotIds).map(Number),
            max_capacity: null,
            academic_year: Number(academicYear),
            group_ids: needsManualGroup ? manualGroups : null,
            is_lecture_combined: false,
            fixed_room_id: null,
          }),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || "บันทึกไม่สำเร็จ");
        }
      } else {
        for (const sec of sections) {
          const res = await fetch(`${API_BASE}/subject-selected`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              subject_id: selected.subject_id,
              teacher_ids: sec.teacherIds.filter((id) => id),
              study_date: null,
              preferred_timeslot_ids: [],
              max_capacity: sec.maxCapacity ? Number(sec.maxCapacity) : null,
              academic_year: Number(academicYear),
              group_ids: needsManualGroup ? manualGroups : null,
              is_lecture_combined: combinedFlag,
              fixed_room_id: sec.fixedRoomId || null,
            }),
          });
          if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            throw new Error(body.detail || "บันทึกไม่สำเร็จ");
          }
        }
      }
      onSaved();
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
            <h3 className="text-[17px] font-bold text-gray-900">
              {mode === "edit"
                ? `แก้ไขการเปิดสอน${editingRows && editingRows.length > 1 ? ` (${editingRows.length} sections)` : ""}`
                : "เพิ่มรายวิชาที่เปิดสอน"}
            </h3>
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

          {mode === "add" && !selected ? (
            <SubjectPickerTable
              subjects={subjects}
              academicYear={academicYear}
              existingByKey={existingByKey}
              sectionCountByKey={sectionCountByKey}
              onSelect={selectSubject}
            />
          ) : (
            <>
              {mode === "add" && (
                <button
                  onClick={() => {
                    setSelected(null);
                    setSections([{ teacherIds: [""], maxCapacity: "", fixedRoomId: "" }]);
                    setPreferredTimeslotIds(new Set());
                    setManualGroups([]);
                    setLectureCombined(false);
                  }}
                  className="text-xs text-orange-500 hover:underline mb-4 cursor-pointer"
                >
                  ← เลือกวิชาอื่น
                </button>
              )}

              {needsManualGroup && (
                <div className="mb-4 max-w-md">
                  <label className="flex items-center gap-1.5 text-xs font-semibold text-gray-500 mb-2">
                    <Users size={13} />
                    ชั้นปีที่เปิดสอน (เลือกได้หลายชั้นปี)
                  </label>
                  <div className="flex gap-1.5">
                    {ALL_GROUPS.map((g) => {
                      const takenGroups = existingByKey[`${selected!.subject_id}-${academicYear}`];
                      const isTaken = selected!.subject_type === "GENERAL" && !!takenGroups?.has(g);
                      return (
                        <button
                          key={g}
                          disabled={isTaken}
                          onClick={() => !isTaken && toggleGroup(g)}
                          title={isTaken ? `${g} เปิดสอนวิชานี้ไปแล้วในปีการศึกษานี้` : undefined}
                          className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${
                            isTaken
                              ? "border-gray-100 bg-gray-50 text-gray-300 cursor-not-allowed"
                              : manualGroups.includes(g)
                                ? "border-orange-300 bg-orange-50 text-orange-600 cursor-pointer"
                                : "border-gray-200 text-gray-500 hover:bg-gray-50 cursor-pointer"
                          }`}
                        >
                          {GROUP_LABEL[g] ?? g}
                        </button>
                      );
                    })}
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
                    excludeSubjectSelectedId={mode === "edit" ? editingRows![0].id : null}
                  />
                </div>
              ) : (
                <div className="mb-4">
                  <label className="flex items-center gap-1.5 text-xs font-semibold text-gray-500 mb-2">
                    <User size={13} />
                    อาจารย์ผู้สอน (เพิ่มได้หลาย section กรณีอาจารย์คนละคนสอนคนละกลุ่ม)
                  </label>

                  <SectionTeacherEditor
                    sections={sections}
                    teachers={teachers}
                    mode={mode}
                    editableSections={isMultiSectionEdit}
                    fixedGroupStudentCount={fixedGroupStudentCount}
                    onAddSection={addSection}
                    onRemoveSection={removeSection}
                    onUpdateCapacity={updateCapacity}
                    onAddCoTeacher={addCoTeacher}
                    onUpdateTeacher={updateTeacher}
                    onRemoveTeacher={removeTeacher}
                    onDistributeEvenly={distributeEvenly}
                    lectureCombined={lectureCombined}
                    onToggleLectureCombined={toggleLectureCombined}
                    rooms={rooms}
                    onUpdateFixedRoom={updateFixedRoom}
                  />
                </div>
              )}
            </>
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
              ) : mode === "edit" ? (
                "บันทึกการแก้ไข"
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