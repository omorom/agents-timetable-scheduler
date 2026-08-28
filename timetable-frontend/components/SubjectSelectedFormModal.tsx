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
  | { mode: "add"; onClose: () => void; onSaved: () => void; row?: undefined }
  | { mode: "edit"; onClose: () => void; onSaved: () => void; row: SubjectSelectedRow };

export default function SubjectSelectedFormModal(props: Props) {
  const { mode, onClose, onSaved } = props;
  const editingRow = mode === "edit" ? props.row : null;

  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [teachers, setTeachers] = useState<Teacher[]>([]);
  const [timeslots, setTimeslots] = useState<Timeslot[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [rooms, setRooms] = useState<Room[]>([]);
  // key: `${subject_id}-${academic_year}` -> Set ของ group_id ที่เปิดสอนไปแล้ว (ใช้ตอน mode add เท่านั้น)
  const [existingByKey, setExistingByKey] = useState<Record<string, Set<string>>>({});
  const [sectionCountByKey, setSectionCountByKey] = useState<Record<string, number>>({});

  const [selected, setSelected] = useState<Subject | null>(editingRow?.subjects ?? null);

  const [sections, setSections] = useState<Section[]>(
    editingRow
      ? [
          {
            teacherIds:
              editingRow.teachers && editingRow.teachers.length > 0
                ? editingRow.teachers.map((t) => t.teacher_id)
                : [""],
            maxCapacity: editingRow.max_capacity != null ? String(editingRow.max_capacity) : "",
            fixedRoomId: editingRow.fixed_room_id ?? "",
          },
        ]
      : [{ teacherIds: [""], maxCapacity: "", fixedRoomId: "" }]
  );
  // เรียน LECTURE รวมกันทุก section ไหม (มีผลก็ต่อเมื่อมีมากกว่า 1 section)
  const [lectureCombined, setLectureCombined] = useState(editingRow?.is_lecture_combined ?? false);
  const [preferredTimeslotIds, setPreferredTimeslotIds] = useState<Set<string>>(
    new Set((editingRow?.subject_selected_preferred_timeslots ?? []).map((t) => String(t.timeslot_id)))
  );
  // ปีการศึกษาไม่ต้องให้กรอกเอง ใช้ปีปัจจุบันเป็นค่า default เงียบ ๆ
  const [academicYear] = useState(
    editingRow ? String(editingRow.academic_year) : String(new Date().getFullYear() + 543)
  );
  const [manualGroups, setManualGroups] = useState<string[]>(
    editingRow && editingRow.subjects.group_id == null ? editingRow.group_ids : []
  );

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // ---- Section-level helpers (แยกเซค) ----
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

  // แบ่งจำนวนนักศึกษาทั้งหมด (fixedGroupStudentCount) ให้เท่า ๆ กันในทุก section ที่มีอยู่
  // ถ้าหารไม่ลงตัว ให้เศษที่เหลือตกกับ section แรก ๆ ก่อน (เช่น 61 คน 2 sec -> 31, 30)
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

  // ---- Teacher-level helpers (อาจารย์ร่วมสอนในเซคเดียวกัน) ----
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

        const map: Record<string, Set<string>> = {};
        const countMap: Record<string, number> = {};
        for (const row of Array.isArray(existing) ? existing : []) {
          // ตอน edit ไม่ต้องนับ record ของตัวเอง ไม่งั้นจะโดน lock วิชาตัวเองผิด ๆ
          if (mode === "edit" && row.id === editingRow!.id) continue;
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

  // ใช้เช็ค "ชั้นปีนี้มีวิชาอื่นเรียนแล้วไหม" ได้ก็ต่อเมื่อรู้ชั้นปีแน่ชัดแค่ 1 ชั้นปีเท่านั้น
  const resolvedGroupId = selected?.group_id ?? (manualGroups.length === 1 ? manualGroups[0] : null);

  // ถ้าวิชานี้ผูกชั้นปีตายตัวอยู่แล้ว รู้จำนวนนิสิตของชั้นปีนั้นได้เลย ใช้เป็นค่า default ให้จำนวนที่นั่ง
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
    // toggle รวม LECTURE มีความหมายก็ต่อเมื่อมีมากกว่า 1 section เท่านั้น
    const combinedFlag = sections.length > 1 ? lectureCombined : false;

    setSaving(true);
    setError("");
    try {
      if (mode === "edit") {
        // แก้ไข: มี record เดียวแน่นอน (สอดคล้องกับ row ที่คลิกมา) ใช้ sections[0] พอ
        const sec = sections[0];
        const res = await fetch(`${API_BASE}/subject-selected/${editingRow!.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            subject_id: selected.subject_id,
            teacher_ids: isGeneral ? [] : sec.teacherIds.filter((id) => id),
            study_date: null,
            preferred_timeslot_ids: isGeneral ? Array.from(preferredTimeslotIds).map(Number) : [],
            max_capacity: isGeneral ? null : sec.maxCapacity ? Number(sec.maxCapacity) : null,
            academic_year: Number(academicYear),
            group_ids: needsManualGroup ? manualGroups : null,
            is_lecture_combined: combinedFlag,
            fixed_room_id: isGeneral ? null : sec.fixedRoomId || null,
          }),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || "บันทึกไม่สำเร็จ");
        }
      } else if (isGeneral) {
        // GENERAL: ไม่มีแนวคิด section หลายอาจารย์ สร้างแค่ record เดียว
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
        // CORE/ELECTIVE: สร้างทีละ section ตามลำดับ (1 section = 1 คำขอ = 1 subject_selected)
        // แต่ละ section อาจมีอาจารย์ได้หลายคน (สอนพร้อมกันในเซคเดียวกัน)
        // ทุก section ที่สร้างในรอบนี้ ใช้ค่า is_lecture_combined เดียวกันหมด (มาจาก toggle บนสุด)
        // ส่วน fixed_room_id เป็นค่าเฉพาะของแต่ละ section เอง (ไม่ใช้ค่าร่วม)
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
              {mode === "edit" ? "แก้ไขการเปิดสอน" : "เพิ่มรายวิชาที่เปิดสอน"}
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

          {/* ขั้นตอนค้นหา/เลือกวิชา — เฉพาะตอน add เท่านั้น ตอน edit ข้ามไปเลยเพราะรู้วิชาอยู่แล้ว */}
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
              {/* ปุ่ม "เลือกวิชาอื่น" ใช้ได้เฉพาะตอน add เท่านั้น ตอน edit ไม่ต้องมีเพราะวิชาเปลี่ยนไม่ได้ */}
              {mode === "add" && (
                <button
                  onClick={() => {
                    // ล้างค่าทั้งหมดที่ผูกกับวิชาเดิม กันค่าค้าง (เช่น จำนวนที่นั่ง auto-fill ของวิชาก่อนหน้า)
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
                    excludeSubjectSelectedId={mode === "edit" ? editingRow!.id : null}
                  />
                </div>
              ) : (
                <div className="mb-4">
                  <label className="flex items-center gap-1.5 text-xs font-semibold text-gray-500 mb-2">
                    <User size={13} />
                    อาจารย์ผู้สอน {mode === "add" && "(เพิ่มได้หลาย section กรณีอาจารย์คนละคนสอนคนละกลุ่ม)"}
                  </label>

                  <SectionTeacherEditor
                    sections={sections}
                    teachers={teachers}
                    mode={mode}
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