/**
 * کلاینت سبک برای صحبت با بک‌اند (بدون وابستگی به axios یا کتابخانه‌ی جانبی).
 * توکن دسترسی را از localStorage می‌خواند (بنگرید tokenStorage.ts).
 */

import { getToken } from "./tokenStorage";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

/** خطای سرور را با کد وضعیت HTTP همراه نگه می‌دارد تا فراخوان بتواند 400 را از بقیه تشخیص دهد */
export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

interface ApiRequestOptions extends RequestInit {
  /** آیا هدر Authorization اضافه شود؟ پیش‌فرض: بله */
  auth?: boolean;
}

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const { auth = true, headers, ...rest } = options;

  const finalHeaders: Record<string, string> = {
    "Content-Type": "application/json",
    ...(headers as Record<string, string> | undefined),
  };

  if (auth) {
    const token = getToken();
    if (token) {
      finalHeaders["Authorization"] = `Bearer ${token}`;
    }
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...rest,
    headers: finalHeaders,
  });

  if (!response.ok) {
    let detail = `خطای سرور (کد ${response.status})`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) {
        detail = body.detail;
      }
    } catch {
      // بدنه‌ی پاسخ JSON نبود؛ از پیام پیش‌فرض بالا استفاده می‌شود
    }
    throw new ApiError(detail, response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}
