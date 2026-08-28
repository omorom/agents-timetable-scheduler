"use client";

import { X, Shuffle, Link2, Lock } from "lucide-react";

export interface Teacher {
  teacher_id: string;
  teacher_name: string;
}

export interface Room {
  room_id: string;
  room_name: string;
  room_type?: string; // "LECTURE" | "LAB" — ถ้ามี ใช้กรองให้เหลือแต่ห้อง LAB ใน dropdown
}

// fixedRoomId: "" = ไม่ล็อก (ให้ระบบเลือกอัตโนมัติ), มีค่า = บังคับใช้ห้องนั้นเสมอ
export type Section = { teacherIds: string[]; maxCapacity: string; fixedRoomId: string };

// คืนชุด teacher_id ที่ถูกเลือกซ้ำภายใน section เดียวกัน (ไม่นับค่าว่าง)
export function getDuplicateTeacherIds(teacherIds: string[]): Set<string> {
  const seen = new Set<string>();
  const dupes = new Set<string>();
  for (const id of teacherIds) {
    if (!id) continue;
    if (seen.has(id)) dupes.add(id);
    seen.add(id);
  }
  return dupes;
}

export function hasAnyDuplicateTeacher(sections: Section[]): boolean {
  return sections.some((sec) => getDuplicateTeacherIds(sec.teacherIds).size > 0);
}

interface Props {
  sections: Section[];
  teachers: Teacher[];
  mode: "add" | "edit";
  fixedGroupStudentCount?: number;
  onAddSection: () => void;
  onRemoveSection: (sectionIdx: number) => void;
  onUpdateCapacity: (sectionIdx: number, value: string) => void;
  onAddCoTeacher: (sectionIdx: number) => void;
  onUpdateTeacher: (sectionIdx: number, teacherIdx: number, value: string) => void;
  onRemoveTeacher: (sectionIdx: number, teacherIdx: number) => void;
  onDistributeEvenly?: () => void;
  // รวม LECTURE ทุก section เข้าด้วยกัน (เรียนเวลา/ห้องเดียวกัน)
  lectureCombined?: boolean;
  onToggleLectureCombined?: () => void;
  // ล็อกห้อง LAB ตายตัวต่อ section — ส่ง rooms มาถึงจะโชว์ dropdown นี้
  // (ไม่ส่งมา = ซ่อนไปเลย ไม่กระทบวิชาที่ไม่มี LAB หรือหน้าจอที่ยังไม่รองรับ)
  rooms?: Room[];
  onUpdateFixedRoom?: (sectionIdx: number, roomId: string) => void;
}

