import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import KanbanBoard from "./KanbanBoard";
import { renderWithProviders } from "../test/renderWithProviders";
import { setUser } from "../store/slices/authSlice";
import * as api from "../services/applicationsApi";
import { allowedDestinations, STATUS_COLUMNS, type ApplicationListItem } from "../types/application";
jest.mock("../services/applicationsApi");
const item:ApplicationListItem={application_id:"a",candidate_id:"c",candidate_name:"مریم احمدی",current_status:"Screening",score_ai:80,updated_at:"2026-11-15T10:00:00Z"};
function setup(role="HR_Manager") {
  const view=renderWithProviders(<KanbanBoard jobId="j" />);
  act(()=>{view.store.dispatch(setUser({id:"hr",email:"hr@example.test",role}));});return view;
}
beforeEach(()=>{jest.clearAllMocks();jest.mocked(api.fetchApplicationsForJob).mockResolvedValue([item]);});
test("مقصدها با ماشین وضعیت خطی و حالت نهایی منطبق‌اند",()=>{
  for(let i=0;i<7;i++)expect(allowedDestinations(STATUS_COLUMNS[i].value)).toEqual([STATUS_COLUMNS[i+1].value,"Rejected"]);
  expect(allowedDestinations("Hired")).toEqual([]);expect(allowedDestinations("Rejected")).toEqual([]);
});
test("انتخاب مقصد و Escape بدون درخواست سرور لغو می‌شود",async()=>{
  setup();const control=await screen.findByRole("button",{name:/تغییر وضعیت مریم/});control.focus();
  await userEvent.keyboard(" {ArrowLeft}{Escape}");
  expect(api.updateApplicationStatus).not.toHaveBeenCalled();
  expect(screen.getByRole("status")).toHaveTextContent("انتقال مریم احمدی لغو شد");expect(control).toHaveFocus();
});
test("تأیید کیبورد فقط یک درخواست می‌فرستد و بعد از تأیید سرور موفقیت را اعلام می‌کند",async()=>{
  let complete!:(value:Awaited<ReturnType<typeof api.updateApplicationStatus>>)=>void;
  jest.mocked(api.updateApplicationStatus).mockImplementation(()=>new Promise(resolve=>{complete=resolve}));
  setup();const control=await screen.findByRole("button",{name:/تغییر وضعیت مریم/});control.focus();
  await userEvent.keyboard("{Enter}{Enter}{Enter}");
  await waitFor(()=>expect(api.updateApplicationStatus).toHaveBeenCalledTimes(1));
  expect(screen.getByRole("status")).toHaveTextContent("منتظر تأیید سرور");
  expect(within(screen.getByTestId("kanban-column-Technical Interview")).getByText(item.candidate_name)).toBeInTheDocument();
  expect(screen.getByRole("button",{name:/تغییر وضعیت مریم/})).toHaveFocus();
  jest.mocked(api.fetchApplicationsForJob).mockResolvedValue([{...item,current_status:"Technical Interview"}]);
  complete({application_id:"a",previous_status:"Screening",new_status:"Technical Interview",updated_at:item.updated_at});
  await waitFor(()=>expect(screen.getByRole("status")).toHaveTextContent("وضعیت مریم احمدی با موفقیت به مصاحبه فنی تغییر کرد"));
});
test("شکست تغییر وضعیت کارت را برمی‌گرداند و پیام موفقیت نمی‌دهد",async()=>{
  jest.mocked(api.updateApplicationStatus).mockRejectedValue(Error("offline"));setup();
  (await screen.findByRole("button",{name:/تغییر وضعیت مریم/})).focus();await userEvent.keyboard("{Enter}{ArrowLeft}{Enter}");
  await waitFor(()=>expect(screen.getByRole("status")).toHaveTextContent("انتقال مریم احمدی به رد شده ناموفق بود؛ وضعیت غربالگری بازگردانده شد"));
  expect(within(screen.getByTestId("kanban-column-Screening")).getByText(item.candidate_name)).toBeInTheDocument();
  expect(screen.getByRole("button",{name:/تغییر وضعیت مریم/})).toHaveFocus();
});
test("جهت‌ها بین کارت‌ها و ستون‌های غیرخالی با ترتیب RTL حرکت می‌کنند",async()=>{
  jest.mocked(api.fetchApplicationsForJob).mockResolvedValue([item,{...item,application_id:"b",candidate_name:"سارا"},{...item,application_id:"c",candidate_name:"رضا",current_status:"Offer"}]);
  setup();(await screen.findByRole("button",{name:/تغییر وضعیت مریم/})).focus();
  await userEvent.keyboard("{ArrowDown}");expect(screen.getByRole("button",{name:/تغییر وضعیت سارا/})).toHaveFocus();
  await userEvent.keyboard("{ArrowLeft}");expect(screen.getByRole("button",{name:/تغییر وضعیت رضا/})).toHaveFocus();
  await userEvent.keyboard("{ArrowRight}");expect(screen.getByRole("button",{name:/تغییر وضعیت مریم/})).toHaveFocus();
});
test("نقش بدون مجوز و پرش ماوس هیچ mutation نمی‌فرستند",async()=>{
  const view=setup("Interviewer");const control=await screen.findByRole("button",{name:/تغییر وضعیت مریم/});await userEvent.click(control);
  expect(api.updateApplicationStatus).not.toHaveBeenCalled();
  act(()=>{view.store.dispatch(setUser({id:"hr",email:"hr@example.test",role:"HR_Manager"}));});
  fireEvent.dragStart(screen.getByTestId("application-card"));fireEvent.drop(screen.getByTestId("kanban-column-Hired"));
  expect(api.updateApplicationStatus).not.toHaveBeenCalled();expect(screen.getByRole("status")).toHaveTextContent("طبق قوانین مجاز نیست");
});
