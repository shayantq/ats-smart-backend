import { useQuery } from "@tanstack/react-query";
import { fetchMyNotifications } from "../services/notificationsApi";

export const NOTIFICATIONS_QUERY_KEY = ["notifications", "me"];

/** فاصله‌ی بررسی اعلان‌های جدید — هشدارهای سرور تقریباً آنی در سایت دیده شوند */
const POLL_INTERVAL_MS = 15_000;

/**
 * صندوق اعلان‌های کاربر لاگین‌شده با به‌روزرسانی خودکار دوره‌ای.
 * هم نشان (Badge) تب و هم خودِ پنل اعلان‌ها از همین کوئری مشترک استفاده می‌کنند
 * (React Query درخواست‌های هم‌کلید را یکی می‌کند).
 */
export function useNotifications(enabled = true) {
  return useQuery({
    queryKey: NOTIFICATIONS_QUERY_KEY,
    queryFn: fetchMyNotifications,
    enabled,
    refetchInterval: POLL_INTERVAL_MS,
    refetchIntervalInBackground: true,
    retry: false,
  });
}
