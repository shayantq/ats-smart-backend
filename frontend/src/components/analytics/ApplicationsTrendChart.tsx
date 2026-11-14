/**
 * کامپوننت نمودار خطی روند ثبت درخواست‌ها — مصرف‌کننده‌ی
 * GET /api/v1/analytics/applications-trend.
 *
 * همان توضیح dir="ltr" در RecruitmentFunnelChart.tsx اینجا هم صدق می‌کند
 * (محدودیت شناخته‌شده‌ی Recharts زیر والد RTL).
 */

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DailyApplicationCount } from "../../types/analytics";

interface ApplicationsTrendChartProps {
  series: DailyApplicationCount[];
}

function formatAxisDate(isoDate: string): string {
  return new Date(isoDate).toLocaleDateString("fa-IR", { day: "numeric", month: "short" });
}

function formatTooltipDate(isoDate: string): string {
  return new Date(isoDate).toLocaleDateString("fa-IR", { year: "numeric", month: "long", day: "numeric" });
}

interface TrendTooltipProps {
  active?: boolean;
  payload?: { payload: DailyApplicationCount }[];
}

function TrendTooltip({ active, payload }: TrendTooltipProps) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;

  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-500 bg-white dark:bg-slate-800 px-3 py-2 text-xs ">
      <p className="mb-1 font-semibold text-slate-700 dark:text-slate-200">{formatTooltipDate(point.date)}</p>
      <p className="text-slate-700 dark:text-slate-200">
        تعداد درخواست ثبت‌شده: <span className="font-bold">{point.count}</span>
      </p>
    </div>
  );
}

export default function ApplicationsTrendChart({ series }: ApplicationsTrendChartProps) {
  const isEmpty = series.every((point) => point.count === 0);

  if (isEmpty) {
    return (
      <p className="rounded-lg border border-dashed border-slate-500 dark:border-slate-500 p-6 text-center text-sm text-slate-600 dark:text-slate-300">
        در این بازه‌ی زمانی هیچ درخواستی ثبت نشده است.
      </p>
    );
  }

  return (
    <div dir="ltr" className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={series} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
          <XAxis
            dataKey="date"
            tickFormatter={formatAxisDate}
            tick={{ fontSize: 11, fill: "var(--chart-text)" }}
            minTickGap={24}
          />
          <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "var(--chart-text)" }} width={28} />
          <Tooltip content={<TrendTooltip />} />
          <Line
            isAnimationActive={false}
            type="monotone"
            dataKey="count"
            stroke="var(--chart-line)"
            strokeWidth={2}
            dot={{ r: 3, fill: "var(--chart-line)" }}
            activeDot={{ r: 5 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
