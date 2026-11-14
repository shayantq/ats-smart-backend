import { PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, ResponsiveContainer } from "recharts";

export default function CandidateRadar({ metrics }: {metrics:{label:string;score:number}[]}) {
  return <figure className="mt-5 min-w-0">
    <div aria-hidden="true" dir="ltr" className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <RadarChart data={metrics} outerRadius="58%">
          <PolarGrid stroke="#dce1e6" />
          <PolarAngleAxis dataKey="label" tick={{fontSize:11,fill:"#475569"}} />
          <PolarRadiusAxis domain={[0,100]} tick={false} axisLine={false} />
          <Radar dataKey="score" stroke="#475569" fill="#64748b" fillOpacity={0.2} isAnimationActive={false} />
        </RadarChart>
      </ResponsiveContainer>
    </div>
    <figcaption className="text-caption text-muted">سیگنال‌های مهارت نرم؛ امتیازهای ۰ تا ۱ ذخیره‌شده در مقیاس درصد نمایش داده می‌شوند. این تحلیل واژه‌نامه‌ای، سنجش روان‌شناختی یا تصمیم استخدام نیست.</figcaption>
    <ul className="mt-3 text-caption">{metrics.map(v=><li key={v.label}>{v.label}: {v.score.toLocaleString("fa-IR",{maximumFractionDigits:1})} از ۱۰۰</li>)}</ul>
  </figure>;
}
