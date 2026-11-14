import { fireEvent, screen } from "@testing-library/react";
import { renderWithProviders as render } from "../test/renderWithProviders";
import { fetchApplicationDossier } from "../services/applicationsApi";
import userEvent from "@testing-library/user-event";
import ApplicationCard from "./ApplicationCard";
import type { ApplicationListItem } from "../types/application";
jest.mock("../services/applicationsApi", () => ({fetchApplicationDossier:jest.fn()}));
beforeEach(()=>jest.mocked(fetchApplicationDossier).mockResolvedValue({application_id:"a1",resume_id:null,raw_text:null,parsed_data:null,skill_analysis:null,agent_analysis:null}));

const application: ApplicationListItem = {
  application_id: "a1", candidate_id: "c1", candidate_name: "مریم احمدی",
  current_status: "Screening", score_ai: 82, updated_at: "2026-11-10T10:00:00Z",
};

// jsdom رفتار native dialog را اجرا نمی‌کند؛ فقط باز/بسته‌شدن برای تست رفتار شبیه‌سازی می‌شود.
beforeAll(() => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value() { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value() { this.removeAttribute("open"); } });
});
afterAll(() => {
  delete (HTMLDialogElement.prototype as Partial<HTMLDialogElement>).showModal;
  delete (HTMLDialogElement.prototype as Partial<HTMLDialogElement>).close;
});

test("پرونده فقط امتیاز واقعی و نبود دادهٔ تفصیلی را نشان می‌دهد و فوکوس را بازمی‌گرداند", async () => {
  render(<ApplicationCard application={application} isDragging={false} onDragStart={jest.fn()} onDragEnd={jest.fn()} />);
  const trigger = screen.getByRole("button", { name: "مشاهده پرونده مریم احمدی" });
  await userEvent.click(trigger);
  const dialog = screen.getByRole("dialog", { name: "مریم احمدی" });
  expect(screen.getByText("82 از ۱۰۰")).toBeInTheDocument();
  expect(screen.getByText("نمودار رادار در دسترس نیست")).toBeInTheDocument();
  expect(screen.getByText("فهرست مهارت‌ها در دادهٔ دریافتی موجود نیست.")).toBeInTheDocument();
  fireEvent(dialog, new Event("cancel", { bubbles: true, cancelable: true }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
});

test("امتیاز غایب با صفر یا امتیاز ساختگی جایگزین نمی‌شود و بستن پرونده کار می‌کند", async () => {
  render(<ApplicationCard application={{ ...application, score_ai: null }} isDragging={false} onDragStart={jest.fn()} onDragEnd={jest.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: /مشاهده پرونده/ }));
  expect(screen.getByText("هنوز محاسبه نشده")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "بستن پرونده" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("پرونده از شناسهٔ درخواست، متن و مهارت واقعی را می‌گیرد و HTML را اجرا نمی‌کند",async()=>{
  jest.mocked(fetchApplicationDossier).mockResolvedValue({application_id:"a1",resume_id:"r1",raw_text:"رزومه <script>alert(1)</script>",parsed_data:null,agent_analysis:null,skill_analysis:{skills:["Python"],experience_entries:[{company:"شرکت نمونه",job_title:"توسعه‌دهنده",duration:"1400-1403",start_year:1400,is_valid:true}]}});
  render(<ApplicationCard application={application} isDragging={false} onDragStart={jest.fn()} onDragEnd={jest.fn()} />);
  await userEvent.click(screen.getByRole("button",{name:/مشاهده پرونده/}));
  expect(await screen.findByText("Python")).toBeInTheDocument();
  expect(screen.getByText("شرکت نمونه")).toBeInTheDocument();
  expect(screen.getByText("رزومه <script>alert(1)</script>")).toBeInTheDocument();
  expect(document.querySelector('dialog script')).toBeNull();
  expect(fetchApplicationDossier).toHaveBeenCalledWith("a1");
});

test("خطای دسترسی پرونده به‌صورت خطا نمایش داده می‌شود، نه پروندهٔ خالی موفق",async()=>{
  jest.mocked(fetchApplicationDossier).mockRejectedValue(new Error("forbidden"));
  render(<ApplicationCard application={application} isDragging={false} onDragStart={jest.fn()} onDragEnd={jest.fn()} />);
  await userEvent.click(screen.getByRole("button",{name:/مشاهده پرونده/}));
  expect(await screen.findByRole("alert")).toHaveTextContent("دریافت جزئیات پرونده ممکن نشد");
});
