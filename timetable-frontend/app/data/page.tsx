"use client";

import { useState, useEffect, useCallback } from "react";
import { RefreshCw, AlertCircle, DoorOpen, Users, GraduationCap, Search, Pencil, X, Loader2 } from "lucide-react";
import { API_BASE } from "../../components/types";
import UnavailabilityModal from "../../components/UnavailabilityModal";
import ImportUnavailabilityRow from "../../components/ImportUnavailabilityRow";

interface Room {
  room_id: string;
  room_name?: string;
  capacity?: number;
  room_type?: string;
  [key: string]: unknown;
}

interface Teacher {
  teacher_id: string;
  teacher_name: string;
  [key: string]: unknown;
}

interface Group {
  group_id: string;
  group_name: string;
  total_students: number;
  major?: string;
  [key: string]: unknown;
}

// แปลประเภทห้องเป็นภาษาไทย ไม่ว่าจะพิมพ์เล็กใหญ่ยังไงก็แปลได้
function roomTypeTh(type?: string): string {
  const t = (type || "").toUpperCase();
  if (t === "LECTURE") return "ห้องบรรยาย";
  if (t === "LAB") return "ห้องปฏิบัติการ";
  return type || "-";
}



type TabKey = "rooms" | "teachers" | "students";

const TABS: { key: TabKey; label: string; icon: typeof DoorOpen }[] = [
  { key: "rooms", label: "ห้องเรียน", icon: DoorOpen },
  { key: "teachers", label: "อาจารย์", icon: Users },
  { key: "students", label: "นิสิต", icon: GraduationCap },
];

