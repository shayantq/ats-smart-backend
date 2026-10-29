import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ActiveSessionsPanel from "./ActiveSessionsPanel";
import { jsonResponse, mockFetchRoutes, renderWithProviders } from "../../test/renderWithProviders";
import { setToken } from "../../services/tokenStorage";
import type { UserSession } from "../../types/session";

const baseSession: UserSession = {
  id: "s-current",
  browser: "Chrome",
  browser_version: "129.0.0",
  os: "Windows",
  os_version: "10",
  device_type: "desktop",
  device: "",
  user_agent: "Mozilla/5.0 ...",
  ip: "5.160.0.10",
  location: { country: "Iran", country_code: "IR", city: "Tehran" },
  created_at: "2026-10-29T08:00:00Z",
  last_active_at: "2026-10-29T09:30:00Z",
  expires_at: "2026-11-05T08:00:00Z",
  is_current: true,
  suspicious: false,
};

const phoneSession: UserSession = {
  ...baseSession,
  id: "s-phone",
  browser: "Mobile Safari",
  browser_version: "17.5",
  os: "iOS",
  os_version: "17.5",
  device_type: "mobile",
  device: "Apple iPhone",
  ip: "46.4.0.x",
  location: { country: "Germany", country_code: "DE", city: "Frankfurt am Main" },
  is_current: false,
  suspicious: true,
};

beforeEach(() => {
  localStorage.clear();
  setToken("valid-token");
});

test("فهرست نشست‌ها مرورگر، سیستم‌عامل، دستگاه، IP، موقعیت و آخرین فعالیت را نشان می‌دهد", async () => {
  mockFetchRoutes({ "/auth/sessions/": () => jsonResponse({ items: [baseSession, phoneSession] }) });
  renderWithProviders(<ActiveSessionsPanel />);

  const items = await screen.findAllByRole("listitem");
  expect(items).toHaveLength(2);

  expect(within(items[0]).getByText("Chrome 129.0.0 · Windows 10")).toBeInTheDocument();
  expect(within(items[0]).getByText("همین دستگاه")).toBeInTheDocument();
  expect(within(items[0]).queryByRole("button", { name: "خروج از این دستگاه" })).not.toBeInTheDocument();
  expect(within(items[0]).getByText(/آخرین فعالیت/)).toBeInTheDocument();

  expect(within(items[1]).getByText("Mobile Safari 17.5 · iOS 17.5")).toBeInTheDocument();
  expect(within(items[1]).getByText("تلفن همراه (Apple iPhone)")).toBeInTheDocument();
  expect(within(items[1]).getByText("ورود مشکوک")).toBeInTheDocument();
  expect(within(items[1]).getByText("46.4.0.x")).toBeInTheDocument();
  expect(within(items[1]).getByText(/Frankfurt am Main، Germany/)).toBeInTheDocument();
});

test("«خروج از این دستگاه» نشست را با DELETE باطل و فهرست را تازه می‌کند", async () => {
  let sessions = [baseSession, phoneSession];
  const fetchMock = mockFetchRoutes({
    "/auth/sessions/s-phone/": () => {
      sessions = [baseSession];
      return { ok: true, status: 204, json: async () => undefined } as Response;
    },
    "/auth/sessions/": () => jsonResponse({ items: sessions }),
  });
  renderWithProviders(<ActiveSessionsPanel />);

  await userEvent.setup().click(await screen.findByRole("button", { name: "خروج از این دستگاه" }));

  await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(1));
  const deleteCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/auth/sessions/s-phone/"));
  expect(deleteCall?.[1]).toMatchObject({ method: "DELETE" });
  expect(await screen.findByText("نشست آن دستگاه بسته شد.")).toBeInTheDocument();
});
