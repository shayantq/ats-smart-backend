import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders as render } from "../test/renderWithProviders";
import CandidatePortal from "./CandidatePortal";
import * as api from "../services/candidatesApi";
import { fetchActiveJobs } from "../services/jobsApi";

jest.mock("../services/candidatesApi");
jest.mock("../services/jobsApi");
const profile = { candidate_id: "c", email: "candidate@example.test", first_name: "مریم", last_name: "احمدی", phone: null, skills: ["Python"] };
beforeEach(() => {
  jest.clearAllMocks();
  jest.mocked(api.fetchMyProfile).mockResolvedValue(profile);
  jest.mocked(api.fetchMyApplications).mockResolvedValue([]);
  jest.mocked(api.fetchMyOffers).mockResolvedValue([]);
  jest.mocked(fetchActiveJobs).mockResolvedValue([]);
  jest.mocked(api.updateMyProfile).mockResolvedValue(profile);
});

test("ویرایش مشخصات و مهارت و تأیید دومرحله‌ای حذف حفظ می‌شوند", async () => {
  render(<CandidatePortal />);
  const name = await screen.findByDisplayValue("مریم");
  fireEvent.change(name, { target: { value: "سارا" } });
  const skills = screen.getByRole("textbox", { name: "افزودن مهارت" });
  await userEvent.type(skills, "React{Enter}");
  await userEvent.click(screen.getByRole("button", { name: "ذخیره‌ی تغییرات" }));
  await waitFor(() => expect(api.updateMyProfile).toHaveBeenCalledWith({ first_name: "سارا", last_name: "احمدی", phone: "", skills: ["Python", "React"] }, expect.anything()));
  await userEvent.click(screen.getByRole("button", { name: "حذف حساب" }));
  expect(api.deleteMyAccount).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "انصراف" }));
  expect(screen.queryByRole("button", { name: "بله، حسابم برای همیشه حذف شود" })).not.toBeInTheDocument();
});

test("تب‌ها با جهت RTL و Home و End کار می‌کنند و حالت خالی نمایش داده می‌شود", async () => {
  render(<CandidatePortal />);
  await screen.findByDisplayValue("مریم");
  const tabs = screen.getAllByRole("tab");
  tabs[0].focus();
  await userEvent.keyboard("{ArrowLeft}");
  expect(tabs[1]).toHaveFocus();
  expect(await screen.findByText("هنوز برای هیچ آگهی‌ای درخواست نداده‌ای.")).toBeInTheDocument();
  await userEvent.keyboard("{End}");
  expect(tabs[2]).toHaveAttribute("aria-selected", "true");
  expect(await screen.findByText("فعلاً هیچ پیشنهاد شغلی فعالی نداری.")).toBeInTheDocument();
  await userEvent.keyboard("{Home}");
  expect(tabs[0]).toHaveFocus();
});

test.each([['قبول پیشنهاد', 'accept'], ['رد پیشنهاد', 'reject']] as const)("پاسخ %s قرارداد قبلی را حفظ می‌کند", async (label, decision) => {
  jest.mocked(api.fetchMyOffers).mockResolvedValue([{application_id:"a",job_id:"j",job_title:"Python",company_name:"شرکت نمونه",updated_at:"2026-11-14T10:00:00Z"}]);
  jest.mocked(api.respondToOffer).mockResolvedValue({application_id:"a",new_status:decision==='accept'?'Accepted':'Rejected',message:"ثبت شد"});
  render(<CandidatePortal />);
  await userEvent.click(screen.getByRole("tab", { name: "صندوق پیشنهادها" }));
  await userEvent.click(await screen.findByRole("button", { name: label }));
  await waitFor(() => expect(api.respondToOffer).toHaveBeenCalledWith("a", decision));
});

test("فایل نامجاز ارسال نمی‌شود و انتخاب فایل با دکمهٔ قابل دسترس انجام می‌شود", async () => {
  render(<CandidatePortal />);
  await screen.findByDisplayValue("مریم");
  expect(screen.getByRole("button", { name: "انتخاب فایل رزومه" })).toBeEnabled();
  fireEvent.change(screen.getByLabelText("فایل رزومه"), {target:{files:[new File(["x"],"bad.exe")]}});
  expect(await screen.findByText("فقط فایل PDF یا DOCX پذیرفته می‌شود.")).toBeInTheDocument();
  expect(api.uploadResume).not.toHaveBeenCalled();
});

test("رزومه با همان فایل و آگهی ارسال می‌شود و پیام دریافت سرور نمایش داده می‌شود", async () => {
  jest.mocked(fetchActiveJobs).mockResolvedValue([{job_id:"j",title:"Python",department:"فنی",description:"نمونه",skills_required:[],salary_range:null,status:"Active",created_by:"hr",created_at:null}]);
  jest.mocked(api.uploadResume).mockResolvedValue({application_id:"a",status:"Applied",message:"برای تحلیل پذیرفته شد"});
  render(<CandidatePortal />);
  await screen.findByRole("option", {name:"Python"});
  await userEvent.selectOptions(screen.getByRole("combobox"), "j");
  const file = new File(["resume"], "resume.pdf", {type:"application/pdf"});
  fireEvent.change(screen.getByLabelText("فایل رزومه"), {target:{files:[file]}});
  await userEvent.click(screen.getByRole("button", {name:"ارسال رزومه"}));
  await waitFor(() => expect(api.uploadResume).toHaveBeenCalledWith({jobId:"j",file},expect.anything()));
  expect(await screen.findByText("برای تحلیل پذیرفته شد")).toBeInTheDocument();
});
