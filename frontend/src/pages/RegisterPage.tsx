import { useState, type FormEvent } from "react";
import { ApiError } from "../services/apiClient";
import { registerCandidate } from "../services/authApi";

/**
 * نسخه‌ی متن رضایت‌نامه؛ با app/core/privacy.py::PRIVACY_NOTICE_VERSION بک‌اند یکی است (سرور همان را ثبت می‌کند).
 * هر تغییر در متن پایین باید با تغییر نسخه در هر دو طرف همراه باشد.
 */
export const PRIVACY_NOTICE_VERSION = "2026-10";

interface RegisterPageProps {
  onRegistered: (email: string) => void;
  onBackToLogin: () => void;
}

/**
 * ثبت‌نام کارجو با رضایت صریح پردازش داده‌های شخصی (GDPR): دکمه‌ی ثبت‌نام تا تیک خوردن رضایت‌نامه غیرفعال است.
 */
export default function RegisterPage({ onRegistered, onBackToLogin }: RegisterPageProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [consent, setConsent] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!consent) return;
    setErrorMessage(null);
    setIsSubmitting(true);

    try {
      await registerCandidate(email.trim(), password, consent);
      onRegistered(email.trim());
    } catch (error) {
      if (error instanceof ApiError && error.status === 400) {
        setErrorMessage("با این ایمیل قبلاً حساب ساخته شده است.");
      } else if (error instanceof ApiError && error.status === 422) {
        setErrorMessage("ایمیل معتبر و رمز عبور دست‌کم ۸ کاراکتری وارد کنید.");
      } else if (error instanceof ApiError && error.status === 429) {
        setErrorMessage("تعداد تلاش‌ها زیاد بوده؛ یک دقیقه‌ی دیگر دوباره امتحان کنید.");
      } else {
        setErrorMessage("ارتباط با سرور برقرار نشد. لطفاً دوباره تلاش کنید.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-100 p-4">
      <form
        onSubmit={handleSubmit}
        aria-labelledby="register-title"
        className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-6 shadow-sm"
      >
        <h1 id="register-title" className="mb-1 text-xl font-bold text-slate-800">
          ثبت‌نام کارجو
        </h1>
        <p className="mb-6 text-sm text-slate-500">ساخت حساب برای ارسال رزومه و پیگیری درخواست‌ها</p>

        <label htmlFor="register-email" className="mb-1 block text-sm font-semibold text-slate-700">
          ایمیل
        </label>
        <input
          id="register-email"
          type="email"
          dir="ltr"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className="mb-4 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />

        <label htmlFor="register-password" className="mb-1 block text-sm font-semibold text-slate-700">
          رمز عبور
        </label>
        <input
          id="register-password"
          type="password"
          dir="ltr"
          autoComplete="new-password"
          required
          minLength={8}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="mb-4 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />

        <details className="mb-3 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs leading-6 text-slate-600">
          <summary className="cursor-pointer font-semibold text-slate-700">متن رضایت‌نامه‌ی حریم خصوصی</summary>
          <ul className="mt-2 list-disc space-y-1 pr-4">
            <li>نام، شماره‌ی تماس، آدرس و متن رزومه‌ی شما فقط برای فرایند استخدام سازمان‌هایی که به آن‌ها درخواست می‌دهید پردازش می‌شود.</li>
            <li>این اطلاعات در پایگاه داده رمزنگاری‌شده ذخیره می‌شود و فقط کارشناسان مجاز همان سازمان‌ها آن را می‌بینند.</li>
            <li>هر زمان بخواهید، از بخش «پروفایل» می‌توانید حساب خود را حذف کنید؛ اطلاعات هویتی و فایل رزومه‌تان پاک می‌شود و فقط آمار بی‌نام درخواست‌ها می‌ماند.</li>
          </ul>
          <p className="mt-2 text-[11px] text-slate-400">نسخه‌ی {PRIVACY_NOTICE_VERSION}</p>
        </details>

        <label className="mb-4 flex items-start gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={consent}
            onChange={(event) => setConsent(event.target.checked)}
            className="mt-1"
          />
          <span>رضایت‌نامه‌ی حریم خصوصی را خواندم و با پردازش اطلاعات شخصی‌ام برای فرایند استخدام موافقم.</span>
        </label>

        {errorMessage && (
          <p role="alert" className="mb-4 rounded-md bg-red-50 p-2 text-sm text-red-600">
            {errorMessage}
          </p>
        )}

        <button
          type="submit"
          disabled={!consent || isSubmitting}
          className="w-full rounded-md bg-blue-600 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isSubmitting ? "در حال ثبت‌نام..." : "ثبت‌نام"}
        </button>
        <button
          type="button"
          onClick={onBackToLogin}
          className="mt-3 w-full text-center text-xs font-semibold text-blue-600 hover:underline"
        >
          حساب دارید؟ ورود
        </button>
      </form>
    </main>
  );
}
