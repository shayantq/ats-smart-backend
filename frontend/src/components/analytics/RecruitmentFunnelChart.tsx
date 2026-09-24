/**
 * کامپوننت نمودار قیف استخدام — مصرف‌کننده‌ی GET /api/v1/analytics/funnel.
 *
 * ⚠️ تصمیم مهندسی مستند — dir="ltr" روی ظرف نمودار: کتابخانه‌ی Recharts
 * رسماً از چیدمان RTL پشتیبانی نمی‌کند؛ محاسبه‌ی مختصات Tooltip و Hit-Testing
 * ماوس روی سگمنت‌های قیف زیر یک والد RTL (صفحه‌ی این پروژه dir="rtl" است)
 * به‌درستی کار نمی‌کند. برای همین، فقط همین ظرف SVG با dir="ltr" مجزا شده تا
 * تعامل موس/Tooltip درست باشد؛ خودِ متن‌های فارسی داخل Tooltip/برچسب‌ها بدون
 * مشکل و طبق جهت طبیعی‌شان رندر می‌شوند (جهت نوشتار به‌ازای هر عنصر متنی
 * جداگانه توسط الگوریتم Bidi مرورگر تعیین می‌شود، نه توسط dir ظرف بیرونی).
 */

import { Cell, Funnel, FunnelChart, LabelList, ResponsiveContainer, Tooltip } from "recharts";
import { STATUS_COLUMNS } from "../../types/application";
import type { FunnelStageCount } from "../../types/analytics";

interface RecruitmentFunnelChartProps {
  stages: FunnelStageCount[];
}

interface FunnelDatum {
  stage: string;
  name: string;
  value: number;
  conversionFromPrevious: number | null;
  conversionFromFirst: number | null;
}

// از تیره به روشن — همان رنگ آبی اصلی پروژه (blue-700 بورد کانبان)، هرچه مرحله جلوتر روشن‌تر
const FUNNEL_COLORS = ["#1d4ed8", "#2563eb", "#3b82f6", "#60a5fa", "#93c5fd", "#bfdbfe", "#dbeafe"];

function stageLabel(stage: string): string {
  return STATUS_COLUMNS.find((column) => column.value === stage)?.label ?? stage;
}

function roundToOneDecimal(value: number): number {
  return Math.round(value * 10) / 10;
}

function buildFunnelData(stages: FunnelStageCount[]): FunnelDatum[] {
  const firstCount = stages[0]?.count ?? 0;

  return stages.map((entry, index) => {
    const previousCount = index > 0 ? stages[index - 1].count : null;

    return {
      stage: entry.stage,
      name: stageLabel(entry.stage),
      value: entry.count,
      conversionFromPrevious:
        index === 0 ? 100 : previousCount && previousCount > 0 ? roundToOneDecimal((entry.count / previousCount) * 100) : null,
      conversionFromFirst: firstCount > 0 ? roundToOneDecimal((entry.count / firstCount) * 100) : null,
    };
  });
}

interface FunnelTooltipProps {
  active?: boolean;
  payload?: { payload: FunnelDatum }[];
}

function FunnelTooltip({ active, payload }: FunnelTooltipProps) {
  if (!active || !payload?.length) return null;
  const datum = payload[0].payload;

  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg">
      <p className="mb-1 font-semibold text-slate-700">{datum.name}</p>
      <p className="text-slate-600">
        تعداد کارجو: <span className="font-bold text-slate-900">{datum.value}</span>
      </p>
      {datum.conversionFromPrevious !== null && (
        <p className="text-slate-600">
          نرخ تبدیل از مرحله‌ی قبل: <span className="font-bold text-slate-900">٪{datum.conversionFromPrevious}</span>
        </p>
      )}
      {datum.conversionFromFirst !== null && (
        <p className="text-slate-600">
          نرخ تبدیل از ابتدای قیف: <span className="font-bold text-slate-900">٪{datum.conversionFromFirst}</span>
        </p>
      )}
    </div>
  );
}

export default function RecruitmentFunnelChart({ stages }: RecruitmentFunnelChartProps) {
  const data = buildFunnelData(stages);
  const isEmpty = data.every((entry) => entry.value === 0);

  if (isEmpty) {
    return (
      <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
        هنوز هیچ درخواستی برای نمایش در قیف استخدام ثبت نشده است.
      </p>
    );
  }

  return (
    <div dir="ltr" className="h-80 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <FunnelChart>
          <Tooltip content={<FunnelTooltip />} />
          <Funnel dataKey="value" data={data} isAnimationActive nameKey="name">
            {data.map((entry, index) => (
              <Cell key={entry.stage} fill={FUNNEL_COLORS[index % FUNNEL_COLORS.length]} />
            ))}
            <LabelList dataKey="name" position="right" fill="#334155" stroke="none" fontSize={12} />
            <LabelList dataKey="value" position="center" fill="#ffffff" stroke="none" fontSize={13} fontWeight={700} />
          </Funnel>
        </FunnelChart>
      </ResponsiveContainer>
    </div>
  );
}
