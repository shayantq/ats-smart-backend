import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import KanbanBoard from "../components/KanbanBoard";
import TodayInterviewsPanel from "../components/interview/TodayInterviewsPanel";
const AnalyticsDashboard = lazy(() => import("../components/analytics/AnalyticsDashboard"));
import NotificationsPanel from "../components/notifications/NotificationsPanel";
import JobCreateForm from "../components/jobs/JobCreateForm";
import { useNotifications } from "../hooks/useNotifications";
import { useToast } from "../context/ToastContext";
import { fetchActiveJobs } from "../services/jobsApi";
import { useAppSelector } from "../store/hooks";
import type { Job } from "../types/job";

type HRTab = "kanban" | "new_job" | "interviews" | "analytics" | "notifications";

// ثبت آگهی فقط برای نقش‌های مدیریت آگهی (همان JOB_MANAGER_ROLES بک‌اند)؛ مصاحبه‌کننده این تب را نمی‌بیند
const JOB_MANAGER_ROLES = ["Admin", "HR_Manager"];

const TABS: { value: HRTab; label: string; managersOnly?: boolean }[] = [
  { value: "kanban", label: "بورد کانبان" },
  { value: "new_job", label: "ثبت آگهی", managersOnly: true },
  { value: "interviews", label: "مصاحبه‌های امروز" },
  { value: "analytics", label: "داشبورد تحلیلی" },
  { value: "notifications", label: "اعلان‌های فنی" },
];

export default function HRDashboard() {
  const [activeTab, setActiveTab] = useState<HRTab>("kanban");
  const [activeJobId, setActiveJobId] = useState("");
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const role = useAppSelector((state) => state.auth.user?.role);
  const canManageJobs = role !== undefined && JOB_MANAGER_ROLES.includes(role);
  const visibleTabs = TABS.filter((tab) => !tab.managersOnly || canManageJobs);

  function handleJobCreated(job: Job) {
    queryClient.invalidateQueries({ queryKey: ["jobs", "active"] });
    setActiveJobId(job.job_id);
    setActiveTab("kanban");
  }

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
    <div className="min-h-screen bg-paper">
      <div className="editorial-shell">
        <p className="editorial-label mb-2">فضای کار استخدام / منابع انسانی</p>
        <h1 className="mb-2 text-heading sm:text-display">
          داشبورد کارشناس منابع انسانی
        </h1>
        <p className="mb-8 max-w-prose text-body text-muted">
          بورد کانبان فرآیند استخدام، و دسترسی سریع به فرم‌های ارزیابی مصاحبه‌های امروز.
        </p>

        <div className="mb-8 flex min-w-0 flex-col gap-2 sm:max-w-lg">
          <label htmlFor="job-select" className="text-xs font-semibold text-slate-600 dark:text-slate-300">
            آگهی شغلی
          </label>
          <select
            id="job-select"
            value={activeJobId}
            onChange={(event) => setActiveJobId(event.target.value)}
            disabled={isLoadingJobs || jobs.length === 0}
            className="w-full min-w-0 rounded border border-slate-500 bg-white dark:bg-slate-800 px-3 py-2 text-body"
          >
            {isLoadingJobs && <option value="">در حال بارگذاری آگهی‌ها...</option>}
            {!isLoadingJobs && jobs.length === 0 && <option value="">هنوز هیچ آگهی فعالی ثبت نشده</option>}
            {jobs.map((job) => (
              <option key={job.job_id} value={job.job_id}>
                {job.title}
              </option>
            ))}
          </select>
          {!isLoadingJobs && jobs.length === 0 && canManageJobs && activeTab !== "new_job" && (
            <button
              onClick={() => setActiveTab("new_job")}
              className="mt-1 self-start text-xs font-semibold text-blue-600 dark:text-blue-300 hover:underline"
            >
              ثبت اولین آگهی
            </button>
          )}
        </div>

        <div role="tablist" aria-label="بخش‌های داشبورد" className="mb-6 flex max-w-full gap-1 overflow-x-auto border-b border-rule"
          onKeyDown={(event) => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
            event.preventDefault();
            const current = visibleTabs.findIndex((tab) => tab.value === activeTab);
            const next = event.key === "Home" ? 0 : event.key === "End" ? visibleTabs.length - 1
              : (current + (event.key === "ArrowLeft" ? 1 : -1) + visibleTabs.length) % visibleTabs.length;
            setActiveTab(visibleTabs[next].value);
            event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus();
          }}>
          {visibleTabs.map((tab) => (
            <button
              key={tab.value}
              role="tab"
              id={`hr-tab-${tab.value}`}
              aria-controls={`hr-panel-${tab.value}`}
              tabIndex={activeTab === tab.value ? 0 : -1}
              aria-selected={activeTab === tab.value}
              onClick={() => setActiveTab(tab.value)}
              className={`shrink-0 border-b-2 px-4 py-3 text-sm font-medium leading-7 transition-colors ${
                activeTab === tab.value
                  ? "border-slate-700 dark:border-slate-500 text-ink"
                  : "border-transparent text-muted hover:bg-wash hover:text-ink"
              }`}
            >
              {tab.label}
              {tab.value === "notifications" && unreadCount > 0 && (
                <span className="ms-1.5 rounded-full bg-red-600 dark:bg-red-700 px-1.5 py-0.5 text-[10px] font-bold text-white dark:text-slate-100">
                  {unreadCount.toLocaleString("fa-IR")}
                </span>
              )}
            </button>
          ))}
        </div>

        <section role="tabpanel" id={`hr-panel-${activeTab}`} aria-labelledby={`hr-tab-${activeTab}`} tabIndex={0}>
        {activeTab === "kanban" && <KanbanBoard jobId={activeJobId} />}
        {activeTab === "new_job" && canManageJobs && <JobCreateForm onCreated={handleJobCreated} />}
        {activeTab === "interviews" && <TodayInterviewsPanel />}
        {activeTab === "analytics" && <Suspense fallback={<p role="status">در حال بارگذاری داشبورد…</p>}><AnalyticsDashboard jobId={activeJobId} /></Suspense>}
        {activeTab === "notifications" && <NotificationsPanel />}
        </section>
      </div>
    </div>
  );
}
