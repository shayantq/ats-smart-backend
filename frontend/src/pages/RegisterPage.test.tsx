import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import RegisterPage from "./RegisterPage";
import { jsonResponse, mockFetchRoutes, renderWithProviders } from "../test/renderWithProviders";
import { setToken } from "../services/tokenStorage";

beforeEach(() => localStorage.clear());

test("دکمه‌ی ثبت‌نام تا تأیید رضایت‌نامه‌ی حریم خصوصی غیرفعال است", async () => {
  const fetchMock = mockFetchRoutes({ "/auth/register": () => jsonResponse({ status: "success" }, 201) });
  const onRegistered = jest.fn();
  const user = userEvent.setup();
  renderWithProviders(<RegisterPage onRegistered={onRegistered} onBackToLogin={jest.fn()} />);

  await user.type(screen.getByLabelText("ایمیل"), "sara@example.com");
  await user.type(screen.getByLabelText("رمز عبور"), "Passw0rd!x");
  const submit = screen.getByRole("button", { name: "ثبت‌نام" });
  expect(submit).toBeDisabled();
  expect(screen.getByText("متن رضایت‌نامه‌ی حریم خصوصی")).toBeInTheDocument();

  await user.click(screen.getByRole("checkbox"));
  expect(submit).toBeEnabled();
  await user.click(submit);

  await waitFor(() => expect(onRegistered).toHaveBeenCalledWith("sara@example.com"));
  const [, request] = fetchMock.mock.calls[0];
  expect(JSON.parse(request.body)).toEqual({
    email: "sara@example.com",
    password: "Passw0rd!x",
    role: "Candidate",
    data_consent: true,
  });
});

test("از صفحه‌ی ورود به ثبت‌نام و بعد از ثبت‌نام با پیام موفقیت به ورود برمی‌گردد", async () => {
  mockFetchRoutes({ "/auth/register": () => jsonResponse({ status: "success" }, 201) });
  const user = userEvent.setup();
  renderWithProviders(<App />);

  await user.click(screen.getByRole("button", { name: "کارجو هستید و حساب ندارید؟ ثبت‌نام" }));
  await user.type(screen.getByLabelText("ایمیل"), "new@example.com");
  await user.type(screen.getByLabelText("رمز عبور"), "Passw0rd!x");
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "ثبت‌نام" }));

  expect(await screen.findByRole("status")).toHaveTextContent("ثبت‌نام انجام شد");
  expect(screen.getByLabelText("ایمیل")).toHaveValue("new@example.com");
});

test("حذف حساب کارجو: تأیید دومرحله‌ای، DELETE و بازگشت به صفحه‌ی ورود با پیام", async () => {
  setToken("valid-token");
  const fetchMock = mockFetchRoutes({
    "/auth/me": () => jsonResponse({ user_id: "u-2", email: "sara@example.com", role: "Candidate" }),
    "/candidates/me/applications": () =>
      jsonResponse({ items: [], next_cursor: null, previous_cursor: null, has_next: false, has_previous: false }),
    "/candidates/me/offers": () =>
      jsonResponse({ items: [], next_cursor: null, previous_cursor: null, has_next: false, has_previous: false }),
    "/candidates/me/": () => jsonResponse({ message: "deleted", resumes_cleared: 1, files_deleted: 1 }),
    "/candidates/me": () =>
      jsonResponse({ id: "c-1", email: "sara@example.com", first_name: "Sara", last_name: "A", phone: null, location: null, skills: [] }),
    "/jobs/": () => jsonResponse({ items: [], next_cursor: null, previous_cursor: null, has_next: false, has_previous: false }),
  });
  const user = userEvent.setup();
  renderWithProviders(<App />);

  await user.click(await screen.findByRole("tab", { name: "پروفایل" }));
  await user.click(await screen.findByRole("button", { name: "حذف حساب" }));
  await user.click(screen.getByRole("button", { name: "بله، حسابم برای همیشه حذف شود" }));

  expect(await screen.findByRole("status")).toHaveTextContent("حساب شما حذف شد");
  expect(screen.getByRole("button", { name: "ورود" })).toBeInTheDocument();
  const deleteCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/candidates/me/"));
  expect(deleteCall?.[1]).toMatchObject({ method: "DELETE" });
});
