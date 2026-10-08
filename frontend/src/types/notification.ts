/**
 * دسته‌های اعلان — منطبق بر بک‌اند (app/routers/ops.py):
 * "alert" = هشدار سیستم مانیتورینگ، "deployment" = گزارش خط لوله‌ی CI/CD
 */
export type NotificationCategory = "alert" | "deployment" | string;

/** ساختار یک اعلان — خروجی GET /api/v1/notifications/me */
export interface AppNotification {
  id: string;
  title: string;
  content: string | null;
  category: NotificationCategory | null;
  is_read: boolean;
  created_at: string;
}

export interface NotificationListResponse {
  items: AppNotification[];
  unread_count: number;
  next_cursor: string | null;
  previous_cursor: string | null;
  has_next: boolean;
  has_previous: boolean;
}
