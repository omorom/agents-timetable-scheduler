"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { RefreshCw, Sparkles, MessageCircle, AlertCircle, Trash2, X, Loader2, FileDown } from "lucide-react";
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

// การ์ดตารางของ 1 กลุ่ม (CS หรือ IT) สำหรับ 1 ชั้นปี วางในคอลัมน์ซ้าย/ขวา
// ถ้ากลุ่มนั้นไม่มีข้อมูล (undefined) ให้โชว์กรอบเส้นประว่างแทน กันเลย์เอาต์เพี้ยน
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

  // ref ของพื้นที่ตารางทั้งหมด — ใช้ตอน export PDF เพื่อสั่ง print เฉพาะส่วนนี้
  // (ไม่รวม sidebar/ปุ่ม action ต่าง ๆ) ผ่าน CSS media print ที่ id "schedule-print-area"
  const printAreaRef = useRef<HTMLDivElement>(null);

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
    // เรียงตาม group_id ให้แสดงผลเป็นลำดับ (ยังใช้ได้ตามเดิม แม้จะแยกกลุ่ม CS/IT ทีหลังแล้ว)
    groupList.sort((a, b) => a.group_id.localeCompare(b.group_id));
    setGroups(groupList);

    // sd คาดว่าเป็น { [group_id]: ScheduleItem[] } เช่น { Y1: [...], "IT-Y1": [...] }
    const safeSchedule: Record<string, ScheduleItem[]> = {};
    for (const grp of groupList) {
      const key = grp.group_id.toLowerCase(); // เผื่อ backend ส่งเป็น key ตัวเล็ก
      const fromKey = sd?.[grp.group_id] ?? sd?.[key];
      safeSchedule[grp.group_id] = Array.isArray(fromKey) ? fromKey : [];
    }

    // จองสีให้วิชาที่สอนหลายชั้นปี (เช่น LECTURE รวมข้ามชั้นปี/สาขา) ให้ตรงกัน
    // ทุกตารางก่อน แล้วค่อย setScheduleByGroup ให้ re-render การ์ดด้วยสีที่พร้อม
    // แล้ว — ต้องเรียกก่อน set state เสมอ ไม่งั้นการ์ดแรกที่ render จะไปแจกสี
    // แบบ per-group ทั่วไปก่อนที่ระบบจะรู้ว่าวิชาไหนต้องจองสีข้ามชั้นปีบ้าง
    primeSubjectColors(safeSchedule);
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

  // Export เป็น PDF ผ่าน browser print dialog — ผู้ใช้เลือก "Save as PDF" เป็น
  // ปลายทางได้เอง ไม่ต้องพึ่ง library ฝั่ง client เพิ่ม (jsPDF/html2canvas ฯลฯ)
  // ตอนพิมพ์จะโชว์เป็นตารางข้อมูล (SchedulePrintTable) แทนตารางกริดที่เห็นบนจอ
  // เพราะกริดอ่านยากเวลาพิมพ์ออกกระดาษ — ดู .print-only + @media print ด้านล่าง
  function handleExportPdf() {
    window.print();
  }

  // จัดกลุ่มตามเลขปี แล้วแยก CS / IT ไว้คนละคอลัมน์ในแต่ละแถว
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

            {/* เส้นแบ่งกันปุ่ม "ล้างตาราง" (destructive) ออกจากกลุ่ม action ปกติ
                ให้รู้สึกเป็นคนละกลุ่มชัดเจน ลดโอกาสกดพลาดตอนมือไล่จากซ้ายไปขวา */}
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

        {/* Grids: 2 คอลัมน์ข้างกัน ซ้าย = CS (ส้ม), ขวา = IT (ม่วง), เรียงตามชั้นปี
            — โชว์เฉพาะบนจอ ตอนพิมพ์ถูกซ่อนด้วย .no-print (ใช้ตาราง list ด้านล่างแทน) */}
        <div id="schedule-print-area" ref={printAreaRef} className="no-print">
          {loading ? (
            <>
              {/* หัวคอลัมน์ */}
              <div className="grid grid-cols-2 gap-5 mb-4">
                <div className="skeleton h-9 w-full rounded-xl" />
                <div className="skeleton h-9 w-full rounded-xl" />
              </div>
              <div className="space-y-5">
                {[1, 2].map((n) => (
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

        {/* ตาราง list สำหรับพิมพ์/Export PDF (ซ่อนบนจอด้วย .print-only ใน component เอง)
            แยกออกมาเป็น component ต่างหากเพราะ logic การรวม/เรียง row ค่อนข้างเยอะ */}
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

      {/* Print-only styles: ปกติซ่อน .print-only (ตาราง list) ไว้บนจอ และซ่อน
          .no-print (กริด, ปุ่ม action, chatbot) ตอนสั่งพิมพ์/Save as PDF แทน —
          สลับกันเป๊ะ ๆ ระหว่างจอกับกระดาษ ไม่ต้องพึ่ง visibility ทั้งหน้าแบบเดิม
          ซึ่งเสี่ยงเว้นที่ว่างของ element ที่ถูกซ่อนไว้ */}
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