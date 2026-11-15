import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId } from "react";
import { useToast } from "../../context/ToastContext";
import { SESSIONS_QUERY_KEY, fetchMySessions, revokeSession } from "../../services/sessionsApi";
import type { UserSession } from "../../types/session";

const DEVICE_LABELS: Record<string, string> = {
  desktop: "رایانه",
  mobile: "تلفن همراه",
  tablet: "تبلت",
  bot: "ربات",
  other: "دستگاه نامشخص",
};

function formatDateTime(isoDate: string): string {
  return new Date(isoDate).toLocaleString("fa-IR", { dateStyle: "medium", timeStyle: "short" });
}

function formatLocation(session: UserSession): string {
  if (!session.location) return "موقعیت نامشخص";
  return [session.location.city, session.location.country].filter(Boolean).join("، ");
}

function SessionRow({ session, onRevoke, isRevoking }: { session: UserSession; onRevoke: () => void; isRevoking: boolean }) {
  const deviceDescription = useId();
  const browser = [session.browser, session.browser_version].filter(Boolean).join(" ");
  const os = [session.os, session.os_version].filter(Boolean).join(" ");

  return (
    <li
      className={`rounded-lg border p-4 ${
        session.suspicious ? "border-red-200 dark:border-red-400 bg-red-50/40 dark:bg-red-950/40" : session.is_current ? "border-blue-200 dark:border-blue-400 bg-blue-50/40 dark:bg-blue-950/40" : "border-slate-200 dark:border-slate-500 bg-white dark:bg-slate-800"
      }`}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <h3 id={deviceDescription} dir="ltr" className="text-sm font-bold text-slate-800 dark:text-slate-200">
              {browser} · {os}
            </h3>
            <span className="rounded-full bg-slate-100 dark:bg-slate-900 px-2 py-0.5 text-[11px] font-semibold text-slate-600 dark:text-slate-300">
              {DEVICE_LABELS[session.device_type] ?? session.device_type}
              {session.device ? ` (${session.device})` : ""}
            </span>
            {session.is_current && (
              <span className="rounded-full bg-blue-100 dark:bg-blue-950 px-2 py-0.5 text-[11px] font-semibold text-blue-700 dark:text-blue-300">همین دستگاه</span>
            )}
            {session.suspicious && (
              <span className="rounded-full bg-red-100 dark:bg-red-950 px-2 py-0.5 text-[11px] font-semibold text-red-700 dark:text-red-300">ورود مشکوک</span>
            )}
          </div>
          <p className="text-xs leading-6 text-slate-600 dark:text-slate-300">
            <span dir="ltr">{session.ip}</span> · {formatLocation(session)}
          </p>
          <p className="text-[11px] leading-5 text-slate-600 dark:text-slate-300">
            آخرین فعالیت: <time dateTime={session.last_active_at}>{formatDateTime(session.last_active_at)}</time>
            {" · "}
            ورود: <time dateTime={session.created_at}>{formatDateTime(session.created_at)}</time>
          </p>
        </div>
        {!session.is_current && (
          <button
            onClick={onRevoke}
            aria-describedby={deviceDescription}
            disabled={isRevoking}
            className="shrink-0 rounded-md border border-red-300 dark:border-red-400 px-3 py-1 text-xs font-semibold text-red-600 dark:text-red-300 hover:bg-red-50 dark:hover:bg-red-950 disabled:opacity-50"
          >
            خروج از این دستگاه
          </button>
        )}
      </div>
    </li>
  );
}

/**
 * نشست‌های فعال حساب (مقابله با ربوده شدن حساب): هر دستگاهی که با این حساب وارد شده، با مرورگر،
 * سیستم‌عامل، IP، موقعیت تقریبی و آخرین فعالیت. «خروج از این دستگاه» نشست را فوراً باطل می‌کند؛ آن دستگاه
 * در اولین درخواست یا نوسازی توکن به صفحه‌ی ورود برمی‌گردد.
 */
export default function ActiveSessionsPanel() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { data, isLoading, isError } = useQuery({ queryKey: SESSIONS_QUERY_KEY, queryFn: fetchMySessions });

  const revokeMutation = useMutation({
    mutationFn: revokeSession,
    onSuccess: () => {
      showToast("نشست آن دستگاه بسته شد.");
      queryClient.invalidateQueries({ queryKey: SESSIONS_QUERY_KEY });
    },
    onError: () => showToast("بستن نشست ناموفق بود.", "error"),
  });

  const sessions = data?.items ?? [];

  return (
    <section className="mx-auto max-w-3xl px-4 py-6 sm:px-6">
      <div className="mb-4">
        <h2 className="text-sm font-bold text-slate-700 dark:text-slate-200">نشست‌های فعال</h2>
        <p className="text-xs text-slate-600 dark:text-slate-300">دستگاه‌هایی که الان با حساب شما وارد شده‌اند. اگر دستگاهی را نمی‌شناسید، از آن خارج شوید و رمز عبورتان را عوض کنید.</p>
      </div>

      {isLoading && <p className="text-sm text-slate-600 dark:text-slate-300">در حال بارگذاری...</p>}
      {isError && <p className="text-sm text-red-600 dark:text-red-300">دریافت فهرست نشست‌ها ناموفق بود.</p>}

      <ul className="flex flex-col gap-3">
        {sessions.map((session) => (
          <SessionRow
            key={session.id}
            session={session}
            onRevoke={() => revokeMutation.mutate(session.id)}
            isRevoking={revokeMutation.isPending && revokeMutation.variables === session.id}
          />
        ))}
      </ul>
    </section>
  );
}
