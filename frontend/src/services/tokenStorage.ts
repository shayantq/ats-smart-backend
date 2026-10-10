/**
 * نگه‌داری access_token کاربر لاگین‌شده در localStorage (بنگرید pages/LoginPage.tsx).
 * عمر توکن کوتاه است (پیش‌فرض ۱۵ دقیقه)؛ بعد از انقضا، اولین درخواست با 401 رد می‌شود و
 * کاربر خودکار به صفحه‌ی ورود برمی‌گردد (بنگرید UNAUTHORIZED_EVENT در apiClient.ts).
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
