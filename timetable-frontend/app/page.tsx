"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { RefreshCw, Sparkles, MessageCircle, AlertCircle, Bell, AlertTriangle, Trash2, X, Loader2, FileDown, ChevronDown } from "lucide-react";
import { ScheduleItem, ExistingItem, Timeslot, API_BASE, primeSubjectColors } from "../components/types";
import ScheduleGrid, { PreferredItem } from "../components/ScheduleGrid";
import SchedulePrintTable from "../components/SchedulePrintTable";
import Chatbot from "../components/Chatbot";

const USER_ID = "teacher_01";

interface Group {
  group_id: string;
  group_name: string;
  total_students: number;
  major: string; // 'CS' | 'IT'
}

interface Subject {
  subject_id: string;
  name_thai: string;
  name_english?: string;
}

// วิชา/session ที่ auto_assign_all() จัดไม่ได้เลยตั้งแต่ต้น (ไม่มีที่ว่างให้จัด) —
// ตรงกับ _fail_entry() ใน auto_assign.py ฝั่ง backend
interface FailedSession {
  session_id: string;
  subject_id: string | null;
  session_type: "LECTURE" | "LAB" | string | null;
  section: string | null;
  group_ids: string[] | null;
  reason: string;
}

// ดึงเลขปีจากท้าย group_id ไม่ว่าจะมี prefix (IT-, CS-, ไม่มีเลย) นำหน้าหรือไม่
function yearNumber(group_id: string): string {
  const match = group_id.match(/Y(\d+)$/i);
  return match ? match[1] : "?";
}

const MAJOR_LABELS: Record<string, string> = {
  CS: "วิทยาการคอมพิวเตอร์",
  IT: "เทคโนโลยีสารสนเทศ",
};
function majorNameOf(major: string): string {
  return MAJOR_LABELS[major] ?? major;
}

function fullYearLabel(group_id: string, major: string): string {
  return `นิสิตชั้นปีที่ ${yearNumber(group_id)} · ${majorNameOf(major)}`;
}

// ธีมสีต่อสาขา: CS = ส้ม (เดิม), IT = ม่วง
const MAJOR_THEME: Record<string, { border: string; headerBg: string; headerText: string; dot: string }> = {
  CS: {
    border: "border-orange-200",
    headerBg: "bg-orange-50",
    headerText: "text-orange-600",
    dot: "bg-orange-400",
  },
  IT: {
    border: "border-purple-200",
    headerBg: "bg-purple-50",
    headerText: "text-purple-600",
    dot: "bg-purple-400",
  },
};
function themeOf(major: string) {
  return MAJOR_THEME[major] ?? { border: "border-gray-200", headerBg: "bg-gray-50", headerText: "text-gray-600", dot: "bg-gray-400" };
}

function ScheduleGridSlot({
  group,
  major,
  year,
  scheduleByGroup,
  existing,
  preferred,
  timeslots,
  onRefresh,
}: {
  group?: Group;
  major: string;
  year: string;
  scheduleByGroup: Record<string, ScheduleItem[]>;
  existing: ExistingItem[];
  preferred: PreferredItem[];
  timeslots: Timeslot[];
  onRefresh: () => void;
}) {
  if (!group) {
    return (
      <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50/40 p-5 flex items-center justify-center min-h-[120px] text-center">
        <div className="text-sm text-gray-400">
          ปีที่ {year} · {majorNameOf(major)}
          <div className="text-xs text-gray-300 mt-1">ยังไม่มีข้อมูล</div>
        </div>
      </div>
    );
  }

  return (
    <ScheduleGrid
      items={scheduleByGroup[group.group_id] ?? []}
      existing={existing}
      preferred={preferred}
      year={group.group_id}
      groupName={fullYearLabel(group.group_id, group.major)}
      timeslots={timeslots}
      onRefresh={onRefresh}
      theme={major === "IT" ? "purple" : "orange"}
    />
  );
}

// ─────────────────────────────────────────────────────────────
// fetch GET แบบบังคับไม่ให้ browser cache คำตอบไว้เลย (สำคัญมาก!)
function fetchFresh(url: string) {
  return fetch(url, { cache: "no-store" });
}

