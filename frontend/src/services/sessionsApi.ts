/**
 * نشست‌های فعال کاربر (دستگاه‌هایی که با این حساب وارد شده‌اند):
 * - GET    /api/v1/auth/sessions/        فهرست نشست‌ها، جدیدترین فعالیت اول
 * - DELETE /api/v1/auth/sessions/{id}/   خروج از یک دستگاه (ابطال فوری نشست و Refresh Token آن)
 * - POST   /api/v1/auth/logout           خروج از همین دستگاه
 */

import { apiRequest } from "./apiClient";
import type { SessionListResponse } from "../types/session";

export const SESSIONS_QUERY_KEY = ["auth", "sessions"];

export async function fetchMySessions(): Promise<SessionListResponse> {
  return apiRequest<SessionListResponse>("/auth/sessions/");
}

export async function revokeSession(sessionId: string): Promise<void> {
  return apiRequest<void>(`/auth/sessions/${sessionId}/`, { method: "DELETE" });
}

export async function logoutCurrentSession(): Promise<void> {
  return apiRequest<void>("/auth/logout", { method: "POST" });
}
