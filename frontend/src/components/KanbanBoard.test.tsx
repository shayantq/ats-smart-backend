import { screen, within } from "@testing-library/react";
import KanbanBoard from "./KanbanBoard";
import { STATUS_COLUMNS } from "../types/application";
import { jsonResponse, mockFetchRoutes, renderWithProviders } from "../test/renderWithProviders";

const page = (items: unknown[]) => ({ items, next_cursor: null, previous_cursor: null, has_next: false, has_previous: false });

test("بدون انتخاب آگهی، راهنمای انتخاب آگهی نمایش داده می‌شود", () => {
  renderWithProviders(<KanbanBoard jobId="" />);

  expect(screen.getByText("برای مشاهده‌ی بورد، ابتدا یک آگهی شغلی انتخاب کنید.")).toBeInTheDocument();
});

test("همه‌ی ستون‌های ماشین وضعیت به ترتیب و هر کارت در ستون درست رندر می‌شود", async () => {
  mockFetchRoutes({
    "/applications/": () =>
      jsonResponse(
        page([
          { application_id: "a-1", candidate_id: "c-1", candidate_name: "Sara Ahmadi", current_status: "Draft", score_ai: 70, updated_at: "2026-10-01T10:00:00Z" },
          { application_id: "a-2", candidate_id: "c-2", candidate_name: "Reza Karimi", current_status: "Offer", score_ai: 91, updated_at: "2026-10-02T10:00:00Z" },
        ]),
      ),
  });

  renderWithProviders(<KanbanBoard jobId="job-1" />);

  const board = await screen.findByTestId("kanban-board");
  const columns = within(board).getAllByRole("region");
  expect(columns.map((column) => column.getAttribute("aria-label"))).toEqual(STATUS_COLUMNS.map((column) => column.label));
  expect(within(screen.getByTestId("kanban-column-Draft")).getByText("Sara Ahmadi")).toBeInTheDocument();
  expect(within(screen.getByTestId("kanban-column-Offer")).getByText("Reza Karimi")).toBeInTheDocument();
  expect(within(screen.getByTestId("kanban-column-Hired")).queryAllByTestId("application-card")).toHaveLength(0);
});

test("خطای سرور به‌جای کرش، پیام خطا نمایش می‌دهد", async () => {
  mockFetchRoutes({ "/applications/": () => jsonResponse({ detail: "boom" }, 500) });

  renderWithProviders(<KanbanBoard jobId="job-1" />);

  expect(await screen.findByText("خطا در دریافت لیست درخواست‌ها. اتصال به سرور را بررسی کنید.")).toBeInTheDocument();
});
