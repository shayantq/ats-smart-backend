/**
 * ذخیره‌ی موقت access_token در localStorage.
 *
 * ⚠️ این یک راه‌حل موقت است تا زمانی که صفحه‌ی ورود (Login) واقعی در فرانت‌اند
 * ساخته شود. فعلاً کارشناس HR باید access_token را از Swagger بک‌اند کپی و در
 * فرم بالای داشبورد وارد کند (بنگرید HRDashboard.tsx).
 */

const TOKEN_STORAGE_KEY = "ats_smart_access_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY);
}
