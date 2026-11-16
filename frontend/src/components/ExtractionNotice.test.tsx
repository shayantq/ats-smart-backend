import {render,screen} from "@testing-library/react";
import ExtractionNotice from "./ExtractionNotice";

test("موفقیت ذخیره‌سازی، هشدار استخراج ناقص را پنهان نمی‌کند",()=>{
  render(<ExtractionNotice value={{status:"partial",warnings:["ocr_region_failed"]}} />);
  expect(screen.getByRole("status")).toHaveTextContent("فایل اصلی رزومه را بررسی کنید");
});
test("خوانایی OCR بدون امتیاز اعتماد ساختگی توضیح داده می‌شود",()=>{
  render(<ExtractionNotice value={{status:"completed",warnings:["low_ocr_confidence"]}} />);
  expect(screen.getByRole("status")).toHaveTextContent("خوانایی");
});
test("سند قدیمی یا سالم هشدار ساختگی ندارد",()=>{
  const {rerender}=render(<ExtractionNotice value={null} />);
  expect(screen.queryByRole("status")).toBeNull();
  rerender(<ExtractionNotice value={{status:"completed",warnings:[]}} />);
  expect(screen.queryByRole("status")).toBeNull();
});
