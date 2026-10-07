"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { API_BASE } from "./types";
import { Subject } from "./SubjectPickerTable";
import { CS_GROUPS, IT_GROUPS, GROUP_LABEL } from "./SectionTeacherEditor";

interface Props {
  /** ข้อความที่ผู้ใช้พิมพ์ค้นหาไว้ ใช้ prefill ให้อัตโนมัติ */
  initialText?: string;
  onCancel: () => void;
  /** สร้างสำเร็จ ส่งวิชาที่ได้จาก backend กลับไป */
  onCreated: (subject: Subject) => void;
}

const TYPE_OPTIONS = [
  { value: "CORE", label: "วิชาสาขา" },
  { value: "ELECTIVE", label: "วิชาเลือก" },
  { value: "GENERAL", label: "ศึกษาทั่วไป" },
];

const inputCls =
  "w-full px-3 py-2 rounded-lg border border-gray-200 bg-white text-sm text-gray-700 outline-none focus:border-orange-300 transition-all placeholder:text-gray-300";
const labelCls = "block text-xs font-semibold text-gray-500 mb-1.5";

export default function CreateSubjectForm({ initialText = "", onCancel, onCreated }: Props) {
  const text = initialText.trim();
  const isCode = /^\d+$/.test(text);

  const [subjectId, setSubjectId] = useState(isCode ? text : "");
  const [nameThai, setNameThai] = useState(isCode ? "" : text);
  const [nameEnglish, setNameEnglish] = useState("");
  const [subjectType, setSubjectType] = useState("CORE");
  const [groupId, setGroupId] = useState(""); // "" = ไม่ผูกชั้นปีตายตัว
  const [semester, setSemester] = useState("1");
  const [lectureHours, setLectureHours] = useState("3");
  const [labHours, setLabHours] = useState("0");
  const [descriptionThai, setDescriptionThai] = useState("");
  const [descriptionEnglish, setDescriptionEnglish] = useState("");

  // วิชาศึกษาทั่วไปไม่ใช้ชั่วโมงบรรยาย/ปฏิบัติ (กำหนดคาบเองตอนเปิดสอน) → เก็บเป็น NULL เหมือนข้อมูลเดิม
  const isGeneral = subjectType === "GENERAL";

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [idError, setIdError] = useState("");

  async function handleCreate() {
    setError("");
    setIdError("");

    if (!subjectId.trim()) return setIdError("กรุณากรอกรหัสวิชา");
    if (!nameThai.trim()) return setError("กรุณากรอกชื่อวิชาภาษาไทย");
    if (!isGeneral && Number(lectureHours || 0) + Number(labHours || 0) <= 0)
      return setError("ต้องมีชั่วโมงบรรยายหรือปฏิบัติอย่างน้อย 1 ชั่วโมง");

    setSaving(true);
    try {
      const res = await fetch(`${API_BASE}/subjects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subject_id: subjectId.trim(),
          name_thai: nameThai.trim(),
          name_english: nameEnglish.trim() || null,
          description_thai: descriptionThai.trim() || null,
          description_english: descriptionEnglish.trim() || null,
          subject_type: subjectType,
          group_id: groupId || null,
          semester: Number(semester),
          lecture_hours: isGeneral ? null : Number(lectureHours || 0),
          lab_hours: isGeneral ? null : Number(labHours || 0),
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (res.status === 409) {
        setIdError(body.detail || "รหัสวิชานี้มีอยู่แล้ว");
        return;
      }
      if (!res.ok) throw new Error(body.detail || "สร้างรายวิชาไม่สำเร็จ");
      onCreated(body as Subject);
    } catch (e) {
      setError(e instanceof Error ? e.message : "สร้างรายวิชาไม่สำเร็จ");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <button onClick={onCancel} className="text-xs text-orange-500 hover:underline mb-4 cursor-pointer">
        ← กลับไปเลือกจากรายการ
      </button>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-2.5 text-red-600 text-[13px] mb-4">
          {error}
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        {/* แถว 1: รหัส + ชื่อไทย */}
        <div className="col-span-2 md:col-span-1">
          <label className={labelCls}>รหัสวิชา *</label>
          <input
            inputMode="numeric"
            className={`${inputCls} ${idError ? "border-red-300" : ""}`}
            value={subjectId}
            onChange={(e) => {
              setSubjectId(e.target.value);
              setIdError("");
            }}
            placeholder="เช่น 254362"
          />
          {idError && <p className="text-[12px] text-red-500 mt-1">{idError}</p>}
        </div>
        <div className="col-span-2 md:col-span-4">
          <label className={labelCls}>ชื่อวิชา (ไทย) *</label>
          <input className={inputCls} value={nameThai} onChange={(e) => setNameThai(e.target.value)} />
        </div>

        {/* แถว 2: ชื่ออังกฤษ */}
        <div className="col-span-2 md:col-span-5">
          <label className={labelCls}>ชื่อวิชา (อังกฤษ)</label>
          <input className={inputCls} value={nameEnglish} onChange={(e) => setNameEnglish(e.target.value)} />
        </div>

        {/* แถว 3: ประเภท / ชั้นปี / ภาค / ชั่วโมง */}
        <div>
          <label className={labelCls}>ประเภทวิชา *</label>
          <select className={inputCls} value={subjectType} onChange={(e) => setSubjectType(e.target.value)}>
            {TYPE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelCls}>ชั้นปี</label>
          <select className={inputCls} value={groupId} onChange={(e) => setGroupId(e.target.value)}>
            <option value="">ไม่ผูกชั้นปี</option>
            {CS_GROUPS.map((g) => (
              <option key={g} value={g}>
                CS {GROUP_LABEL[g] ?? g}
              </option>
            ))}
            {IT_GROUPS.map((g) => (
              <option key={g} value={g}>
                IT {GROUP_LABEL[g] ?? g}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelCls}>ภาคเรียน</label>
          <select className={inputCls} value={semester} onChange={(e) => setSemester(e.target.value)}>
            <option value="1">ภาค 1</option>
            <option value="2">ภาค 2</option>
            <option value="3">ภาคฤดูร้อน</option>
          </select>
        </div>
        <div>
          <label className={labelCls}>ชั่วโมงบรรยาย</label>
          <input
            type="number"
            min={0}
            disabled={isGeneral}
            className={`${inputCls} disabled:bg-gray-50 disabled:text-gray-300`}
            value={isGeneral ? "" : lectureHours}
            placeholder={isGeneral ? "-" : undefined}
            onChange={(e) => setLectureHours(e.target.value)}
          />
        </div>
        <div>
          <label className={labelCls}>ชั่วโมงปฏิบัติ</label>
          <input
            type="number"
            min={0}
            disabled={isGeneral}
            className={`${inputCls} disabled:bg-gray-50 disabled:text-gray-300`}
            value={isGeneral ? "" : labHours}
            placeholder={isGeneral ? "-" : undefined}
            onChange={(e) => setLabHours(e.target.value)}
          />
        </div>

        {/* แถว 4: คำอธิบาย ไทย | อังกฤษ */}
        <div className="col-span-2 md:col-span-5 grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className={labelCls}>คำอธิบายรายวิชา (ไทย)</label>
            <textarea
              rows={3}
              className={`${inputCls} resize-none`}
              value={descriptionThai}
              onChange={(e) => setDescriptionThai(e.target.value)}
            />
          </div>
          <div>
            <label className={labelCls}>คำอธิบายรายวิชา (อังกฤษ)</label>
            <textarea
              rows={3}
              className={`${inputCls} resize-none`}
              value={descriptionEnglish}
              onChange={(e) => setDescriptionEnglish(e.target.value)}
            />
          </div>
        </div>
      </div>

      <div className="flex gap-2.5 justify-end mt-6">
        <button
          onClick={onCancel}
          className="px-5 py-2.5 rounded-xl border border-gray-200 text-gray-600 text-sm font-semibold hover:bg-gray-50 cursor-pointer transition-colors"
        >
          ยกเลิก
        </button>
        <button
          onClick={handleCreate}
          disabled={saving}
          className="px-6 py-2.5 rounded-xl bg-orange-500 hover:bg-orange-600 text-white text-sm font-semibold cursor-pointer disabled:bg-orange-200 transition-colors flex items-center gap-1.5"
        >
          {saving ? (
            <>
              <Loader2 size={14} className="animate-spin" /> กำลังสร้าง...
            </>
          ) : (
            "สร้างและเลือกวิชานี้"
          )}
        </button>
      </div>
    </div>
  );
}