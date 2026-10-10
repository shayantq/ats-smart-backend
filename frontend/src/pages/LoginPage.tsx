import { useState, type FormEvent } from "react";
import { ApiError } from "../services/apiClient";
import { fetchCurrentUser, login } from "../services/authApi";
import { clearToken, setToken } from "../services/tokenStorage";
import { useAppDispatch } from "../store/hooks";
import { setUser } from "../store/slices/authSlice";

/**
 * صفحه‌ی ورود: ایمیل + رمز عبور → POST /auth/login → ذخیره‌ی توکن → GET /auth/me →
 * ثبت کاربر در Redux؛ App.tsx بر اساس نقش، کاربر را به پورتال مناسبش هدایت می‌کند.
 */
export default function LoginPage() {
  const dispatch = useAppDispatch();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setErrorMessage(null);
    setIsSubmitting(true);

    try {
      const tokens = await login(email.trim(), password);
      setToken(tokens.access_token);
      dispatch(setUser(await fetchCurrentUser()));
    } catch (error) {
      clearToken();
      if (error instanceof ApiError && error.status === 401) {
        setErrorMessage("ایمیل یا رمز عبور نادرست است.");
      } else if (error instanceof ApiError && error.status === 429) {
        setErrorMessage("تعداد تلاش‌های ورود زیاد بوده؛ یک دقیقه‌ی دیگر دوباره امتحان کنید.");
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
        aria-labelledby="login-title"
        className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-6 shadow-sm"
      >
        <h1 id="login-title" className="mb-1 text-xl font-bold text-slate-800">
          ورود به ATS Smart
        </h1>
        <p className="mb-6 text-sm text-slate-500">سامانه‌ی هوشمند جذب و استخدام</p>

        <label htmlFor="login-email" className="mb-1 block text-sm font-semibold text-slate-700">
          ایمیل
        </label>
        <input
          id="login-email"
          type="email"
          dir="ltr"
          autoComplete="username"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className="mb-4 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />

        <label htmlFor="login-password" className="mb-1 block text-sm font-semibold text-slate-700">
          رمز عبور
        </label>
        <input
          id="login-password"
          type="password"
          dir="ltr"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="mb-4 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />

        {errorMessage && (
          <p role="alert" className="mb-4 rounded-md bg-red-50 p-2 text-sm text-red-600">
            {errorMessage}
          </p>
        )}

        <button
          type="submit"
          disabled={isSubmitting}
          className="w-full rounded-md bg-blue-600 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
        >
          {isSubmitting ? "در حال ورود..." : "ورود"}
        </button>
      </form>
    </main>
  );
}
