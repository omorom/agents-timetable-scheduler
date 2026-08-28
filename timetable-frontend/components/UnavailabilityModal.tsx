"use client";

import { X } from "lucide-react";
import UnavailabilityGrid from "./UnavailabilityGrid";

interface Props {
  kind: "teacher" | "room";
  entityId: string;
  title: string;
  subtitle?: string;
  onClose: () => void;
}

export default function UnavailabilityModal({ kind, entityId, title, subtitle, onClose }: Props) {
  return (
    <div
      className="fixed inset-0 bg-black/30 backdrop-blur-[2px] z-50 flex items-center justify-center animate-fade-up p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-2xl w-full max-w-6xl max-h-[92vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between px-7 py-6 border-b border-gray-100 sticky top-0 bg-white z-10">
          <div>
            <h3 className="text-[18px] font-bold text-gray-900">{title}</h3>
            {subtitle && <p className="text-sm text-gray-400 mt-1">{subtitle}</p>}
          </div>
          <button
            onClick={onClose}
            className="text-gray-300 hover:text-gray-500 transition-colors cursor-pointer shrink-0"
          >
            <X size={22} />
          </button>
        </div>

        <div className="p-7">
          <UnavailabilityGrid kind={kind} entityId={entityId} />
        </div>
      </div>
    </div>
  );
}