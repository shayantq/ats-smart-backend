import { useState } from "react";
import KanbanBoard from "../components/KanbanBoard";
import { getToken, setToken as saveToken } from "../services/tokenStorage";

export default function HRDashboard() {
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
          بورد کانبان فرآیند استخدام — کارت کارجو را بین ستون‌ها بکشید تا وضعیتش تغییر کند.
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

        <KanbanBoard jobId={activeJobId} />
      </div>
    </div>
  );
}
