import {render, screen} from "@testing-library/react";
import ResumeProcessingStatus from "./ResumeProcessingStatus";

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
