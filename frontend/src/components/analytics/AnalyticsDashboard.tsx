/**
 * تب «داشبورد تحلیلی» — بخش پنل ادمین/HR (Task «پیاده‌سازی داشبوردهای
 * تحلیلی پنج‌گانه»، دو مورد اول: قیف استخدام + روند ثبت درخواست‌ها؛ بقیه‌ی
 * نمودارها در تسک‌های بعدی به همین کامپوننت اضافه می‌شوند).
 *
 * هر دو کارت مستقل از هم بارگذاری/رفرش می‌شوند (دو useQuery جدا) تا کند
 * بودن یکی، دیگری را بلاک نکند.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import ChartSkeleton from "./ChartSkeleton";
import RecruitmentFunnelChart from "./RecruitmentFunnelChart";
import ApplicationsTrendChart from "./ApplicationsTrendChart";
import { fetchApplicationsTrend, fetchRecruitmentFunnel } from "../../services/analyticsApi";

interface AnalyticsDashboardProps {
  /** شناسه‌ی آگهی فعلاً بارگذاری‌شده در بخش موقت بالای داشبورد (اختیاری) */
  jobId?: string;
}

const TREND_DAY_OPTIONS = [7, 30, 90] as const;

function ErrorState({ message }: { message: string }) {
  return (
    <p className="rounded-lg border border-red-200 bg-red-50 p-6 text-center text-sm text-red-600">{message}</p>
  );
}

function RefreshButton({ onClick, isFetching }: { onClick: () => void; isFetching: boolean }) {
  return (
    <button
      onClick={onClick}
      disabled={isFetching}
      className="shrink-0 rounded-md border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-600 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {isFetching ? "در حال به‌روزرسانی..." : "به‌روزرسانی"}
    </button>
  );
}

export default function AnalyticsDashboard({ jobId }: AnalyticsDashboardProps) {
  const [scopeToJob, setScopeToJob] = useState(false);
  const [trendDays, setTrendDays] = useState<number>(30);

  const scopedJobId = scopeToJob && jobId ? jobId : undefined;

  const funnelQuery = useQuery({
    queryKey: ["analytics", "funnel", scopedJobId ?? "all"],
    queryFn: () => fetchRecruitmentFunnel({ jobId: scopedJobId }),
  });

  const trendQuery = useQuery({
    queryKey: ["analytics", "trend", trendDays, scopedJobId ?? "all"],
    queryFn: () => fetchApplicationsTrend({ days: trendDays, jobId: scopedJobId }),
  });

  return (
    <div className="flex flex-col gap-6">
      {jobId && (
        <label className="flex w-fit items-center gap-2 text-xs font-semibold text-slate-600">
          <input
            type="checkbox"
            checked={scopeToJob}
            onChange={(event) => setScopeToJob(event.target.checked)}
            className="h-3.5 w-3.5 rounded border-slate-300"
          />
          فقط برای همین آگهی (Job ID بالای صفحه)
        </label>
      )}

      {/* روی صفحات کوچک زیر هم، از lg به بعد کنار هم — معیار پذیرش واکنش‌گرا بودن */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
          <div className="mb-3 flex items-start justify-between gap-2">
            <div>
              <h2 className="text-sm font-bold text-slate-800">قیف استخدام</h2>
              <p className="text-xs text-slate-500">تعداد کارجویان و نرخ تبدیل در هر مرحله از فرآیند</p>
            </div>
            <RefreshButton onClick={() => void funnelQuery.refetch()} isFetching={funnelQuery.isFetching} />
          </div>

          {funnelQuery.isLoading && <ChartSkeleton heightClass="h-80" />}
          {funnelQuery.isError && <ErrorState message="خطا در دریافت داده‌ی قیف استخدام. توکن دسترسی (Admin/HR_Manager) را بررسی کنید." />}
          {funnelQuery.data && <RecruitmentFunnelChart stages={funnelQuery.data.stages} />}
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
          <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
            <div>
              <h2 className="text-sm font-bold text-slate-800">روند ثبت درخواست‌ها</h2>
              <p className="text-xs text-slate-500">تعداد درخواست‌های ثبت‌شده به تفکیک روز</p>
            </div>
            <div className="flex items-center gap-2">
              <select
                value={trendDays}
                onChange={(event) => setTrendDays(Number(event.target.value))}
                className="rounded-md border border-slate-300 px-2 py-1 text-xs"
              >
                {TREND_DAY_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option} روز اخیر
                  </option>
                ))}
              </select>
              <RefreshButton onClick={() => void trendQuery.refetch()} isFetching={trendQuery.isFetching} />
            </div>
          </div>

          {trendQuery.isLoading && <ChartSkeleton heightClass="h-72" />}
          {trendQuery.isError && <ErrorState message="خطا در دریافت داده‌ی سری زمانی. توکن دسترسی (Admin/HR_Manager) را بررسی کنید." />}
          {trendQuery.data && <ApplicationsTrendChart series={trendQuery.data.series} />}
        </section>
      </div>
    </div>
  );
}
