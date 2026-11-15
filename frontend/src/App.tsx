import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import ActiveSessionsPanel from "./components/security/ActiveSessionsPanel";
import { ToastProvider } from "./context/ToastContext";
import HRDashboard from "./pages/HRDashboard";
import CandidatePortal from "./pages/CandidatePortal";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import { ACCOUNT_DELETED_EVENT, UNAUTHORIZED_EVENT } from "./services/apiClient";
import { fetchCurrentUser } from "./services/authApi";
import { logoutCurrentSession } from "./services/sessionsApi";
import { clearToken, getToken } from "./services/tokenStorage";
import { useAppDispatch, useAppSelector } from "./store/hooks";
import { clearUser, setUser } from "./store/slices/authSlice";
import ThemeControl from "./components/ThemeControl";

const ROLE_LABELS: Record<string, string> = {
  Admin: "مدیر سیستم",
  HR_Manager: "کارشناس منابع انسانی",
  Interviewer: "مصاحبه‌کننده",
  Candidate: "کارجو",
};

function App() {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();
  const user = useAppSelector((state) => state.auth.user);
  // اگر از قبل توکنی ذخیره شده، پیش از تصمیم‌گیری بین «صفحه‌ی ورود» و «پورتال» اعتبارش سنجیده می‌شود
  const [isRestoringSession, setIsRestoringSession] = useState(() => Boolean(getToken()));
  // لینک «مشاهده‌ی نشست‌های فعال» در ایمیل هشدار ورود: /?view=sessions
  const [showSessions, setShowSessions] = useState(
    () => new URLSearchParams(window.location.search).get("view") === "sessions",
  );
  // صفحه‌ی ورود یا ثبت‌نام کارجو (برای کاربر واردنشده) + پیام موفقیت روی صفحه‌ی ورود
  const [authView, setAuthView] = useState<"login" | "register">("login");
  const [loginNotice, setLoginNotice] = useState<{ message: string; email: string } | null>(null);

  useEffect(() => {
    if (!isRestoringSession) return;
    fetchCurrentUser()
      .then((currentUser) => dispatch(setUser(currentUser)))
      .catch(() => clearToken())
      .finally(() => setIsRestoringSession(false));
  }, [isRestoringSession, dispatch]);

  // توکن منقضی/نامعتبر در هر درخواستی → بازگشت به صفحه‌ی ورود
  useEffect(() => {
    const handleUnauthorized = () => {
      dispatch(clearUser());
      queryClient.clear();
    };
    window.addEventListener(UNAUTHORIZED_EVENT, handleUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, handleUnauthorized);
  }, [dispatch, queryClient]);

  // حذف حساب کارجو (ProfileTab): خروج و پیام تأیید روی صفحه‌ی ورود
  useEffect(() => {
    const handleAccountDeleted = () => {
      clearToken();
      setShowSessions(false);
      setLoginNotice({ message: "حساب شما حذف شد و اطلاعات هویتی و فایل رزومه‌تان پاک شد.", email: "" });
      dispatch(clearUser());
      queryClient.clear();
    };
    window.addEventListener(ACCOUNT_DELETED_EVENT, handleAccountDeleted);
    return () => window.removeEventListener(ACCOUNT_DELETED_EVENT, handleAccountDeleted);
  }, [dispatch, queryClient]);

  function handleLogout() {
    // نشست همین دستگاه سمت سرور هم باطل شود (کوکی Refresh Token دیگر قابل استفاده نیست)؛ خطای شبکه مانع خروج نمی‌شود
    logoutCurrentSession().catch(() => undefined);
    clearToken();
    setShowSessions(false);
    dispatch(clearUser());
    queryClient.clear(); // داده‌های کش‌شده‌ی کاربر قبلی برای کاربر بعدی نمی‌ماند
  }

  if (isRestoringSession) {
    return <p className="p-6 text-center text-sm text-slate-600 dark:text-slate-300">در حال بارگذاری...</p>;
  }

  return (
    <ToastProvider>
      {user === null && <div className="flex justify-end px-4 py-3"><ThemeControl /></div>}
      {user === null ? (
        authView === "register" ? (
          <RegisterPage
            onRegistered={(email) => {
              setLoginNotice({ message: "ثبت‌نام انجام شد؛ حالا وارد شوید.", email });
              setAuthView("login");
            }}
            onBackToLogin={() => setAuthView("login")}
          />
        ) : (
          <LoginPage
            key={loginNotice?.email ?? ""}
            notice={loginNotice?.message ?? null}
            initialEmail={loginNotice?.email ?? ""}
            onRegisterClick={() => {
              setLoginNotice(null);
              setAuthView("register");
            }}
          />
        )
      ) : (
        <>
          <a href="#main-content" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:right-2 focus:z-50 focus:rounded focus:bg-paper focus:p-3 focus:text-ink">رفتن به محتوای اصلی</a>
          <header className="border-b border-slate-200 dark:border-slate-500 bg-white dark:bg-slate-800">
            <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-8 lg:px-12">
              <span className="text-sm font-bold text-slate-800 dark:text-slate-200">ATS Smart</span>
              <div className="flex min-w-0 flex-wrap items-center gap-3">
                <ThemeControl />
                <span className="min-w-0 break-words text-caption text-muted">
                  <bdi>{user.email}</bdi> · {ROLE_LABELS[user.role] ?? user.role}
                </span>
                <button
                  onClick={() => setShowSessions((value) => !value)}
                  aria-pressed={showSessions}
                  className="rounded-md border border-slate-500 dark:border-slate-500 px-3 py-1 text-xs font-semibold text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-900"
                >
                  {showSessions ? "بازگشت" : "نشست‌های فعال"}
                </button>
                <button
                  onClick={handleLogout}
                  className="rounded-md border border-slate-500 dark:border-slate-500 px-3 py-1 text-xs font-semibold text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-900"
                >
                  خروج
                </button>
              </div>
            </div>
          </header>
          <main id="main-content" tabIndex={-1}>
          {showSessions ? <ActiveSessionsPanel /> : user.role === "Candidate" ? <CandidatePortal /> : <HRDashboard />}
          </main>
        </>
      )}
    </ToastProvider>
  );
}

export default App;
