import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../../App";
import { jsonResponse, mockFetchRoutes, renderWithProviders } from "../../test/renderWithProviders";
import { setToken } from "../../services/tokenStorage";

const emptyPage = { items: [], next_cursor: null, previous_cursor: null, has_next: false, has_previous: false };
const createdJob = {
  job_id: "job-1",
  title: "Backend Developer",
  department: null,
  description: null,
  skills_required: ["Python"],
  salary_range: null,
  status: "Active",
  created_by: "u-1",
  created_at: null,
};

beforeEach(() => {
  localStorage.clear();
  setToken("valid-token");
});

function mockStaff(role: string) {
  let jobs: (typeof createdJob)[] = [];
  const fetchMock = mockFetchRoutes({
    "/auth/me": () => jsonResponse({ user_id: "u-1", email: "hr@example.com", role }),
    "/notifications/me": () => jsonResponse({ ...emptyPage, unread_count: 0 }),
    "/applications/": () => jsonResponse(emptyPage),
    "/jobs/?": () => jsonResponse({ ...emptyPage, items: jobs }),
    "/jobs/": () => {
      jobs = [createdJob];
      return jsonResponse(createdJob, 201);
    },
  });
  return fetchMock;
}

test("HR از تب «ثبت آگهی» آگهی می‌سازد و همان آگهی در بورد انتخاب می‌شود", async () => {
  const fetchMock = mockStaff("HR_Manager");
  const user = userEvent.setup();
  renderWithProviders(<App />);

  await user.click(await screen.findByRole("button", { name: "ثبت اولین آگهی" }));
  await user.type(screen.getByLabelText(/عنوان آگهی/), "Backend Developer");
  await user.selectOptions(screen.getByLabelText("سطح ارشدیت"), "senior");
  await user.type(screen.getByLabelText("موقعیت مکانی"), "Tehran");
  await user.click(screen.getByRole("button", { name: "انتشار آگهی" }));

  await waitFor(() => expect(screen.getByRole("tab", { name: "بورد کانبان" })).toHaveAttribute("aria-selected", "true"));
  expect(await screen.findByRole("option", { name: "Backend Developer" })).toBeInTheDocument();
  const post = fetchMock.mock.calls.find(([url, init]) => String(url).endsWith("/jobs/") && init?.method === "POST");
  expect(JSON.parse(post?.[1]?.body as string)).toEqual({
    title: "Backend Developer",
    skills_required: [],
    required_seniority: "senior",
    location: "Tehran",
  });
});

test("مصاحبه‌کننده تب ثبت آگهی را نمی‌بیند", async () => {
  mockStaff("Interviewer");
  renderWithProviders(<App />);

  expect(await screen.findByRole("tab", { name: "بورد کانبان" })).toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: "ثبت آگهی" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "ثبت اولین آگهی" })).not.toBeInTheDocument();
});
