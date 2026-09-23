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

async function parseResponse<T>(response: Response): Promise<T> {
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

  return parseResponse<T>(response);
}

/**
 * ساختار عمومی پاسخ اندپوینت‌های GET List بک‌اند بعد از مهاجرت به
 * Cursor Pagination (بنگرید app/core/pagination.py). دیگر `total` وجود
 * ندارد — چون محاسبه‌ی COUNT(*) دقیق روی جدول‌های حجیم دقیقاً همان مشکل
 * کارایی‌ای است که این معماری قرار است حذفش کند.
 */
export interface CursorPageResponse<T> {
  items: T[];
  next_cursor: string | null;
  previous_cursor: string | null;
  has_next: boolean;
  has_previous: boolean;
}

/** باید با app.core.pagination.MAX_PAGE_SIZE بک‌اند یکی باشد. */
const MAX_PAGE_SIZE = 100;

/**
 * تمام صفحات یک اندپوینت Cursor-Paginated بک‌اند را پشت‌سرهم می‌خواند و
 * به‌صورت یک آرایه‌ی واحد برمی‌گرداند.
 *
 * چرا؟ بخش زیادی از UI فعلی (بورد کانبان، رهگیر وضعیت، صندوق پیشنهادها،
 * پنل مصاحبه‌های امروز) طوری نوشته شده که انتظار دارد کل لیست یک‌جا برگردد
 * (بدون دکمه‌ی «بیشتر»/اسکرول بی‌نهایت). این تابع همان رفتار را برای
 * کامپوننت‌ها حفظ می‌کند، درحالی‌که هر درخواست واقعی به بک‌اند همچنان
 * صفحه‌بندی‌شده و بهینه است — نه یک SELECT بدون سقف روی جدول‌های حجیم.
 *
 * برای لیست‌های واقعاً بزرگ (مثل هزاران رزومه)، گام بعدی طبیعی این است که
 * UI به Infinite Scroll/دکمه‌ی «بیشتر» با useInfiniteQuery مهاجرت کند و
 * این حلقه‌ی خودکار حذف شود؛ فعلاً برای هم‌خوانی کامل با رفتار فعلی UI
 * نگه داشته شده است.
 */
export async function fetchAllCursorPages<T>(
  path: string,
  options: { params?: Record<string, string>; auth?: boolean } = {},
): Promise<T[]> {
  const { params = {}, auth = true } = options;
  const items: T[] = [];
  let cursor: string | undefined;

  do {
    const searchParams = new URLSearchParams(params);
    searchParams.set("limit", String(MAX_PAGE_SIZE));
    if (cursor) {
      searchParams.set("cursor", cursor);
    }

    const data = await apiRequest<CursorPageResponse<T>>(`${path}?${searchParams.toString()}`, { auth });
    items.push(...data.items);
    cursor = data.has_next ? data.next_cursor ?? undefined : undefined;
  } while (cursor);

  return items;
}

/**
 * برای آپلود فایل (multipart/form-data) — عمداً هدر Content-Type دستی ست
 * نمی‌شود، چون مرورگر خودش باید boundary درست را برای FormData بسازد.
 */
export async function apiUploadFile<T>(path: string, formData: FormData): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers,
    body: formData,
  });

  return parseResponse<T>(response);
}