export default function SectionTeacherEditor({
  sections,
  teachers,
  mode,
  fixedGroupStudentCount,
  onAddSection,
  onRemoveSection,
  onUpdateCapacity,
  onAddCoTeacher,
  onUpdateTeacher,
  onRemoveTeacher,
  onDistributeEvenly,
  lectureCombined = false,
  onToggleLectureCombined,
  rooms,
  onUpdateFixedRoom,
}: Props) {
  // แสดงปุ่ม "แบ่งเท่า ๆ กัน" เมื่อมีมากกว่า 1 section และรู้จำนวนนักศึกษาทั้งหมดแน่นอน
  // (ถ้าไม่รู้ fixedGroupStudentCount ก็ไม่รู้จะหารจากเลขไหน เลยไม่แสดงปุ่ม)
  const canDistribute = mode === "add" && sections.length > 1 && fixedGroupStudentCount != null && !!onDistributeEvenly;

  // แสดง toggle "รวม LECTURE" เมื่อมีมากกว่า 1 section เท่านั้น (section เดียวไม่มีอะไรให้รวม)
  const canCombineLecture = sections.length > 1 && !!onToggleLectureCombined;

  // เฉพาะห้องประเภท LAB เท่านั้น (ถ้า rooms ไม่ระบุ room_type มา ก็แสดงทั้งหมดไปเลย
  // ไม่กรอง เผื่อ backend บางที่ยังไม่ส่ง field นี้มา)
  const labRooms = rooms?.filter((r) => !r.room_type || r.room_type === "LAB") ?? [];
  const showFixedRoom = !!rooms && !!onUpdateFixedRoom;

  return (
    <div className="space-y-3">
      {canDistribute && (
        <div className="flex items-center justify-between px-1">
          <span className="text-[12px] text-gray-400">
            จำนวนที่นั่งต่อ section ({fixedGroupStudentCount} คนทั้งหมด)
          </span>
          <button
            onClick={onDistributeEvenly}
            className="flex items-center gap-1.5 text-[12px] font-semibold text-orange-500 hover:text-orange-600 cursor-pointer transition-colors"
          >
            <Shuffle size={13} />
            แบ่งเท่า ๆ กัน
          </button>
        </div>
      )}

      {canCombineLecture && (
        <div className="flex items-center justify-between px-3.5 py-2.5 rounded-xl border border-gray-200 bg-gray-50/60">
          <div className="flex items-center gap-2">
            <Link2 size={14} className={lectureCombined ? "text-orange-500" : "text-gray-400"} />
            <span className="text-[13px] font-medium text-gray-700">
              เรียน LECTURE รวมกันทุก Section
            </span>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={lectureCombined}
            onClick={onToggleLectureCombined}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors cursor-pointer ${
              lectureCombined ? "bg-orange-500" : "bg-gray-300"
            }`}
          >
            <span
              className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                lectureCombined ? "translate-x-4.5" : "translate-x-1"
              }`}
            />
          </button>
        </div>
      )}

      {sections.map((sec, sIdx) => {
        const duplicateIds = getDuplicateTeacherIds(sec.teacherIds);
        return (
          <div key={sIdx} className="border border-gray-200 rounded-xl shadow-sm bg-white p-4">
            <div className="flex items-center justify-between mb-3">
              <span className="text-[11px] font-semibold text-gray-400 tracking-wide">
                SECTION {sIdx + 1}
              </span>
              {mode === "add" && sections.length > 1 && (
                <button
                  onClick={() => onRemoveSection(sIdx)}
                  className="text-gray-300 hover:text-red-500 transition-colors cursor-pointer"
                >
                  <X size={14} />
                </button>
              )}
            </div>

            {/* อาจารย์เรียงแนวนอน ขึ้นบรรทัดใหม่เมื่อเต็มแถว */}
            <div className="flex items-center gap-2 flex-wrap">
              {sec.teacherIds.map((teacherId, tIdx) => {
                const isDuplicate = !!teacherId && duplicateIds.has(teacherId);
                return (
                  <div key={tIdx} className="w-60 flex items-center gap-1.5">
                    <select
                      value={teacherId}
                      onChange={(e) => onUpdateTeacher(sIdx, tIdx, e.target.value)}
                      className={`flex-1 min-w-0 border rounded-lg px-2.5 py-2 text-[13px] outline-none bg-white transition-all text-gray-700 ${
                        isDuplicate
                          ? "border-red-300 focus:border-red-400 focus:ring-2 focus:ring-red-50"
                          : "border-gray-200 focus:border-orange-300 focus:ring-2 focus:ring-orange-50"
                      }`}
                    >
                      <option value="">ยังไม่ระบุอาจารย์</option>
                      {teachers.map((t) => (
                        <option key={t.teacher_id} value={t.teacher_id}>
                          {t.teacher_name}
                        </option>
                      ))}
                    </select>
                    {sec.teacherIds.length > 1 && (
                      <button
                        onClick={() => onRemoveTeacher(sIdx, tIdx)}
                        className="text-gray-300 hover:text-red-500 transition-colors cursor-pointer shrink-0"
                      >
                        <X size={13} />
                      </button>
                    )}
                  </div>
                );
              })}
            </div>

            {duplicateIds.size > 0 && (
              <p className="mt-1.5 text-[11px] text-red-500">
                มีอาจารย์คนเดียวกันถูกเลือกซ้ำในเซคนี้ — สอนไปแล้ว กรุณาเลือกคนอื่นแทน
              </p>
            )}

            {/* ปุ่มเพิ่มอาจารย์ — อยู่บรรทัดของตัวเองเสมอ ตำแหน่งคงที่ ไม่ขยับตามจำนวนอาจารย์ */}
            <button
              onClick={() => onAddCoTeacher(sIdx)}
              className="mt-2 text-[12px] text-orange-500 hover:text-orange-600 cursor-pointer"
            >
              + เพิ่มอาจารย์อีกคน
            </button>

            <div className="mt-3 pt-3 border-t border-gray-100 flex flex-wrap gap-4">
              <div className="max-w-[180px]">
                <label className="block text-[11px] text-gray-400 mb-1">
                  จำนวนที่นั่ง
                  {fixedGroupStudentCount != null && ` (${fixedGroupStudentCount} คน)`}
                </label>
                <input
                  type="number"
                  value={sec.maxCapacity}
                  onChange={(e) => onUpdateCapacity(sIdx, e.target.value)}
                  placeholder="เช่น 75"
                  className="w-full border border-gray-200 rounded-lg px-2.5 py-2 text-[13px] outline-none bg-white focus:border-orange-300 focus:ring-2 focus:ring-orange-50 transition-all"
                />
              </div>

              {showFixedRoom && (
                <div className="max-w-[220px] flex-1 min-w-[180px]">
                  <label className="flex items-center gap-1 text-[11px] text-gray-400 mb-1">
                    <Lock size={11} />
                    ล็อกห้อง LAB ตายตัว (ถ้ามี)
                  </label>
                  <select
                    value={sec.fixedRoomId}
                    onChange={(e) => onUpdateFixedRoom!(sIdx, e.target.value)}
                    className="w-full border border-gray-200 rounded-lg px-2.5 py-2 text-[13px] outline-none bg-white focus:border-orange-300 focus:ring-2 focus:ring-orange-50 transition-all text-gray-700"
                  >
                    <option value="">อัตโนมัติ (ให้ระบบเลือกให้)</option>
                    {labRooms.map((r) => (
                      <option key={r.room_id} value={r.room_id}>
                        {r.room_name}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          </div>
        );
      })}

      {mode === "add" && (
        <button
          onClick={onAddSection}
          className="text-[13px] font-medium text-gray-500 hover:text-orange-500 cursor-pointer transition-colors"
        >
          + เพิ่ม section ใหม่
        </button>
      )}
    </div>
  );
}