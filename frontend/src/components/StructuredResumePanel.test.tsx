import {render,screen} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import StructuredResumePanel, {durationLabel} from "./StructuredResumePanel";

const sourceFact=(value:string,status="extracted")=>({value,status,evidence:[{text:value,page:1,bbox:[1,2,3,4]}]});

test("هویت فایل از حساب جدا می‌ماند و اختلاف نیازمند بررسی است",()=>{
  render(<StructuredResumePanel accountName="account-alias" value={{version:"resume-structured-v1",identity:{name:sourceFact("MIRA HART")},activities:[],contacts:[]}} />);
  expect(screen.getByText("MIRA HART")).toBeInTheDocument();
  expect(screen.getByText("account-alias")).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("حساب تغییر نکرده است");
});
test("شاهد با کیبورد باز می‌شود و HTML رزومه اجرا نمی‌شود",async()=>{
  render(<StructuredResumePanel accountName="MIRA HART" value={{version:"resume-structured-v1",identity:{name:sourceFact("MIRA HART")},activities:[],contacts:[sourceFact("<script>bad()</script>","ambiguous")]}} />);
  await userEvent.click(screen.getByText("شاهد تلفن"));
  expect(screen.getAllByText("<script>bad()</script>").length).toBeGreaterThan(0);
  expect(document.querySelector("script")).toBeNull();
  expect(screen.getAllByText("(نیازمند بررسی)").length).toBeGreaterThan(0);
});
test("سطح زبان و گواهی‌نامه تأیید اصالت تلقی نمی‌شوند",()=>{
  render(<StructuredResumePanel accountName="MIRA HART" value={{version:"resume-structured-v1",identity:{},activities:[],languages:[{fields:{language:sourceFact("Spanish"),level:sourceFact("Advanced","attributed")}}],certifications:[{fields:{title:sourceFact("Example Certification")},expiry_status:"expired_claim"}]}} />);
  expect(screen.getByText("(ادعای رزومه)")).toBeInTheDocument();
  expect(screen.getByText("پیشرفته")).toBeInTheDocument();
  expect(screen.getByText(/اصالت گواهی بررسی نشده/)).toBeInTheDocument();
});

test("مدت کوتاه ماهانه و پیوند پروژه با پروفایل متفاوت نمایش داده می‌شوند",()=>{
  expect(durationLabel(0.296,0.378)).toBe('حدود ۳ تا ۵ ماه');
  render(<StructuredResumePanel accountName="fixture" value={{version:'resume-structured-v1',identity:{},links:[sourceFact('github.com/example'),sourceFact('github.com/example/tool')]}}/>);
  expect(screen.getByRole('link',{name:'بازکردن پروفایل گیت‌هاب'})).toHaveAttribute('href','https://github.com/example');
  expect(screen.getByRole('link',{name:'بازکردن مخزن پروژه در گیت‌هاب'})).toHaveAttribute('rel','noopener noreferrer');
});
