import { fireEvent, render, screen, within } from "@testing-library/react";
import KanbanColumn from "./KanbanColumn";
import ApplicationCard from "./ApplicationCard";
import type { ApplicationListItem } from "../types/application";

const cards: ApplicationListItem[] = [
  {
    application_id: "a-1",
    candidate_id: "c-1",
    candidate_name: "Sara Ahmadi",
    current_status: "Screening",
    score_ai: 82,
    updated_at: "2026-10-01T10:00:00Z",
  },
  {
    application_id: "a-2",
    candidate_id: "c-2",
    candidate_name: "Reza Karimi",
    current_status: "Screening",
    score_ai: null,
    updated_at: "2026-10-02T10:00:00Z",
  },
];

function renderColumn(applications: ApplicationListItem[], onDropOnColumn = jest.fn()) {
  render(
    <KanbanColumn
      status="Screening"
      label="غربالگری"
      applications={applications}
      draggedApplicationId={null}
      onDragStart={jest.fn()}
      onDragEnd={jest.fn()}
      onDropOnColumn={onDropOnColumn}
    />,
  );
  return { column: screen.getByRole("region", { name: "غربالگری" }), onDropOnColumn };
}

test("ستون عنوان، تعداد و کارت‌های خودش را رندر می‌کند", () => {
  const { column } = renderColumn(cards);

  expect(within(column).getByRole("heading", { name: "غربالگری" })).toBeInTheDocument();
  expect(within(column).getByTestId("column-count")).toHaveTextContent("2");
  expect(within(column).getAllByTestId("application-card")).toHaveLength(2);
});

test("ستون خالی پیام «کارتی نیست» نشان می‌دهد", () => {
  const { column } = renderColumn([]);

  expect(within(column).getByText("کارتی در این مرحله نیست")).toBeInTheDocument();
  expect(within(column).getByTestId("column-count")).toHaveTextContent("0");
});

test("رها کردن کارت روی ستون، وضعیت مقصد را گزارش می‌دهد", () => {
  const { column, onDropOnColumn } = renderColumn(cards);

  fireEvent.dragOver(column);
  fireEvent.drop(column);

  expect(onDropOnColumn).toHaveBeenCalledWith("Screening");
});

test("کارت کارجو قابل درگ است و امتیاز هوش مصنوعی را نشان می‌دهد", () => {
  const onDragStart = jest.fn();
  render(<ApplicationCard application={cards[0]} isDragging={false} onDragStart={onDragStart} onDragEnd={jest.fn()} />);
  const card = screen.getByTestId("application-card");

  expect(card).toHaveAttribute("draggable", "true");
  expect(card).toHaveTextContent("82%");
  fireEvent.dragStart(card);
  expect(onDragStart).toHaveBeenCalledWith(expect.anything(), cards[0]);
});

test("کارت بدون امتیاز، «بدون امتیاز» نشان می‌دهد", () => {
  render(<ApplicationCard application={cards[1]} isDragging={false} onDragStart={jest.fn()} onDragEnd={jest.fn()} />);

  expect(screen.getByText("بدون امتیاز")).toBeInTheDocument();
});
