/** هشدار استخراج؛ confidence موتور OCR به‌عنوان احتمال صحت پرونده نمایش داده نمی‌شود. */
export default function ExtractionNotice({value}: {value:unknown}) {
  if (!value || typeof value !== "object") return null;
  const extraction=value as Record<string,unknown>;
  const partial=extraction.status === "partial";
  const warnings=Array.isArray(extraction.warnings) ? extraction.warnings : [];
  if (!partial && !warnings.includes("low_ocr_confidence")) return null;
  return <p role="status" className="my-3 border-s-2 border-amber-500 ps-3 text-caption text-amber-800 dark:text-amber-300">
    {partial ? "استخراج بعضی قسمت‌ها کامل نشد؛ پیش از تصمیم‌گیری، فایل اصلی رزومه را بررسی کنید." : "خوانایی برخی بخش‌های اسکن پایین است؛ متن استخراج‌شده را با فایل اصلی تطبیق دهید."}
  </p>;
}
