/**
 * فراخوانی اندپوینت‌های صندوق اعلان‌های داخل سایت:
 * - GET /api/v1/notifications/me              جدیدترین اعلان‌ها + تعداد خوانده‌نشده‌ها
 * - PUT /api/v1/notifications/{id}/read       علامت‌گذاری یک اعلان
 * - PUT /api/v1/notifications/read-all        علامت‌گذاری همه
 */

import { apiRequest } from "./apiClient";
import type { AppNotification, NotificationListResponse } from "../types/notification";

/** فقط صفحه‌ی اول (جدیدترین‌ها) — صندوق اعلان نیازی به بارگذاری کل تاریخچه ندارد */
const NOTIFICATIONS_PAGE_SIZE = 50;

export async function fetchMyNotifications(): Promise<NotificationListResponse> {
  return apiRequest<NotificationListResponse>(`/notifications/me?limit=${NOTIFICATIONS_PAGE_SIZE}`);
}

export async function markNotificationRead(notificationId: string): Promise<AppNotification> {
  return apiRequest<AppNotification>(`/notifications/${notificationId}/read`, { method: "PUT" });
}

export async function markAllNotificationsRead(): Promise<{ updated_count: number }> {
  return apiRequest<{ updated_count: number }>("/notifications/read-all", { method: "PUT" });
}
