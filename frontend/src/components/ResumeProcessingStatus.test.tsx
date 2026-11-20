import {render, screen} from "@testing-library/react";
import ResumeProcessingStatus from "./ResumeProcessingStatus";

test.each([
  ["incomplete_generation", "پاسخ مدل کامل نشد"],
  ["context_limit_exceeded", "از ظرفیت فعلی مدل طولانی‌تر است"],
  ["engine_deadline_exceeded", "پردازش مدل بیش از حد طول کشید و متوقف شد"],
])("خطای مدل %s وضعیت ذخیره شدن متن را نشان می‌دهد", (error_code, message) => {
  render(<ResumeProcessingStatus state={{status:"failed",stage:"inference",attempt:1,error_code}} />);
  const alert = screen.getByRole("alert");
  expect(alert).toHaveTextContent(message);
  expect(alert).toHaveTextContent("متن استخراج‌شدهٔ رزومه ذخیره شد");
});

test("خطای تحلیل با خالی‌بودن رزومه یا موفقیت اشتباه نمی‌شود", () => {
  render(<ResumeProcessingStatus state={{status:"failed",stage:"inference",attempt:3,error_code:"inference_unavailable"}} />);
  expect(screen.getByRole("alert")).toHaveTextContent("تحلیل ناموفق بود");
  expect(screen.getByRole("alert")).toHaveTextContent("حفظ شده است");
  expect(screen.getByRole("alert")).toHaveTextContent("inference_unavailable");
  expect(screen.queryByText(/تحلیل ذخیره شد/)).not.toBeInTheDocument();
});

test("تغییر مرحلهٔ واقعی با پیام قابل خواندن برای صفحه‌خوان نمایش داده می‌شود", () => {
  const {rerender} = render(<ResumeProcessingStatus state={{status:"queued",stage:"queued",attempt:0}} />);
  expect(screen.getByRole("status")).toHaveTextContent("در صف تحلیل");
  rerender(<ResumeProcessingStatus state={{status:"processing",stage:"inference",attempt:1}} />);
  expect(screen.getByRole("status")).toHaveTextContent("تحلیل مدل");
  rerender(<ResumeProcessingStatus state={{status:"succeeded",stage:"complete",attempt:1}} />);
  expect(screen.getByRole("status")).toHaveTextContent("بررسی انسانی");
});

test("پیام محدودیت مدل ذخیره شدن اطلاعات را توضیح می‌دهد", () => {
  render(<ResumeProcessingStatus state={{status:"failed",stage:"inference",attempt:1,error_code:"input_exceeds_model_budget"}} />);
  expect(screen.getByRole("alert")).toHaveTextContent("برای ظرفیت فعلی تحلیل بیش از حد طولانی است");
  expect(screen.getByRole("alert")).toHaveTextContent("متن استخراج‌شده و داده‌های ساختاریافته ذخیره شدند");
});

test("ورودی ناقص مدل با ذخیره شدن دادهٔ مستند اعلام می‌شود", () => {
  render(<ResumeProcessingStatus state={{status:"succeeded",stage:"complete",attempt:1}} reviewReason="incomplete_input" />);
  const status = screen.getByRole("status");
  expect(status).toHaveTextContent("اطلاعات مستند ذخیره شد");
  expect(status).toHaveTextContent("شواهد ورودی مدل ناقص بود");
});

test("ناسازگاری تطبیق مدل نیازمند بازبینی نمایش داده می‌شود", () => {
  render(<ResumeProcessingStatus state={{status:"succeeded",stage:"complete",attempt:1}} reviewReason="matching_conflict" />);
  expect(screen.getByRole("status")).toHaveTextContent("نتیجهٔ مدل با شواهد شروط آگهی همخوانی ندارد");
});
