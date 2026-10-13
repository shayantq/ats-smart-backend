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

test("توکن منقضی‌شده: بازگشت خودکار به صفحه‌ی ورود", async () => {
  setToken("expired-token");
  mockFetchRoutes({ "/auth/me": () => jsonResponse({ detail: "expired" }, 401) });
  renderWithProviders(<App />);

  expect(await screen.findByRole("button", { name: "ورود" })).toBeInTheDocument();
  expect(getToken()).toBeNull();
});
