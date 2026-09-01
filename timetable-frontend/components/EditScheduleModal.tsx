"use client";

import { useState, useEffect } from "react";
import { X, Loader2 } from "lucide-react";
import { ScheduleItem, Teacher, Room, DAY_TH, DAY_ABBR, API_BASE } from "./types"

const dayOf = (x: { day: string }) => DAY_ABBR[x.day] ?? x.day;

const TYPE_LABEL_MAP: Record<string, string> = {
  GENERAL: "ศึกษาทั่วไป",
  CORE: "วิชาสาขา",
  ELECTIVE: "วิชาเลือก",
};

interface Props {
  item: ScheduleItem;
  onClose: () => void;
  onSaved: () => void;
}

export default function EditScheduleModal({ item, onClose, onSaved }: Props) {
  const [teachers, setTeachers] = useState<Teacher[]>([]);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [loadingOptions, setLoadingOptions] = useState(true);

  const initialTeacherIds =
    item.teacher_keys && item.teacher_keys.length > 0
      ? item.teacher_keys
      : item.teacher_key
        ? [item.teacher_key]
        : [""];
  const [teacherIds, setTeacherIds] = useState<string[]>(initialTeacherIds);
  const [roomId, setRoomId] = useState(item.room_key ?? "");

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoadingOptions(true);
      try {
        const [tRes, rRes] = await Promise.all([
          fetch(`${API_BASE}/teachers`),
          fetch(`${API_BASE}/rooms`),
        ]);
        const [tData, rData] = await Promise.all([tRes.json(), rRes.json()]);
        if (!cancelled) {
          setTeachers(Array.isArray(tData) ? tData : []);
          setRooms(Array.isArray(rData) ? rData : []);
        }
      } catch {
        if (!cancelled) setError("ไม่สามารถโหลดรายชื่ออาจารย์/ห้องได้");
      } finally {
        if (!cancelled) setLoadingOptions(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  function updateTeacher(idx: number, value: string) {
    setTeacherIds((prev) => prev.map((t, i) => (i === idx ? value : t)));
  }

  function addTeacher() {
    setTeacherIds((prev) => [...prev, ""]);
  }

  function removeTeacher(idx: number) {
    setTeacherIds((prev) => prev.filter((_, i) => i !== idx));
  }

  const cleanTeacherIds = teacherIds.filter((t) => t);
  const cleanInitialTeacherIds = initialTeacherIds.filter((t) => t);
  const teacherIdsChanged =
    cleanTeacherIds.length !== cleanInitialTeacherIds.length ||
    cleanTeacherIds.some((t) => !cleanInitialTeacherIds.includes(t)) ||
    cleanInitialTeacherIds.some((t) => !cleanTeacherIds.includes(t));

  const isDirty = teacherIdsChanged || roomId !== (item.room_key ?? "");

  // มีอาจารย์คนเดียวกันถูกเลือกซ้ำในชุดนี้ไหม (กันพลาดเลือกซ้ำโดยไม่ตั้งใจ)
  const duplicateTeacherIds = (() => {
    const seen = new Set<string>();
    const dupes = new Set<string>();
    for (const id of teacherIds) {
      if (!id) continue;
      if (seen.has(id)) dupes.add(id);
      seen.add(id);
    }
    return dupes;
  })();

  async function handleSave() {
    if (!isDirty || saving || duplicateTeacherIds.size > 0) return;
    setSaving(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE}/schedule/${item.session_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          teacher_ids: teacherIdsChanged ? cleanTeacherIds : null,
          room_id: roomId || null,
        }),
      });
      if (res.status === 409) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || "ห้อง/อาจารย์ไม่ว่างในคาบนี้");
        return;
      }
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || "บันทึกไม่สำเร็จ กรุณาลองใหม่");
        return;
      }
      onSaved();
      onClose();
    } catch {
      setError("เกิดข้อผิดพลาด กรุณาลองใหม่");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 bg-black/30 backdrop-blur-[2px] z-50 flex items-center justify-center animate-fade-up p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-2xl w-full max-w-md max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between px-5 pt-4 pb-3 border-b border-gray-100 sticky top-0 bg-white">
          <h3 className="text-[13.5px] font-bold text-gray-900">รายละเอียดวิชา</h3>
          <button onClick={onClose} className="text-gray-300 hover:text-gray-500 transition-colors cursor-pointer">
            <X size={16} />
          </button>
        </div>

        {/* ─── รายละเอียดวิชา (สไตล์เดียวกับ SubjectDetailModal ของวิชา GE) ─── */}
        <div className="px-5 pt-3">
          <div className="flex items-center gap-1.5 mb-1 flex-wrap">
            <span className="text-[11px] font-mono text-gray-400">{item.subject_id}</span>
            {item.session_type && (
              <span
                className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full
                  ${item.session_type === "LAB" ? "bg-blue-100 text-blue-600" : "bg-green-100 text-green-700"}`}
              >
                {item.session_type}
              </span>
            )}
            {item.subject_type && (
              <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-purple-50 text-purple-600">
                {TYPE_LABEL_MAP[item.subject_type] ?? item.subject_type}
              </span>
            )}
            {item.semester != null && (
              <span className="text-[9px] text-gray-400">ภาคเรียนที่ {item.semester}</span>
            )}
          </div>

          <p className="text-[13px] font-bold text-gray-900 mb-0.5">{item.subject_name}</p>
          {item.subject_name_english && (
            <p className="text-[11px] text-gray-400 mb-1.5">{item.subject_name_english}</p>
          )}
          {item.description_thai && (
            <p className="text-[11.5px] text-gray-600 leading-relaxed line-clamp-3">{item.description_thai}</p>
          )}
          {item.description_english && (
            <p className="text-[10.5px] text-gray-400 leading-relaxed mt-1 line-clamp-2">{item.description_english}</p>
          )}

          <p className="text-[10.5px] text-gray-400 mt-2">
            {DAY_TH[dayOf(item)] ?? item.day} · {item.start_time}–{item.end_time}
            {item.section ? ` · Section ${item.section}` : ""}
          </p>
        </div>

        <div className="border-t border-gray-50 mt-3" />

        {/* ─── แก้ไขอาจารย์ (เลือกได้หลายคน) / ห้อง ─── */}
        <div className="px-5 py-3.5 space-y-3">
          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-red-600 text-[12px]">
              {error}
            </div>
          )}

          <div>
            <label className="text-[10px] text-gray-400 mb-1 block">อาจารย์ผู้สอน</label>
            <div className="space-y-1.5">
              {teacherIds.map((tId, idx) => {
                const isDuplicate = !!tId && duplicateTeacherIds.has(tId);
                return (
                  <div key={idx} className="flex items-center gap-1.5">
                    <select
                      value={tId}
                      onChange={(e) => updateTeacher(idx, e.target.value)}
                      disabled={loadingOptions}
                      className={`flex-1 min-w-0 border-0 rounded-lg px-2.5 py-1.5 text-[12px] font-medium disabled:text-gray-400 focus:outline-none focus:ring-2 cursor-pointer transition-colors ${
                        isDuplicate
                          ? "bg-red-50 text-red-600 focus:ring-red-200"
                          : "bg-slate-50 text-gray-700 focus:ring-orange-200"
                      }`}
                    >
                      <option value="">— ไม่ระบุ —</option>
                      {teachers.map((t) => (
                        <option key={t.teacher_id} value={t.teacher_id}>
                          {t.teacher_name}
                        </option>
                      ))}
                    </select>
                    {teacherIds.length > 1 && (
                      <button
                        onClick={() => removeTeacher(idx)}
                        className="text-gray-300 hover:text-red-500 transition-colors cursor-pointer shrink-0"
                      >
                        <X size={13} />
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
            {duplicateTeacherIds.size > 0 && (
              <p className="mt-1 text-[10px] text-red-500">
                มีอาจารย์คนเดียวกันถูกเลือกซ้ำ กรุณาเลือกให้ไม่ซ้ำกัน
              </p>
            )}
            <button
              onClick={addTeacher}
              className="mt-1.5 text-[11px] text-orange-500 hover:text-orange-600 cursor-pointer"
            >
              + เพิ่มอาจารย์อีกคน
            </button>
          </div>

          <div>
            <label className="text-[10px] text-gray-400 mb-1 block">ห้องเรียน</label>
            <select
              value={roomId}
              onChange={(e) => setRoomId(e.target.value)}
              disabled={loadingOptions}
              className="w-full border-0 bg-slate-50 rounded-lg px-2.5 py-1.5 text-[12px] font-medium text-gray-700 disabled:text-gray-400 focus:outline-none focus:ring-2 focus:ring-orange-200 cursor-pointer"
            >
              <option value="">— ไม่ระบุ —</option>
              {rooms.map((r) => (
                <option key={r.room_id} value={r.room_id}>
                  {r.room_name}
                </option>
              ))}
            </select>
          </div>

          <div className="flex gap-2 pt-0.5">
            <button
              onClick={onClose}
              className="flex-1 py-2 rounded-lg border border-gray-200 text-gray-600 text-[12.5px] font-semibold hover:bg-gray-50 cursor-pointer transition-colors"
            >
              ปิด
            </button>
            <button
              onClick={handleSave}
              disabled={!isDirty || saving || loadingOptions || duplicateTeacherIds.size > 0}
              className="flex-1 py-2 rounded-lg bg-orange-500 hover:bg-orange-600 text-white text-[12.5px] font-semibold cursor-pointer disabled:bg-orange-200 transition-colors flex items-center justify-center gap-1.5"
            >
              {saving ? <><Loader2 size={13} className="animate-spin" /> กำลังบันทึก...</> : "บันทึกการแก้ไข"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}