"use client";

import { useState, useEffect, useCallback } from "react";
import { UploadCloud, X, Loader2, AlertTriangle } from "lucide-react";
import { API_BASE } from "./types";

// ============================================================
// สมมติ backend endpoint ไว้ 3 ตัว (แก้ path ให้ตรงกับของจริงถ้าไม่ตรง):
//
// GET  {API_BASE}/room-unavailability/import-status?semester=1
//      -> { imported: boolean, count: number }
//      เช็คว่าภาคเรียนนี้เคย "ใช้ข้อมูลเดิม" ไปแล้วหรือยัง (มีแถว imported_from='1' อยู่ไหม)
//
// POST {API_BASE}/room-unavailability/import   body: { semester: "1" }
//      -> { inserted: number, skipped: number }
//      รัน INSERT ... ON CONFLICT DO NOTHING พร้อม tag imported_from
//
// DELETE {API_BASE}/room-unavailability/import  body: { semester: "1" }
//      -> { deleted: number }
//      รัน DELETE WHERE imported_from = ?semester
// ============================================================

type Semester = "1" | "2";

interface ImportStatus {
  imported: boolean;
  count: number;
}

export default function ImportUnavailabilityRow() {
  const [semester, setSemester] = useState<Semester>("1");
  const [status, setStatus] = useState<ImportStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmOff, setConfirmOff] = useState(false);

  const loadStatus = useCallback(async (sem: Semester) => {
    setStatusLoading(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE}/room-unavailability/import-status?semester=${sem}`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      setStatus(data);
    } catch {
      setError("ไม่สามารถตรวจสอบสถานะข้อมูลนำเข้าได้");
      setStatus(null);
    } finally {
      setStatusLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStatus(semester);
  }, [semester, loadStatus]);

  // กด switch ตอน "ยังไม่ import" -> ใช้ข้อมูลเดิมทันที (เสี่ยงต่ำ แค่เพิ่มข้อมูล)
  async function handleImport() {
    setBusy(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE}/room-unavailability/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ semester }),
      });
      if (!res.ok) throw new Error();
      const data = await res.json();
      setStatus({ imported: true, count: (status?.count ?? 0) + data.inserted });
    } catch {
      setError("นำเข้าข้อมูลไม่สำเร็จ กรุณาลองใหม่");
    } finally {
      setBusy(false);
    }
  }

  // กด switch ตอน "import อยู่แล้ว" -> ต้อง confirm ก่อน เพราะเป็นการลบข้อมูลจริง
  async function handleRemoveConfirmed() {
    setBusy(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE}/room-unavailability/import`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ semester }),
      });
      if (!res.ok) throw new Error();
      setStatus({ imported: false, count: 0 });
    } catch {
      setError("ลบข้อมูลไม่สำเร็จ กรุณาลองใหม่");
    } finally {
      setBusy(false);
      setConfirmOff(false);
    }
  }

  const isOn = status?.imported ?? false;

  return (
    <>
      <div className="flex items-center justify-between border border-gray-200 rounded-xl px-4 py-3 mb-4 bg-white">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-orange-50 text-orange-500 flex items-center justify-center shrink-0">
            <UploadCloud size={15} />
          </div>
          <div>
            <div className="text-sm font-medium text-gray-700">
              นำเข้าข้อมูลห้องไม่ว่างจากภาคเรียนก่อนหน้า
            </div>
            {!statusLoading && status && (
              <div className="text-[12px] text-gray-400 mt-0.5">
                {isOn ? `นำเข้าแล้ว ${status.count.toLocaleString()} แถว` : "ยังไม่ได้นำเข้า"}
              </div>
            )}
            {error && <div className="text-[12px] text-red-500 mt-0.5">{error}</div>}
          </div>
        </div>

        <div className="flex items-center gap-3">
          <select
            value={semester}
            onChange={(e) => setSemester(e.target.value as Semester)}
            disabled={busy}
            className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm outline-none bg-white focus:border-orange-300 cursor-pointer disabled:opacity-50"
          >
            <option value="1">ภาค 1</option>
            <option value="2">ภาค 2</option>
          </select>

          <button
            role="switch"
            aria-checked={isOn}
            disabled={busy || statusLoading}
            onClick={() => (isOn ? setConfirmOff(true) : handleImport())}
            className={`relative w-11 h-6 rounded-full transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed
              ${isOn ? "bg-orange-500" : "bg-gray-200"}`}
          >
            <span
              className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform flex items-center justify-center
                ${isOn ? "translate-x-5" : "translate-x-0"}`}
            >
              {busy && <Loader2 size={11} className="animate-spin text-gray-400" />}
            </span>
          </button>
        </div>
      </div>

      {confirmOff && (
        <div
          className="fixed inset-0 bg-black/30 backdrop-blur-[2px] z-50 flex items-center justify-center p-4"
          onClick={() => !busy && setConfirmOff(false)}
        >
          <div className="bg-white rounded-2xl shadow-2xl p-6 w-96" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between mb-4">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-lg bg-red-50 text-red-500 flex items-center justify-center shrink-0">
                  <AlertTriangle size={17} />
                </div>
                <h3 className="text-[15px] font-bold text-gray-900">ลบข้อมูลที่นำเข้า?</h3>
              </div>
              <button
                onClick={() => !busy && setConfirmOff(false)}
                className="text-gray-300 hover:text-gray-500 transition-colors cursor-pointer"
              >
                <X size={18} />
              </button>
            </div>

            <p className="text-sm text-gray-500 mb-5">
              จะลบข้อมูลห้องไม่ว่าง{" "}
              <span className="font-semibold text-gray-700">
                {status?.count.toLocaleString() ?? 0} แถว
              </span>{" "}
              ที่นำเข้าจากภาค {semester} ทั้งหมด ข้อมูลที่แก้ไขเองไว้จะไม่ถูกลบ
              <br />
              <span className="text-red-500 font-medium">การกระทำนี้ย้อนกลับไม่ได้</span>
            </p>

            <div className="flex gap-2.5">
              <button
                onClick={() => setConfirmOff(false)}
                disabled={busy}
                className="flex-1 py-2.5 rounded-xl border border-gray-200 text-gray-600 text-sm font-semibold hover:bg-gray-50 cursor-pointer transition-colors disabled:opacity-50"
              >
                ยกเลิก
              </button>
              <button
                onClick={handleRemoveConfirmed}
                disabled={busy}
                className="flex-1 py-2.5 rounded-xl bg-red-500 hover:bg-red-600 text-white text-sm font-semibold cursor-pointer disabled:bg-red-200 transition-colors flex items-center justify-center gap-1.5"
              >
                {busy ? <><Loader2 size={14} className="animate-spin" /> กำลังลบ...</> : "ลบข้อมูล"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}