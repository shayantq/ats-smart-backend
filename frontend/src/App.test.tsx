import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";
import { jsonResponse, mockFetchRoutes, renderWithProviders } from "./test/renderWithProviders";
import { getToken, setToken } from "./services/tokenStorage";

const emptyPage = { items: [], next_cursor: null, previous_cursor: null, has_next: false, has_previous: false };

beforeEach(() => localStorage.clear());

test("بدون توکن، صفحه‌ی ورود نمایش داده می‌شود", () => {
  renderWithProviders(<App />);

  expect(screen.getByRole("button", { name: "ورود" })).toBeInTheDocument();
});

test("کاربر HR با توکن معتبر مستقیم به داشبورد HR می‌رود و می‌تواند خارج شود", async () => {
  setToken("valid-token");
  mockFetchRoutes({
    "/auth/me": () => jsonResponse({ user_id: "u-1", email: "hr@example.com", role: "HR_Manager" }),
    "/jobs/": () => jsonResponse(emptyPage),
    "/notifications/me": () => jsonResponse({ ...emptyPage, unread_count: 0 }),
  });
  renderWithProviders(<App />);

  expect(await screen.findByRole("heading", { name: "داشبورد کارشناس منابع انسانی" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "بورد کانبان" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByText("hr@example.com")).toBeInTheDocument();

  await userEvent.setup().click(screen.getByRole("button", { name: "خروج" }));

  expect(screen.getByRole("button", { name: "ورود" })).toBeInTheDocument();
  expect(getToken()).toBeNull();
});

test("کارجو به پورتال کارجو هدایت می‌شود", async () => {
  setToken("valid-token");
  mockFetchRoutes({
    "/auth/me": () => jsonResponse({ user_id: "u-2", email: "sara@example.com", role: "Candidate" }),
    "/candidates/me": () =>
      jsonResponse({ candidate_id: "c-1", email: "sara@example.com", first_name: "Sara", last_name: "", phone: null, location: null, skills: [] }),
    "/jobs/": () => jsonResponse(emptyPage),
  });
  renderWithProviders(<App />);

  expect(await screen.findByRole("heading", { name: "پورتال کارجو" })).toBeInTheDocument();
});

test("access_token منقضی ولی نشست معتبر: نوسازی خودکار با کوکی و ادامه بدون صفحه‌ی ورود", async () => {
  setToken("expired-token");
  const fetchMock = mockFetchRoutes({
    "/auth/refresh": () => jsonResponse({ access_token: "fresh-token", refresh_token: null, token_type: "bearer", expires_in: 900 }),
    "/auth/me": () =>
      fetchMock.mock.calls.some(([url]) => String(url).includes("/auth/refresh"))
        ? jsonResponse({ user_id: "u-2", email: "sara@example.com", role: "Candidate" })
        : jsonResponse({ detail: "expired" }, 401),
    "/candidates/me": () =>
      jsonResponse({ candidate_id: "c-1", email: "sara@example.com", first_name: "Sara", last_name: "", phone: null, location: null, skills: [] }),
    "/jobs/": () => jsonResponse(emptyPage),
  });
  renderWithProviders(<App />);

  expect(await screen.findByRole("heading", { name: "پورتال کارجو" })).toBeInTheDocument();
  expect(getToken()).toBe("fresh-token");
  const refreshCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/auth/refresh"));
  expect(refreshCall?.[1]).toMatchObject({ method: "POST", credentials: "include" });
});

test("نشست این دستگاه از دستگاه دیگر باطل شده: نوسازی 401 → صفحه‌ی ورود", async () => {
  setToken("revoked-session-token");
  mockFetchRoutes({
    "/auth/refresh": () => jsonResponse({ detail: "نشست شما پایان یافته است" }, 401),
    "/auth/me": () => jsonResponse({ detail: "revoked" }, 401),
  });
  renderWithProviders(<App />);

  expect(await screen.findByRole("button", { name: "ورود" })).toBeInTheDocument();
  expect(getToken()).toBeNull();
});

test("لینک ایمیل هشدار (?view=sessions) مستقیم صفحه‌ی نشست‌های فعال را باز می‌کند", async () => {
  window.history.pushState({}, "", "/?view=sessions");
  setToken("valid-token");
  mockFetchRoutes({
    "/auth/me": () => jsonResponse({ user_id: "u-1", email: "hr@example.com", role: "HR_Manager" }),
    "/auth/sessions/": () => jsonResponse({ items: [] }),
  });
  renderWithProviders(<App />);

  expect(await screen.findByRole("heading", { name: "نشست‌های فعال" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "بازگشت" })).toHaveAttribute("aria-pressed", "true");
  window.history.pushState({}, "", "/");
});

test("توکن منقضی‌شده: بازگشت خودکار به صفحه‌ی ورود", async () => {
  setToken("expired-token");
  mockFetchRoutes({ "/auth/me": () => jsonResponse({ detail: "expired" }, 401) });
  renderWithProviders(<App />);

  expect(await screen.findByRole("button", { name: "ورود" })).toBeInTheDocument();
  expect(getToken()).toBeNull();
});
