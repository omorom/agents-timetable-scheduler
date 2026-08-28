"use client";

import { useState, useEffect, useCallback } from "react";
import { RefreshCw, Sparkles, MessageCircle, AlertCircle, Trash2, X, Loader2 } from "lucide-react";
import { ScheduleItem, ExistingItem, Timeslot, API_BASE } from "../components/types";
import ScheduleGrid, { PreferredItem } from "../components/ScheduleGrid";
import Chatbot from "../components/Chatbot";

const USER_ID = "teacher_01";

interface Group {
  group_id: string;
  group_name: string;
  total_students: number;
}

// แปลง group_id (Y1, Y2, ...) เป็น "นิสิตชั้นปีที่ 1" แทนข้อความดิบจาก DB เช่น "year 1"
function fullYearLabel(group_id: string, fallback: string): string {
  const match = group_id.match(/^Y(\d+)$/i);
  return match ? `นิสิตชั้นปีที่ ${match[1]}` : fallback;
}

export default function SchedulePage() {
  const [groups, setGroups] = useState<Group[]>([]);
  const [scheduleByGroup, setScheduleByGroup] = useState<Record<string, ScheduleItem[]>>({});
  const [existing, setExisting] = useState<ExistingItem[]>([]);
  const [preferred, setPreferred] = useState<PreferredItem[]>([]);
  const [timeslots, setTimeslots] = useState<Timeslot[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [clearConfirmOpen, setClearConfirmOpen] = useState(false);
  const [error, setError] = useState("");
  const [chatOpen, setChatOpen] = useState(false);

  async function fetchScheduleData() {
    const [g, s, e, t, p] = await Promise.all([
      fetch(`${API_BASE}/groups`),
      fetch(`${API_BASE}/schedule`),
      fetch(`${API_BASE}/existing`),
      fetch(`${API_BASE}/timeslots`),
      fetch(`${API_BASE}/preferred-timeslots`),
    ]);
    const [gd, sd, ed, td, pd] = await Promise.all([g.json(), s.json(), e.json(), t.json(), p.json()]);

    const groupList: Group[] = Array.isArray(gd) ? gd : [];
    // เรียงตาม group_id (Y1, Y2, Y3, Y4, ...) ให้แสดงผลเป็นลำดับ
    groupList.sort((a, b) => a.group_id.localeCompare(b.group_id));
    setGroups(groupList);

    // sd คาดว่าเป็น { [group_id]: ScheduleItem[] } เช่น { Y1: [...], Y2: [...] }
    // หรือถ้ายังไม่มีข้อมูลจริง จะได้ object ว่าง/ไม่ครบ ก็ fallback เป็น [] ต่อ group ไป
    const safeSchedule: Record<string, ScheduleItem[]> = {};
    for (const grp of groupList) {
      const key = grp.group_id.toLowerCase(); // เผื่อ backend ส่งเป็น key ตัวเล็ก เช่น y1, y2
      const fromKey = sd?.[grp.group_id] ?? sd?.[key];
      safeSchedule[grp.group_id] = Array.isArray(fromKey) ? fromKey : [];
    }
    setScheduleByGroup(safeSchedule);

    setExisting(Array.isArray(ed) ? ed : []);
    setTimeslots(Array.isArray(td) ? td : []);
    setPreferred(Array.isArray(pd) ? pd : []);
  }

  const loadSchedule = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      await fetchScheduleData();
    } catch {
      setError("ไม่สามารถโหลดตารางเรียนได้ กรุณาตรวจสอบการเชื่อมต่อ API");
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshSilently = useCallback(async () => {
    try {
      await fetchScheduleData();
    } catch {
      setError("ไม่สามารถโหลดตารางเรียนได้ กรุณาตรวจสอบการเชื่อมต่อ API");
    }
  }, []);

  useEffect(() => { loadSchedule(); }, [loadSchedule]);

  async function handleGenerate() {
    setGenerating(true);
    setError("");
    try {
      await fetch(`${API_BASE}/generate`, { method: "POST" });
      await loadSchedule();
    } catch {
      setError("สร้างตารางไม่สำเร็จ กรุณาลองใหม่");
    } finally {
      setGenerating(false);
    }
  }

  async function handleClear() {
    setClearing(true);
    setError("");
    try {
      await fetch(`${API_BASE}/clear`, { method: "POST" });
      await loadSchedule();
    } catch {
      setError("ล้างตารางไม่สำเร็จ กรุณาลองใหม่");
    } finally {
      setClearing(false);
      setClearConfirmOpen(false);
    }
  }

  return (
    <>
      {/* Clear confirm modal */}
      {clearConfirmOpen && (
        <div className="fixed inset-0 bg-black/30 backdrop-blur-[2px] z-50 flex items-center justify-center animate-fade-up">
          <div className="bg-white rounded-2xl shadow-2xl p-6 w-96 mx-4">
            <div className="flex items-start justify-between mb-4">
              <div>
                <h3 className="text-[15px] font-bold text-gray-900">ยืนยันการล้างตาราง</h3>
                <p className="text-xs text-gray-400 mt-0.5">การดำเนินการนี้ไม่สามารถย้อนกลับได้</p>
              </div>
              <button onClick={() => setClearConfirmOpen(false)} className="text-gray-300 hover:text-gray-500 transition-colors cursor-pointer">
                <X size={18} />
              </button>
            </div>
            <div className="bg-red-50 rounded-xl p-4 mb-4 text-sm text-red-600 border border-red-100">
              ต้องการลบตารางเรียนทั้งหมดเลยใช่ไหม?
            </div>
            <div className="flex gap-2.5">
              <button
                onClick={() => setClearConfirmOpen(false)}
                className="flex-1 py-2.5 rounded-xl border border-gray-200 text-gray-600 text-sm font-semibold hover:bg-gray-50 cursor-pointer transition-colors"
              >
                ยกเลิก
              </button>
              <button
                onClick={handleClear}
                disabled={clearing}
                className="flex-1 py-2.5 rounded-xl bg-red-500 hover:bg-red-600 text-white text-sm font-semibold cursor-pointer disabled:bg-red-200 transition-colors flex items-center justify-center gap-1.5"
              >
                {clearing
                  ? <><Loader2 size={14} className="animate-spin" /> กำลังล้าง...</>
                  : "ล้างตารางเลย"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Content */}
      <main className="flex-1 overflow-y-auto px-6 py-6">

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-red-600 text-sm mb-5 flex items-center gap-2">
            <AlertCircle size={15} className="shrink-0" />
            {error}
          </div>
        )}

        {/* Page title + actions */}
        <div className="flex items-end justify-between mb-6">
          <div>
            <h1 className="text-xl font-bold text-gray-900">ตารางเรียน</h1>
            <p className="text-[13px] text-gray-400 mt-0.5">ภาควิชาวิทยาการคอมพิวเตอร์และเทคโนโลยีสารสนเทศ</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={loadSchedule}
              disabled={loading}
              className="flex items-center gap-1.5 bg-white hover:bg-gray-50 text-gray-600 border border-gray-200 rounded-lg px-3.5 py-1.5 text-sm font-medium cursor-pointer transition-colors disabled:opacity-50"
            >
              <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
              รีเฟรช
            </button>
            <button
              onClick={handleGenerate}
              disabled={generating || loading}
              className={`flex items-center gap-1.5 text-white border-none rounded-lg px-4 py-1.5 text-sm font-semibold transition-colors
                ${generating || loading
                  ? "bg-orange-300 cursor-default"
                  : "bg-orange-500 hover:bg-orange-600 cursor-pointer shadow-sm shadow-orange-200"}`}
            >
              <Sparkles size={13} />
              {generating ? "กำลังสร้าง..." : "สร้างตาราง"}
            </button>
            <button
              onClick={() => setClearConfirmOpen(true)}
              disabled={generating || loading}
              className="flex items-center gap-1.5 bg-white hover:bg-red-50 text-red-500 border border-red-200 rounded-lg px-3.5 py-1.5 text-sm font-medium cursor-pointer transition-colors disabled:opacity-50"
            >
              <Trash2 size={13} />
              ล้างตาราง
            </button>
          </div>
        </div>

        {/* Grids */}
        {loading ? (
          <div className="space-y-5">
            {groups.length > 0
              ? groups.map((g) => (
                  <div key={g.group_id} className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
                    <div className="skeleton h-5 w-44 rounded mb-4" />
                    <div className="skeleton h-52 w-full rounded-lg" />
                  </div>
                ))
              : [1, 2].map((n) => (
                  <div key={n} className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
                    <div className="skeleton h-5 w-44 rounded mb-4" />
                    <div className="skeleton h-52 w-full rounded-lg" />
                  </div>
                ))}
          </div>
        ) : (
          <div className="space-y-5">
            {groups.length === 0 ? (
              <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-8 text-center text-sm text-gray-400">
                ยังไม่มีข้อมูลชั้นปี (student_group) กรุณาตรวจสอบข้อมูลใน Supabase
              </div>
            ) : (
              groups.map((g) => (
                <ScheduleGrid
                  key={g.group_id}
                  items={scheduleByGroup[g.group_id] ?? []}
                  existing={existing}
                  preferred={preferred}
                  year={g.group_id}
                  groupName={fullYearLabel(g.group_id, g.group_name)}
                  timeslots={timeslots}
                  onRefresh={refreshSilently}
                />
              ))
            )}
          </div>
        )}

      </main>

      <Chatbot
        open={chatOpen}
        onClose={() => setChatOpen(false)}
        userId={USER_ID}
        onScheduleGenerated={loadSchedule}
      />
    </>
  );
}