export default function SchedulePage() {
  const [groups, setGroups] = useState<Group[]>([]);
  const [subjects, setSubjects] = useState<Subject[]>([]);
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

  // ผลลัพธ์ "จัดไม่ครบ" จากการ generate ล่าสุด — เอาเฉพาะ "วิชาที่จัดไม่ได้เลย"
  // (failedSessions) มาโชว์เท่านั้น
  //
  // หมายเหตุ (แก้ไขล่าสุด): backend ยังส่ง hard_issues กลับมาด้วย (เช่น
  // full_day, lecture_before_lab — เป็นปัญหาที่วิชาถูกจัดลงตารางแล้วจริงๆ
  // แค่ไม่ตรง constraint บางอย่าง ไม่ใช่ "จัดไม่ได้") แต่ตั้งใจไม่เอามาโชว์ใน
  // panel นี้แล้ว เพราะไม่ใช่ปัญหาใหญ่ ไม่อยากให้ปนกับ "จัดวิชานี้ไม่ได้" ซึ่ง
  // เป็นปัญหาที่สำคัญกว่ามาก จึงไม่ดึง hard_issues มาใช้เลยในหน้านี้
  const [failedSessions, setFailedSessions] = useState<FailedSession[]>([]);
  const [unscheduledPanelOpen, setUnscheduledPanelOpen] = useState(false);

  const [generateResult, setGenerateResult] = useState<
    { complete: boolean; unscheduledCount: number } | null
  >(null);

  const printAreaRef = useRef<HTMLDivElement>(null);

  async function fetchScheduleData() {
    const [g, s, e, t, p, subj] = await Promise.all([
      fetchFresh(`${API_BASE}/groups`),
      fetchFresh(`${API_BASE}/schedule`),
      fetchFresh(`${API_BASE}/existing`),
      fetchFresh(`${API_BASE}/timeslots`),
      fetchFresh(`${API_BASE}/preferred-timeslots`),
      fetchFresh(`${API_BASE}/subjects`),
    ]);
    const [gd, sd, ed, td, pd, subjd] = await Promise.all([g.json(), s.json(), e.json(), t.json(), p.json(), subj.json()]);

    const groupList: Group[] = Array.isArray(gd) ? gd : [];
    groupList.sort((a, b) => a.group_id.localeCompare(b.group_id));
    setGroups(groupList);

    const safeSchedule: Record<string, ScheduleItem[]> = {};
    for (const grp of groupList) {
      const key = grp.group_id.toLowerCase();
      const fromKey = sd?.[grp.group_id] ?? sd?.[key];
      safeSchedule[grp.group_id] = Array.isArray(fromKey) ? fromKey : [];
    }

    primeSubjectColors(safeSchedule);
    setScheduleByGroup(safeSchedule);

    setExisting(Array.isArray(ed) ? ed : []);
    setTimeslots(Array.isArray(td) ? td : []);
    setPreferred(Array.isArray(pd) ? pd : []);
    setSubjects(Array.isArray(subjd) ? subjd : []);
  }

  // เช็คสถานะตารางปัจจุบัน (ครบ/ไม่ครบ) จาก backend โดยไม่จัดใหม่ — ตั้งใจไม่
  // อ่าน data.hard_issues เลย (ดู comment ที่ state failedSessions ด้านบน)
  // นับความครบถ้วนจาก failed_sessions อย่างเดียว
  const checkScheduleStatus = useCallback(async () => {
    try {
      const res = await fetchFresh(`${API_BASE}/schedule-status`);
      const data = await res.json().catch(() => ({}));
      const nextFailed: FailedSession[] = Array.isArray(data.failed_sessions) ? data.failed_sessions : [];
      setFailedSessions(nextFailed);
      setGenerateResult({
        complete: nextFailed.length === 0,
        unscheduledCount: nextFailed.length,
      });
    } catch {
      // เงียบไว้ — ถ้าเช็คสถานะไม่ได้ ไม่ต้องขึ้น error รบกวนผู้ใช้ แค่ไม่โชว์แบนเนอร์
    }
  }, []);

  const loadSchedule = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      await fetchScheduleData();
      await checkScheduleStatus();
    } catch {
      setError("ไม่สามารถโหลดตารางเรียนได้ กรุณาตรวจสอบการเชื่อมต่อ API");
    } finally {
      setLoading(false);
    }
  }, [checkScheduleStatus]);

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
    setGenerateResult(null);
    try {
      // TODO: ลบบรรทัดนี้ทิ้งหลังเทส skeleton เสร็จ
      await new Promise((resolve) => setTimeout(resolve, 3000));
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

  function handleExportPdf() {
    window.print();
  }

  const byYear = new Map<string, { cs?: Group; it?: Group; others: Group[] }>();
  for (const g of groups) {
    const y = yearNumber(g.group_id);
    if (!byYear.has(y)) byYear.set(y, { others: [] });
    const bucket = byYear.get(y)!;
    if (g.major === "CS") bucket.cs = g;
    else if (g.major === "IT") bucket.it = g;
    else bucket.others.push(g);
  }
  const years = Array.from(byYear.keys()).sort((a, b) => Number(a) - Number(b));

  function subjectNameOf(subject_id: string | null): string {
    if (!subject_id) return "-";
    const s = subjects.find((x) => x.subject_id === subject_id);
    return s ? `${s.subject_id} · ${s.name_thai}` : subject_id;
  }

  function groupLabelOf(group_ids: string[] | null): string {
    if (!group_ids || group_ids.length === 0) return "-";
    return group_ids
      .map((g) => {
        const major = g.toUpperCase().startsWith("IT-") ? "IT" : "CS";
        const year = yearNumber(g);
        return `${major} ปี ${year}`;
      })
      .join(", ");
  }

  const unscheduledCount = failedSessions.length;

  const showSkeleton = loading || generating;

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
      <main className="flex-1 overflow-y-auto px-6 py-6 print:overflow-visible print:h-auto">

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-red-600 text-sm mb-5 flex items-center gap-2 no-print">
            <AlertCircle size={15} className="shrink-0" />
            {error}
          </div>
        )}

        {/* Page title + actions */}
        <div className="flex items-end justify-between mb-6 no-print">
          <div>
            <h1 className="text-xl font-bold text-gray-900">ตารางเรียน</h1>
            <p className="text-[13px] text-gray-400 mt-0.5">ภาควิชาวิทยาการคอมพิวเตอร์และเทคโนโลยีสารสนเทศ</p>
          </div>
          <div className="flex items-center gap-2">
            {/* ไอคอนแจ้งเตือนสถานะการจัดตาราง — โชว์เฉพาะ "วิชาที่จัดไม่ได้เลย"
                (failedSessions) เท่านั้น ไม่เอา hard_issues (full_day,
                lecture_before_lab ฯลฯ) มาปนแล้ว เพราะเป็นปัญหาเล็กน้อยกว่ามาก */}
            {generateResult && (
              <div className="relative">
                <button
                  onClick={() => setUnscheduledPanelOpen((v) => !v)}
                  className="relative flex items-center justify-center w-9 h-9 rounded-full border border-gray-200 bg-white hover:bg-gray-50 text-gray-500 cursor-pointer transition-colors"
                  title={generateResult.complete ? "จัดครบทุกวิชาแล้ว" : `จัดวิชาไม่ได้ ${generateResult.unscheduledCount} รายการ`}
                >
                  <Bell size={16} />
                  {!generateResult.complete && unscheduledCount > 0 && (
                    <span className="absolute -top-1 -right-1 flex items-center justify-center min-w-[16px] h-[16px] rounded-full bg-red-500 text-white text-[10px] font-medium px-1">
                      {unscheduledCount}
                    </span>
                  )}
                </button>

                {unscheduledPanelOpen && (
                  <div
                    className={`absolute right-0 top-full mt-2 max-h-96 overflow-y-auto bg-white rounded-lg border border-gray-200 shadow-md z-40
                      ${generateResult.complete ? "w-56" : "w-96"}`}
                  >
                    {generateResult.complete ? (
                      <div className="px-4 py-3.5 text-center text-[13px] text-gray-600 whitespace-nowrap">
                        จัดตารางครบทุกวิชาแล้ว
                      </div>
                    ) : (
                      <>
                        <div className="px-4 py-2.5 border-b border-gray-100 text-[13px] font-medium text-gray-600">
                          วิชาที่จัดไม่ได้ ({unscheduledCount})
                        </div>

                        <div>
                          {failedSessions.map((f, i) => (
                            <div
                              key={f.session_id}
                              className={`px-4 py-2.5 ${i !== 0 ? "border-t border-gray-50" : ""}`}
                            >
                              <div className="text-[12px] text-gray-600">
                                {subjectNameOf(f.subject_id)}
                              </div>
                              <div className="text-[12px] text-gray-800 mt-0.5">
                                {groupLabelOf(f.group_ids)}
                                {f.session_type && (
                                  <span className="ml-1.5 text-[11px] text-gray-400">
                                    {f.session_type}{f.section ? ` · section ${f.section}` : ""}
                                  </span>
                                )}
                              </div>
                              <div className="text-[12px] text-gray-400 mt-0.5">{f.reason}</div>
                            </div>
                          ))}
                        </div>

                        <div className="px-4 py-2.5 border-t border-gray-100 text-[12px] text-gray-400">
                          ไปที่ตารางด้านล่าง แล้วเพิ่ม/ย้ายวิชาเหล่านี้ด้วยตนเอง
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            )}

            <button
              onClick={loadSchedule}
              disabled={loading}
              className="flex items-center gap-1.5 bg-white hover:bg-gray-50 text-gray-600 border border-gray-200 rounded-lg px-3.5 py-1.5 text-sm font-medium cursor-pointer transition-colors disabled:opacity-50"
            >
              <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
              รีเฟรช
            </button>
            <button
              onClick={handleExportPdf}
              disabled={loading || groups.length === 0}
              className="flex items-center gap-1.5 bg-white hover:bg-gray-50 text-gray-600 border border-gray-200 rounded-lg px-3.5 py-1.5 text-sm font-medium cursor-pointer transition-colors disabled:opacity-50"
            >
              <FileDown size={13} />
              Export PDF
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

            <div className="w-px h-5 bg-gray-200 mx-1" />

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

        <div id="schedule-print-area" ref={printAreaRef} className="no-print">
          {showSkeleton ? (
            <>
              <div className="grid grid-cols-2 gap-5 mb-4">
                <div className="skeleton h-9 w-full rounded-xl" />
                <div className="skeleton h-9 w-full rounded-xl" />
              </div>
              <div className="space-y-5">
                {[1, 2, 3, 4].map((n) => (
                  <div key={n} className="grid grid-cols-2 gap-5">
                    <div className="p-1">
                      <div className="skeleton h-5 w-44 rounded mb-4" />
                      <div className="skeleton h-52 w-full rounded-lg" />
                    </div>
                    <div className="p-1">
                      <div className="skeleton h-5 w-44 rounded mb-4" />
                      <div className="skeleton h-52 w-full rounded-lg" />
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : groups.length === 0 ? (
            <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-8 text-center text-sm text-gray-400">
              ยังไม่มีข้อมูลชั้นปี (student_group) กรุณาตรวจสอบข้อมูลใน Supabase
            </div>
          ) : (
            <>
              <div className="space-y-2">
                {years.map((y) => {
                  const { cs, it, others } = byYear.get(y)!;
                  return (
                    <div key={y} className="grid grid-cols-2 gap-5 print-break-inside-avoid">
                      <ScheduleGridSlot group={cs} major="CS" scheduleByGroup={scheduleByGroup} existing={existing} preferred={preferred} timeslots={timeslots} onRefresh={refreshSilently} year={y} />
                      <ScheduleGridSlot group={it} major="IT" scheduleByGroup={scheduleByGroup} existing={existing} preferred={preferred} timeslots={timeslots} onRefresh={refreshSilently} year={y} />
                      {others.map((g) => (
                        <div key={g.group_id} className={`rounded-xl border-2 ${themeOf(g.major).border} overflow-hidden col-span-2`}>
                          <ScheduleGrid
                            items={scheduleByGroup[g.group_id] ?? []}
                            existing={existing}
                            preferred={preferred}
                            year={g.group_id}
                            groupName={fullYearLabel(g.group_id, g.major)}
                            timeslots={timeslots}
                            onRefresh={refreshSilently}
                          />
                        </div>
                      ))}
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>

        <SchedulePrintTable groups={groups} scheduleByGroup={scheduleByGroup} />

      </main>

      <div className="no-print">
        <Chatbot
          open={chatOpen}
          onClose={() => setChatOpen(false)}
          userId={USER_ID}
          onScheduleGenerated={loadSchedule}
        />
      </div>

      <style jsx global>{`
        .print-only {
          display: none;
        }
        @media print {
          .no-print {
            display: none !important;
          }
          .print-only {
            display: block !important;
          }
          @page {
            size: landscape;
            margin: 12mm;
          }
        }
      `}</style>
    </>
  );
}