"use client";

// หน้าต่าง/แจ้งเตือนที่เปิดจากตารางเรียน (ยืนยันย้าย, ยืนยันสลับ, รายละเอียดวิชา, toast)
import { Check, X, Loader2 } from "lucide-react";
import { ScheduleItem, DAY_TH } from "./types";
import { PreferredItem, DropTarget, dayOf, blockLabelOf } from "./scheduleGridUtils";

export function Toast({ toast }: { toast: { msg: string; type: "error" | "success" } | null }) {
  if (!toast) return null;
  return (
    <div
      className={`fixed top-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2.5 pl-3 pr-4 py-2.5
        bg-white rounded-lg shadow-md border-l-[3px] animate-fade-up max-w-md`}
      style={{ borderLeftColor: toast.type === "error" ? "#ef4444" : "#10b981" }}
    >
      {toast.type === "success" ? (
        <Check size={15} className="text-emerald-500 shrink-0" strokeWidth={2.5} />
      ) : (
        <X size={15} className="text-red-500 shrink-0" strokeWidth={2.5} />
      )}
      <span className="text-[13px] font-medium text-gray-700 whitespace-normal">{toast.msg}</span>
    </div>
  );
}

// โครงหน้าต่างยืนยันที่ใช้ร่วมกัน (หัว + เนื้อหา + error + ปุ่ม) ระหว่างย้ายกับสลับ
function ConfirmShell({
  title,
  subtitle,
  confirmLabel,
  loadingLabel,
  loading,
  error,
  onCancel,
  onConfirm,
  children,
}: {
  title: string;
  subtitle: string;
  confirmLabel: string;
  loadingLabel: string;
  loading: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-[2px] z-[60] flex items-center justify-center animate-fade-up">
      <div className="bg-white rounded-2xl shadow-2xl p-6 w-[26rem] max-w-[calc(100vw-2rem)] mx-4">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h3 className="text-[15px] font-bold text-gray-900">{title}</h3>
            <p className="text-xs text-gray-400 mt-0.5">{subtitle}</p>
          </div>
          <button onClick={onCancel} className="text-gray-300 hover:text-gray-500 transition-colors cursor-pointer">
            <X size={18} />
          </button>
        </div>

        {children}

        {error && (
          <div className="flex items-start gap-2 bg-red-50 border border-red-100 rounded-xl px-3 py-2.5 mb-4">
            <X size={14} className="text-red-500 shrink-0 mt-0.5" strokeWidth={2.5} />
            <span className="text-[12.5px] text-red-600 leading-snug">{error}</span>
          </div>
        )}

        <div className="flex gap-2.5">
          <button
            onClick={onCancel}
            className="flex-1 py-2.5 rounded-xl border border-gray-200 text-gray-600 text-sm font-semibold hover:bg-gray-50 cursor-pointer transition-colors"
          >
            ยกเลิก
          </button>
          <button
            onClick={onConfirm}
            disabled={loading}
            className="flex-1 py-2.5 rounded-xl bg-orange-500 hover:bg-orange-600 text-white text-sm font-semibold cursor-pointer disabled:bg-orange-200 transition-colors flex items-center justify-center gap-1.5"
          >
            {loading ? <><Loader2 size={14} className="animate-spin" /> {loadingLabel}</> : error ? "ลองอีกครั้ง" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export function ConfirmMoveModal({
  pendingItem,
  dropTarget,
  loading,
  error,
  onCancel,
  onConfirm,
}: {
  pendingItem: ScheduleItem;
  dropTarget: DropTarget;
  loading: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <ConfirmShell
      title="ยืนยันการย้ายวิชา"
      subtitle="โปรดตรวจสอบข้อมูลก่อนดำเนินการ"
      confirmLabel="ตกลง"
      loadingLabel="กำลังย้าย..."
      loading={loading}
      error={error}
      onCancel={onCancel}
      onConfirm={onConfirm}
    >
      <div className="bg-slate-50 rounded-xl p-4 mb-4 space-y-3 text-sm border border-slate-100">
        <div className="flex items-start justify-between gap-2">
          <span className="text-gray-400 shrink-0">วิชา</span>
          <span className="font-semibold text-gray-800 text-right">{pendingItem.subject_name}</span>
        </div>
        <div className="border-t border-slate-200" />
        <div className="flex items-center justify-between">
          <span className="text-gray-400">เวลาเดิม</span>
          <span className="text-gray-600 text-[13px]">
            {DAY_TH[dayOf(pendingItem)] ?? pendingItem.day} {blockLabelOf(pendingItem.start_time, pendingItem.end_time)}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-gray-400">เวลาใหม่</span>
          <span className="font-semibold text-orange-600 text-[13px]">
            {DAY_TH[dropTarget.day] ?? dropTarget.day} {dropTarget.slot}
          </span>
        </div>
      </div>
    </ConfirmShell>
  );
}

const TYPE_TH: Record<string, string> = {
  LECTURE: "บรรยาย",
  LAB: "ปฏิบัติ",
};

export function ConfirmSwapModal({
  a,
  b,
  loading,
  error,
  onCancel,
  onConfirm,
}: {
  a: ScheduleItem;
  b: ScheduleItem;
  loading: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const timeOf = (it: ScheduleItem) =>
    `${DAY_TH[dayOf(it)] ?? it.day} ${blockLabelOf(it.start_time, it.end_time)}`;

  // ดีไซน์เรียบ: ซ้าย = ชื่อวิชา + รายละเอียดเล็ก, ขวา = เวลาใหม่ (เด่น) + เวลาเดิม (จาง)
  // ไม่มีป้ายสี/ไอคอน/กล่องพื้นหลัง ใช้แค่น้ำหนักตัวอักษรกับเส้นคั่นบางๆ แยกลำดับความสำคัญ
  const Row = ({ it, to }: { it: ScheduleItem; to: ScheduleItem }) => (
    <div className="flex items-start justify-between gap-4 py-3.5">
      <div className="min-w-0">
        <div className="text-[14px] font-medium text-gray-900 truncate">{it.subject_name}</div>
        <div className="text-[12px] text-gray-400 mt-0.5">
          {it.subject_id} · {TYPE_TH[it.session_type || "LECTURE"] ?? it.session_type}
        </div>
      </div>
      <div className="text-right shrink-0">
        <div className="text-[14px] font-semibold text-gray-900">{timeOf(to)}</div>
        <div className="text-[12px] text-gray-400 mt-0.5">เดิม {timeOf(it)}</div>
      </div>
    </div>
  );

  return (
    <ConfirmShell
      title="สลับเวลาเรียน"
      subtitle="สองวิชานี้จะสลับวันและเวลากัน"
      confirmLabel="สลับ"
      loadingLabel="กำลังสลับ..."
      loading={loading}
      error={error}
      onCancel={onCancel}
      onConfirm={onConfirm}
    >
      <div className="mb-5 border-y border-gray-100 divide-y divide-gray-100">
        <Row it={a} to={b} />
        <Row it={b} to={a} />
      </div>
    </ConfirmShell>
  );
}

const TYPE_LABEL: Record<string, string> = {
  GENERAL: "ศึกษาทั่วไป",
  CORE: "วิชาแกน",
  ELECTIVE: "วิชาเลือก",
};

export function SubjectDetailModal({ subjects, onClose }: { subjects: PreferredItem[]; onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 bg-black/30 backdrop-blur-[2px] z-[60] flex items-center justify-center animate-fade-up p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between px-6 pt-5 pb-4 border-b border-gray-100 sticky top-0 bg-white">
          <h3 className="text-[15px] font-bold text-gray-900">รายละเอียดวิชา</h3>
          <button onClick={onClose} className="text-gray-300 hover:text-gray-500 transition-colors cursor-pointer">
            <X size={18} />
          </button>
        </div>

        <div className="px-6 py-4 space-y-5">
          {subjects.map((s) => (
            <div key={s.subject_id} className="pb-5 border-b border-gray-50 last:border-0 last:pb-0">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-[13px] font-mono text-gray-400">{s.subject_id}</span>
                {s.subject_type && (
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-purple-50 text-purple-600">
                    {TYPE_LABEL[s.subject_type] ?? s.subject_type}
                  </span>
                )}
                {s.semester != null && (
                  <span className="text-[10px] text-gray-400">ภาคเรียนที่ {s.semester}</span>
                )}
              </div>
              <p className="text-[15px] font-bold text-gray-900 mb-0.5">{s.subject_name}</p>
              {s.subject_name_english && (
                <p className="text-[13px] text-gray-400 mb-2">{s.subject_name_english}</p>
              )}
              {s.description_thai && (
                <p className="text-[13px] text-gray-600 leading-relaxed">{s.description_thai}</p>
              )}
              {s.description_english && (
                <p className="text-[12px] text-gray-400 leading-relaxed mt-1.5">{s.description_english}</p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}