export default function DataPage() {
  const [tab, setTab] = useState<TabKey>("rooms");
  const [rooms, setRooms] = useState<Room[]>([]);
  const [teachers, setTeachers] = useState<Teacher[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [modal, setModal] = useState<{ kind: "teacher" | "room"; id: string; title: string; subtitle?: string } | null>(null);
  const [editingGroup, setEditingGroup] = useState<Group | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [r, t, g] = await Promise.all([
        fetch(`${API_BASE}/rooms`),
        fetch(`${API_BASE}/teachers`),
        fetch(`${API_BASE}/groups`),
      ]);
      const [rd, td, gd] = await Promise.all([r.json(), t.json(), g.json()]);

      setRooms(Array.isArray(rd) ? rd : []);
      setTeachers(Array.isArray(td) ? td : []);

      const groupList: Group[] = Array.isArray(gd) ? gd : [];
      groupList.sort((a, b) => a.group_id.localeCompare(b.group_id));
      setGroups(groupList);
    } catch {
      setError("ไม่สามารถโหลดข้อมูลได้ กรุณาตรวจสอบการเชื่อมต่อ API");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const totalStudents = groups.reduce((sum, g) => sum + (g.total_students || 0), 0);

  return (
    <main className="flex-1 overflow-y-auto px-6 py-8">
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-red-600 text-sm mb-5 flex items-center gap-2">
          <AlertCircle size={15} className="shrink-0" />
          {error}
        </div>
      )}

      {/* Page title + actions */}
      <div className="flex items-end justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-gray-900">ข้อมูลในระบบ</h1>
          <p className="text-[13px] text-gray-400 mt-0.5">ห้องเรียน · อาจารย์ · นิสิต</p>
        </div>
        <button
          onClick={loadData}
          disabled={loading}
          className="flex items-center gap-1.5 bg-white hover:bg-gray-50 text-gray-600 border border-gray-200 rounded-lg px-3.5 py-1.5 text-sm font-medium cursor-pointer transition-colors disabled:opacity-50"
        >
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          รีเฟรช
        </button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <SummaryCard icon={DoorOpen} label="ห้องเรียนทั้งหมด" value={rooms.length} loading={loading} />
        <SummaryCard icon={Users} label="อาจารย์ทั้งหมด" value={teachers.length} loading={loading} />
        <SummaryCard icon={GraduationCap} label="นิสิตทั้งหมด" value={totalStudents} loading={loading} />
      </div>

      {/* Tabs: มินิมอล พื้นเทาอ่อน แท็บ active เป็นพื้นขาว+ตัวหนังสือส้ม ไม่ใช้สีทึบเต็มปุ่ม */}
      <div className="flex items-center gap-1 mb-4 bg-slate-100 rounded-2xl p-1">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => { setTab(key); setSearch(""); }}
            className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium cursor-pointer transition-all
              ${tab === key
                ? "bg-white text-gray-900 shadow-sm"
                : "text-gray-500 hover:text-gray-700"}`}
          >
            <Icon size={16} className={tab === key ? "text-orange-500" : "text-gray-400"} />
            {label}
          </button>
        ))}
      </div>

      {/* Search: ใช้ได้กับทุกแท็บ */}
      <div className="relative mb-4">
        <Search size={16} className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-300" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={
            tab === "rooms" ? "ค้นหาห้องเรียน เช่น รหัสห้อง, ชื่อห้อง..."
            : tab === "teachers" ? "ค้นหาอาจารย์ เช่น ชื่อ..."
            : "ค้นหาชั้นปี..."
          }
          className="w-full border border-gray-200 rounded-xl pl-11 pr-4 py-3 text-sm outline-none bg-white focus:border-orange-300 focus:ring-4 focus:ring-orange-50 transition-all placeholder:text-gray-400"
        />
      </div>

      {/* นำเข้าข้อมูลห้องไม่ว่างจากภาคเรียนก่อนหน้า: โชว์เฉพาะ tab ห้องเรียน */}
      {tab === "rooms" && <ImportUnavailabilityRow />}

      {/* Content */}
      <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
        {loading ? (
          <div className="p-5 space-y-2">
            {[1, 2, 3, 4].map(n => <div key={n} className="skeleton h-10 w-full rounded-lg" />)}
          </div>
        ) : tab === "rooms" ? (
          <RoomsTable
            rooms={rooms.filter((r) => {
              const q = search.trim().toLowerCase();
              if (!q) return true;
              return r.room_id.toLowerCase().includes(q) || (r.room_name || "").toString().toLowerCase().includes(q);
            })}
            total={rooms.length}
            onSelect={(r) =>
              setModal({
                kind: "room",
                id: r.room_id,
                title: (r.room_name as string) ?? r.room_id,
                subtitle: `${roomTypeTh(r.room_type)}${r.capacity != null ? ` · ความจุ ${r.capacity} ที่นั่ง` : ""}`,
              })
            }
          />
        ) : tab === "teachers" ? (
          <TeachersTable
            teachers={teachers.filter((t) =>
              t.teacher_name.toLowerCase().includes(search.trim().toLowerCase())
            )}
            total={teachers.length}
            onSelect={(t) => setModal({ kind: "teacher", id: t.teacher_id, title: t.teacher_name, subtitle: "ตารางเวลาที่ไม่สะดวกสอน" })}
          />
        ) : (
          <StudentsTable
            groups={groups.filter((g) => {
              const q = search.trim().toLowerCase();
              if (!q) return true;
              return groupDisplayName(g).toLowerCase().includes(q) || g.group_id.toLowerCase().includes(q);
            })}
            total={groups.length}
            onEdit={(g) => setEditingGroup(g)}
          />
        )}
      </div>

      {editingGroup && (
        <EditGroupModal
          group={editingGroup}
          onClose={() => setEditingGroup(null)}
          onSaved={(updated) => {
            setGroups((prev) => prev.map((g) => (g.group_id === updated.group_id ? { ...g, ...updated } : g)));
            setEditingGroup(null);
          }}
        />
      )}

      {modal && (
        <UnavailabilityModal
          kind={modal.kind}
          entityId={modal.id}
          title={modal.title}
          subtitle={modal.subtitle}
          onClose={() => setModal(null)}
        />
      )}
    </main>
  );
}

function SummaryCard({
  icon: Icon,
  label,
  value,
  loading,
}: {
  icon: typeof DoorOpen;
  label: string;
  value: number;
  loading: boolean;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 flex items-center gap-3">
      <div className="w-10 h-10 rounded-lg bg-orange-50 text-orange-500 flex items-center justify-center shrink-0">
        <Icon size={18} />
      </div>
      <div>
        <div className="text-[11px] text-gray-400 font-medium">{label}</div>
        {loading ? (
          <div className="skeleton h-5 w-10 rounded mt-1" />
        ) : (
          <div className="text-lg font-bold text-gray-900">{value.toLocaleString()}</div>
        )}
      </div>
    </div>
  );
}

function EmptyRow({ colSpan, text }: { colSpan: number; text: string }) {
  return (
    <tr>
      <td colSpan={colSpan} className="text-center text-sm text-gray-400 py-8">
        {text}
      </td>
    </tr>
  );
}

function RoomsTable({ rooms, total, onSelect }: { rooms: Room[]; total: number; onSelect: (r: Room) => void }) {
  return (
    <div>
      <div className="px-5 py-3 border-b border-gray-100 text-[13px] font-semibold text-gray-600">
        ห้องเรียน ({rooms.length}{rooms.length !== total ? ` / ${total}` : ""})
      </div>
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-gray-100">
            <th className="text-left px-5 py-2.5 text-[12px] font-medium text-gray-400">รหัสห้อง</th>
            <th className="text-left px-5 py-2.5 text-[12px] font-medium text-gray-400">ประเภทห้อง</th>
            <th className="text-right px-5 py-2.5 text-[12px] font-medium text-gray-400">ความจุ</th>
          </tr>
        </thead>
        <tbody>
          {rooms.length === 0 ? (
            <EmptyRow colSpan={3} text="ไม่พบห้องเรียนที่ค้นหา" />
          ) : (
            rooms.map((r) => (
              <tr
                key={r.room_id}
                onClick={() => onSelect(r)}
                className="border-b border-gray-50 last:border-0 hover:bg-orange-50/60 transition-colors cursor-pointer"
              >
                <td className="px-5 py-3 text-[13px] text-orange-600 font-medium">
                  {(r.room_name as string) ?? "-"}
                </td>
                <td className="px-5 py-3">
                  <span
                    className={`text-[11px] font-bold px-2.5 py-1 rounded-full
                      ${(r.room_type || "").toUpperCase() === "LAB"
                        ? "bg-blue-50 text-blue-600"
                        : "bg-emerald-50 text-emerald-600"}`}
                  >
                    {roomTypeTh(r.room_type)}
                  </span>
                </td>
                <td className="px-5 py-3 text-[13px] text-gray-600 text-right">
                  {r.capacity != null ? `${r.capacity} ที่นั่ง` : "-"}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function TeachersTable({ teachers, total, onSelect }: { teachers: Teacher[]; total: number; onSelect: (t: Teacher) => void }) {
  return (
    <div>
      <div className="px-5 py-3 border-b border-gray-100 text-[13px] font-semibold text-gray-600">
        อาจารย์ ({teachers.length}{teachers.length !== total ? ` / ${total}` : ""})
      </div>
      {teachers.length === 0 ? (
        <div className="text-center text-sm text-gray-400 py-8">ไม่พบอาจารย์ที่ค้นหา</div>
      ) : (
        <div>
          {teachers.map((t) => (
            <div
              key={t.teacher_id}
              onClick={() => onSelect(t)}
              className="px-5 py-3 text-[13px] text-orange-600 font-medium border-b border-gray-50 last:border-0 hover:bg-orange-50/60 transition-colors cursor-pointer"
            >
              {t.teacher_name}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// แปลรหัสสาขา (จากคอลัมน์ major ใน Supabase) เป็นชื่อเต็มภาษาไทย
function majorNameTh(major?: string): string {
  const m = (major || "").toUpperCase();
  if (m === "CS") return "วิทยาการคอมพิวเตอร์";
  if (m === "IT") return "เทคโนโลยีสารสนเทศ";
  return major || "-";
}

// สีตัวอักษรตามสาขา: IT = ม่วง, CS/COMSCI = ส้ม
function majorTextClass(major?: string): string {
  const m = (major || "").toUpperCase();
  if (m === "IT") return "text-purple-600";
  if (m === "CS") return "text-orange-600";
  return "text-gray-800";
}

// map ชื่อชั้นปีอัตโนมัติจาก group_id (Y1, Y2, ...) + major (CS/IT)
// เช่น group_id="Y1", major="CS" -> "นิสิตสาขาวิทยาการคอมพิวเตอร์ ปี 1"
function groupDisplayName(g: Group): string {
  const match = g.group_id.match(/Y(\d+)$/i);
  const yearNum = match ? match[1] : g.group_id;
  return `นิสิตสาขา${majorNameTh(g.major as string)} ปี ${yearNum}`;
}


function StudentsTable({ groups, total, onEdit }: { groups: Group[]; total: number; onEdit: (g: Group) => void }) {
  return (
    <div>
      <div className="px-5 py-3 border-b border-gray-100 text-[13px] font-semibold text-gray-600">
        จำนวนนิสิตแต่ละชั้นปี ({groups.length}{groups.length !== total ? ` / ${total}` : ""})
      </div>
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-gray-100">
            <th className="text-left px-5 py-2.5 text-[12px] font-medium text-gray-400">ชั้นปี</th>
            <th className="text-right px-5 py-2.5 text-[12px] font-medium text-gray-400">จำนวนนิสิต</th>
            <th className="text-right px-5 py-2.5 text-[12px] font-medium text-gray-400 w-20">แก้ไข</th>
          </tr>
        </thead>
        <tbody>
          {groups.length === 0 ? (
            <EmptyRow colSpan={3} text="ไม่พบชั้นปีที่ค้นหา" />
          ) : (
            groups.map((g) => (
              <tr key={g.group_id} className="border-b border-gray-50 last:border-0 hover:bg-slate-50/60 transition-colors">
                <td className={`px-5 py-3 text-[13px] font-bold ${majorTextClass(g.major as string)}`}>
                  {groupDisplayName(g)}
                </td>
                <td className={`px-5 py-3 text-[13px] font-bold text-right ${majorTextClass(g.major as string)}`}>
                  {g.total_students.toLocaleString()} คน
                </td>
                <td className="px-5 py-3 text-right">
                  <button
                    onClick={() => onEdit(g)}
                    className="text-gray-300 hover:text-orange-500 transition-colors cursor-pointer"
                    title="แก้ไขชั้นปี"
                  >
                    <Pencil size={15} />
                  </button>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function EditGroupModal({
  group,
  onClose,
  onSaved,
}: {
  group: Group;
  onClose: () => void;
  onSaved: (updated: Group) => void;
}) {
  const [value, setValue] = useState(String(group.total_students));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleSave() {
    const n = Number(value);
    if (!Number.isFinite(n) || n < 0) {
      setError("กรุณากรอกจำนวนที่ถูกต้อง");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE}/groups/${encodeURIComponent(group.group_id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ total_students: n }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "บันทึกไม่สำเร็จ");
      }
      const updated = await res.json();
      onSaved({ ...group, ...updated });
    } catch (e) {
      setError(e instanceof Error ? e.message : "บันทึกไม่สำเร็จ กรุณาลองใหม่");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 bg-black/30 backdrop-blur-[2px] z-50 flex items-center justify-center animate-fade-up p-4"
      onClick={onClose}
    >
      <div className="bg-white rounded-2xl shadow-2xl p-6 w-96" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between mb-4">
          <div>
            <h3 className="text-[15px] font-bold text-gray-900">แก้ไขจำนวนนิสิต</h3>
            <p className="text-xs text-gray-400 mt-0.5">{groupDisplayName(group)}</p>
          </div>
          <button onClick={onClose} className="text-gray-300 hover:text-gray-500 transition-colors cursor-pointer">
            <X size={18} />
          </button>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-red-600 text-xs mb-3">
            {error}
          </div>
        )}

        <label className="block text-xs font-medium text-gray-500 mb-1.5">จำนวนนิสิต</label>
        <input
          type="number"
          min={0}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSave();
          }}
          className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm outline-none bg-white focus:border-orange-300 focus:ring-4 focus:ring-orange-50 transition-all mb-4"
          autoFocus
        />

        <div className="flex gap-2.5">
          <button
            onClick={onClose}
            className="flex-1 py-2.5 rounded-xl border border-gray-200 text-gray-600 text-sm font-semibold hover:bg-gray-50 cursor-pointer transition-colors"
          >
            ยกเลิก
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex-1 py-2.5 rounded-xl bg-orange-500 hover:bg-orange-600 text-white text-sm font-semibold cursor-pointer disabled:bg-orange-200 transition-colors flex items-center justify-center gap-1.5"
          >
            {saving ? <><Loader2 size={14} className="animate-spin" /> กำลังบันทึก...</> : "บันทึก"}
          </button>
        </div>
      </div>
    </div>
  );
}