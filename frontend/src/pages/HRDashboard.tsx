import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import KanbanBoard from "../components/KanbanBoard";
import TodayInterviewsPanel from "../components/interview/TodayInterviewsPanel";
import AnalyticsDashboard from "../components/analytics/AnalyticsDashboard";
import NotificationsPanel from "../components/notifications/NotificationsPanel";
import { useNotifications } from "../hooks/useNotifications";
import { useToast } from "../context/ToastContext";
import { fetchActiveJobs } from "../services/jobsApi";

type HRTab = "kanban" | "interviews" | "analytics" | "notifications";

const TABS: { value: HRTab; label: string }[] = [
  { value: "kanban", label: "بورد کانبان" },
  { value: "interviews", label: "مصاحبه‌های امروز" },
  { value: "analytics", label: "داشبورد تحلیلی" },
  { value: "notifications", label: "اعلان‌های فنی" },
];

export default function HRDashboard() {
  const [activeTab, setActiveTab] = useState<HRTab>("kanban");
  const [activeJobId, setActiveJobId] = useState("");
  const { showToast } = useToast();

  // آگهی‌های فعال برای منوی انتخاب آگهی؛ اولین آگهی به‌صورت پیش‌فرض انتخاب می‌شود
  const { data: jobs = [], isLoading: isLoadingJobs } = useQuery({ queryKey: ["jobs", "active"], queryFn: fetchActiveJobs });
  useEffect(() => {
    if (!activeJobId && jobs.length > 0) {
      setActiveJobId(jobs[0].job_id);
    }
  }, [jobs, activeJobId]);

  // تعداد اعلان‌های خوانده‌نشده برای نشان (Badge) روی تب + Toast فوری برای اعلان جدید،
  // حتی وقتی کاربر روی تب دیگری است
  const { data: notificationsData } = useNotifications();
  const unreadCount = notificationsData?.unread_count ?? 0;
  const previousUnreadCount = useRef<number | null>(null);

  useEffect(() => {
    if (notificationsData === undefined) return;
    if (previousUnreadCount.current !== null && unreadCount > previousUnreadCount.current) {
      const newest = notificationsData.items.find((item) => !item.is_read);
      showToast(newest ? newest.title : "اعلان جدید سیستم", newest?.category === "alert" ? "error" : "success");
    }
    previousUnreadCount.current = unreadCount;
  }, [notificationsData, unreadCount, showToast]);

  return (
    <div className="min-h-screen bg-slate-100 p-4 sm:p-6">
      <div className="mx-auto max-w-7xl">
        <h1 className="mb-1 text-xl font-bold text-slate-800 sm:text-2xl">
          داشبورد کارشناس منابع انسانی
        </h1>
        <p className="mb-6 text-sm text-slate-500">
          بورد کانبان فرآیند استخدام، و دسترسی سریع به فرم‌های ارزیابی مصاحبه‌های امروز.
        </p>

        <div className="mb-6 flex flex-col gap-1 sm:max-w-md">
          <label htmlFor="job-select" className="text-xs font-semibold text-slate-600">
            آگهی شغلی
          </label>
          <select
            id="job-select"
            value={activeJobId}
            onChange={(event) => setActiveJobId(event.target.value)}
            disabled={isLoadingJobs || jobs.length === 0}
            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
          >
            {isLoadingJobs && <option value="">در حال بارگذاری آگهی‌ها...</option>}
            {!isLoadingJobs && jobs.length === 0 && <option value="">هنوز هیچ آگهی فعالی ثبت نشده</option>}
            {jobs.map((job) => (
              <option key={job.job_id} value={job.job_id}>
                {job.title}
              </option>
            ))}
          </select>
        </div>

        <div role="tablist" className="mb-4 flex gap-1 overflow-x-auto border-b border-slate-200">
          {TABS.map((tab) => (
            <button
              key={tab.value}
              role="tab"
              aria-selected={activeTab === tab.value}
              onClick={() => setActiveTab(tab.value)}
              className={`shrink-0 rounded-t-lg px-4 py-2 text-sm font-semibold transition-colors ${
                activeTab === tab.value
                  ? "border-b-2 border-blue-600 text-blue-700"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              {tab.label}
              {tab.value === "notifications" && unreadCount > 0 && (
                <span className="ms-1.5 rounded-full bg-red-600 px-1.5 py-0.5 text-[10px] font-bold text-white">
                  {unreadCount.toLocaleString("fa-IR")}
                </span>
              )}
            </button>
          ))}
        </div>

        {activeTab === "kanban" && <KanbanBoard jobId={activeJobId} />}
        {activeTab === "interviews" && <TodayInterviewsPanel />}
        {activeTab === "analytics" && <AnalyticsDashboard jobId={activeJobId} />}
        {activeTab === "notifications" && <NotificationsPanel />}
      </div>
    </div>
  );
}
