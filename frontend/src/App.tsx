import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import ActiveSessionsPanel from "./components/security/ActiveSessionsPanel";
import { ToastProvider } from "./context/ToastContext";
import HRDashboard from "./pages/HRDashboard";
import CandidatePortal from "./pages/CandidatePortal";
import LoginPage from "./pages/LoginPage";
import { UNAUTHORIZED_EVENT } from "./services/apiClient";
import { fetchCurrentUser } from "./services/authApi";
import { logoutCurrentSession } from "./services/sessionsApi";
import { clearToken, getToken } from "./services/tokenStorage";
import { useAppDispatch, useAppSelector } from "./store/hooks";
import { clearUser, setUser } from "./store/slices/authSlice";

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

  function handleLogout() {
    // نشست همین دستگاه سمت سرور هم باطل شود (کوکی Refresh Token دیگر قابل استفاده نیست)؛ خطای شبکه مانع خروج نمی‌شود
    logoutCurrentSession().catch(() => undefined);
    clearToken();
    setShowSessions(false);
    dispatch(clearUser());
    queryClient.clear(); // داده‌های کش‌شده‌ی کاربر قبلی برای کاربر بعدی نمی‌ماند
  }

  if (isRestoringSession) {
    return <p className="p-6 text-center text-sm text-slate-500">در حال بارگذاری...</p>;
  }

  return (
    <ToastProvider>
      {user === null ? (
        <LoginPage />
      ) : (
        <>
          <header className="border-b border-slate-200 bg-white">
            <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-2 sm:px-6">
              <span className="text-sm font-bold text-slate-800">ATS Smart</span>
              <div className="flex items-center gap-3">
                <span className="text-xs text-slate-500">
                  <span dir="ltr">{user.email}</span> · {ROLE_LABELS[user.role] ?? user.role}
                </span>
                <button
                  onClick={() => setShowSessions((value) => !value)}
                  aria-pressed={showSessions}
                  className="rounded-md border border-slate-300 px-3 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50"
                >
                  {showSessions ? "بازگشت" : "نشست‌های فعال"}
                </button>
                <button
                  onClick={handleLogout}
                  className="rounded-md border border-slate-300 px-3 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50"
                >
                  خروج
                </button>
              </div>
            </div>
          </header>
          {showSessions ? <ActiveSessionsPanel /> : user.role === "Candidate" ? <CandidatePortal /> : <HRDashboard />}
        </>
      )}
    </ToastProvider>
  );
}

export default App;
