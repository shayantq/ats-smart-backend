import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LoginPage from "./LoginPage";
import { jsonResponse, mockFetchRoutes, renderWithProviders } from "../test/renderWithProviders";
import { getToken } from "../services/tokenStorage";

beforeEach(() => localStorage.clear());

test("فرم ورود با فیلدهای ایمیل، رمز عبور و دکمه‌ی ورود رندر می‌شود", () => {
  renderWithProviders(<LoginPage />);

  expect(screen.getByRole("heading", { name: "ورود به ATS Smart" })).toBeInTheDocument();
  expect(screen.getByLabelText("ایمیل")).toHaveAttribute("type", "email");
  expect(screen.getByLabelText("رمز عبور")).toHaveAttribute("type", "password");
  expect(screen.getByRole("button", { name: "ورود" })).toBeEnabled();
});

test("ورود موفق: توکن ذخیره و کاربر (با نقش) در Redux ثبت می‌شود", async () => {
  const fetchMock = mockFetchRoutes({
    "/auth/login": () => jsonResponse({ access_token: "token-123", refresh_token: "r", token_type: "bearer", expires_in: 900 }),
    "/auth/me": () => jsonResponse({ user_id: "u-1", email: "hr@example.com", role: "HR_Manager" }),
  });
  const user = userEvent.setup();
  const { store } = renderWithProviders(<LoginPage />);

  await user.type(screen.getByLabelText("ایمیل"), "hr@example.com");
  await user.type(screen.getByLabelText("رمز عبور"), "Passw0rd!x");
  await user.click(screen.getByRole("button", { name: "ورود" }));

  await waitFor(() => expect(store.getState().auth.user?.role).toBe("HR_Manager"));
  expect(getToken()).toBe("token-123");
  const [, loginRequest] = fetchMock.mock.calls[0];
  expect(JSON.parse(loginRequest.body)).toEqual({ email: "hr@example.com", password: "Passw0rd!x" });
});

test("رمز اشتباه: پیام خطا نمایش داده می‌شود و هیچ توکنی ذخیره نمی‌شود", async () => {
  mockFetchRoutes({ "/auth/login": () => jsonResponse({ detail: "ایمیل یا گذرواژه نادرست است." }, 401) });
  const user = userEvent.setup();
  const { store } = renderWithProviders(<LoginPage />);

  await user.type(screen.getByLabelText("ایمیل"), "hr@example.com");
  await user.type(screen.getByLabelText("رمز عبور"), "wrong-password");
  await user.click(screen.getByRole("button", { name: "ورود" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("ایمیل یا رمز عبور نادرست است.");
  expect(getToken()).toBeNull();
  expect(store.getState().auth.isAuthenticated).toBe(false);
});
