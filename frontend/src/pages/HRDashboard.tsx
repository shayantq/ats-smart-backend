import { useState } from "react";
import KanbanBoard from "../components/KanbanBoard";
import TodayInterviewsPanel from "../components/interview/TodayInterviewsPanel";
import { getToken, setToken as saveToken } from "../services/tokenStorage";

type HRTab = "kanban" | "interviews";

const TABS: { value: HRTab; label: string }[] = [
  { value: "kanban", label: "بورد کانبان" },
  { value: "interviews", label: "مصاحبه‌های امروز" },
];

export default function HRDashboard() {
  const [activeTab, setActiveTab] = useState<HRTab>("kanban");
  const [jobIdInput, setJobIdInput] = useState("");
  const [activeJobId, setActiveJobId] = useState("");
  const [tokenInput, setTokenInput] = useState(getToken() ?? "");

  function handleLoadBoard() {
    saveToken(tokenInput.trim());
    setActiveJobId(jobIdInput.trim());
  }

  return (
    <div className="min-h-screen bg-slate-100 p-4 sm:p-6">
      <div className="mx-auto max-w-7xl">
        <h1 className="mb-1 text-xl font-bold text-slate-800 sm:text-2xl">
          داشبورد کارشناس منابع انسانی
        </h1>
        <p className="mb-6 text-sm text-slate-500">
          بورد کانبان فرآیند استخدام، و دسترسی سریع به فرم‌های ارزیابی مصاحبه‌های امروز.
        </p>

        {/* بخش موقت توسعه: تا زمانی که صفحه‌ی ورود (Login) و انتخاب آگهی ساخته شود */}
        <div className="mb-6 flex flex-col gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 sm:flex-row sm:items-end">
          <div className="flex-1">
            <label className="mb-1 block text-xs font-semibold text-amber-800">
              شناسه‌ی آگهی (Job ID)
            </label>
            <input
              type="text"
              value={jobIdInput}
              onChange={(event) => setJobIdInput(event.target.value)}
              placeholder="job_id را از Swagger کپی کنید"
              className="w-full rounded-md border border-amber-300 px-3 py-1.5 text-xs"
            />
          </div>
          <div className="flex-1">
            <label className="mb-1 block text-xs font-semibold text-amber-800">
              توکن دسترسی (HR / Admin)
            </label>
            <input
              type="text"
              value={tokenInput}
              onChange={(event) => setTokenInput(event.target.value)}
              placeholder="access_token را از Swagger کپی کنید"
              className="w-full rounded-md border border-amber-300 px-3 py-1.5 text-xs"
            />
          </div>
          <button
            onClick={handleLoadBoard}
            className="shrink-0 rounded-md bg-amber-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-amber-700"
          >
            بارگذاری بورد
          </button>
        </div>

        <div className="mb-4 flex gap-1 overflow-x-auto border-b border-slate-200">
          {TABS.map((tab) => (
            <button
              key={tab.value}
              onClick={() => setActiveTab(tab.value)}
              className={`shrink-0 rounded-t-lg px-4 py-2 text-sm font-semibold transition-colors ${
                activeTab === tab.value
                  ? "border-b-2 border-blue-600 text-blue-700"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {activeTab === "kanban" && <KanbanBoard jobId={activeJobId} />}
        {activeTab === "interviews" && <TodayInterviewsPanel />}
      </div>
    </div>
  );
}
