import { useMutation, useQueryClient } from "@tanstack/react-query";
import { NOTIFICATIONS_QUERY_KEY, useNotifications } from "../../hooks/useNotifications";
import { markAllNotificationsRead, markNotificationRead } from "../../services/notificationsApi";
import type { AppNotification } from "../../types/notification";

const CATEGORY_LABELS: Record<string, { label: string; className: string }> = {
  alert: { label: "هشدار سرور", className: "bg-red-50 text-red-700 ring-red-200" },
  deployment: { label: "استقرار / CI", className: "bg-blue-50 text-blue-700 ring-blue-200" },
};

function formatDateTime(isoDate: string): string {
  return new Date(isoDate).toLocaleString("fa-IR", { dateStyle: "medium", timeStyle: "short" });
}

function NotificationItem({ notification, onMarkRead }: { notification: AppNotification; onMarkRead: () => void }) {
  const category = notification.category ? CATEGORY_LABELS[notification.category] : undefined;

  return (
    <li
      className={`rounded-lg border p-4 transition-colors ${
        notification.is_read ? "border-slate-200 bg-white" : "border-blue-200 bg-blue-50/40"
      }`}
    >
      <div className="mb-1 flex flex-wrap items-center gap-2">
        {!notification.is_read && <span className="h-2 w-2 shrink-0 rounded-full bg-blue-600" aria-label="خوانده‌نشده" />}
        <h3 className="text-sm font-bold text-slate-800">{notification.title}</h3>
        {category && (
          <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ${category.className}`}>
            {category.label}
          </span>
        )}
      </div>

      {notification.content && (
        // متن چندخطی هشدار/گزارش (منبع، زمان شروع، لینک اجرای CI و ...) — جهت LTR
        // برای خطوطی که با متن لاتین شروع می‌شوند با dir="auto" خودکار انتخاب می‌شود
        <p dir="auto" className="whitespace-pre-line break-words text-xs leading-6 text-slate-600">
          {notification.content}
        </p>
      )}

      <div className="mt-2 flex items-center justify-between gap-2">
        <time className="text-[11px] text-slate-400" dateTime={notification.created_at}>
          {formatDateTime(notification.created_at)}
        </time>
        {!notification.is_read && (
          <button onClick={onMarkRead} className="text-xs font-semibold text-blue-600 hover:underline">
            خوانده شد
          </button>
        )}
      </div>
    </li>
  );
}

/**
 * کانال پیام‌رسان داخل سایت تیم فنی: هشدارهای سیستم مانیتورینگ (Alertmanager)
 * و گزارش‌های موفقیت/شکست خط لوله‌ی CI/CD — هر ۱۵ ثانیه خودکار به‌روز می‌شود.
 */
export default function NotificationsPanel() {
  const queryClient = useQueryClient();
  const { data, isLoading, isError } = useNotifications();

  const invalidate = () => queryClient.invalidateQueries({ queryKey: NOTIFICATIONS_QUERY_KEY });
  const markReadMutation = useMutation({ mutationFn: markNotificationRead, onSuccess: invalidate });
  const markAllMutation = useMutation({ mutationFn: markAllNotificationsRead, onSuccess: invalidate });

  const notifications = data?.items ?? [];
  const unreadCount = data?.unread_count ?? 0;

  return (
    <div>
      <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-sm font-bold text-slate-700">اعلان‌های تیم فنی</h2>
          <p className="text-xs text-slate-500">هشدارهای سرور و گزارش‌های استقرار — به‌روزرسانی خودکار</p>
        </div>
        {unreadCount > 0 && (
          <button
            onClick={() => markAllMutation.mutate()}
            disabled={markAllMutation.isPending}
            className="self-start text-xs font-semibold text-blue-600 hover:underline disabled:opacity-50 sm:self-auto"
          >
            علامت‌گذاری همه به‌عنوان خوانده‌شده ({unreadCount.toLocaleString("fa-IR")})
          </button>
        )}
      </div>

      {isLoading && <p className="p-4 text-sm text-slate-500">در حال بارگذاری...</p>}

      {isError && (
        <p className="rounded-lg border border-red-200 bg-red-50 p-6 text-center text-sm text-red-600">
          خطا در دریافت اعلان‌ها. اتصال به سرور را بررسی کن.
        </p>
      )}

      {!isLoading && !isError && notifications.length === 0 && (
        <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
          هیچ اعلانی نیست — همه‌چیز آرام است.
        </p>
      )}

      <ul className="flex flex-col gap-3">
        {notifications.map((notification) => (
          <NotificationItem
            key={notification.id}
            notification={notification}
            onMarkRead={() => markReadMutation.mutate(notification.id)}
          />
        ))}
      </ul>
    </div>
  );
}
