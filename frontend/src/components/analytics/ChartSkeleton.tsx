/**
 * اسکلتون بارگذاری عمومی برای کارت‌های نموداری داشبورد تحلیلی — طبق معیار
 * پذیرش تسک («در زمان بارگذاری داده از سرور باید اسکلتون یا اسپینر مناسب
 * نمایش داده شود»)، به‌جای یک متن ساده‌ی «در حال بارگذاری...».
 */

interface ChartSkeletonProps {
  /** کلاس ارتفاع Tailwind — باید با ارتفاع واقعی نمودار مطابقت داشته باشد تا از پرش صفحه (Layout Shift) جلوگیری شود */
  heightClass?: string;
}

const BAR_HEIGHTS = [35, 60, 45, 80, 55, 90, 50, 70];

export default function ChartSkeleton({ heightClass = "h-72" }: ChartSkeletonProps) {
  return (
    <div
      role="status"
      aria-label="در حال بارگذاری نمودار"
      className={`${heightClass} w-full animate-pulse rounded-lg bg-slate-50 p-4`}
    >
      <div className="mb-4 h-3 w-1/3 rounded bg-slate-200" />
      <div className="flex h-[calc(100%-1.5rem)] items-end gap-2">
        {BAR_HEIGHTS.map((height, index) => (
          <div key={index} className="flex-1 rounded-t bg-slate-200" style={{ height: `${height}%` }} />
        ))}
      </div>
    </div>
  );
}
