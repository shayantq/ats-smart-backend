"""
موتور استخراج متن خام از فایل رزومه (Text Extraction Engine + OCR Fallback).

استراتژی دو مرحله‌ای برای PDF:
۱. تلاش برای خواندن مستقیم لایه‌ی متنی جاسازی‌شده در PDF با PyMuPDF (fitz) —
   سریع و بدون افت کیفیت؛ کافی برای اکثر رزومه‌های استاندارد (خروجی Word/PDF چاپی).
۲. اگر متن استخراج‌شده به‌طرز مشکوکی کوتاه/خالی بود (نشانه‌ی رزومه‌ی اسکن‌شده
   یا تصویری بدون لایه‌ی متنی)، هر صفحه به یک تصویر با کیفیت بالا رندر شده و
   با موتور OCR واقعی Tesseract (از طریق pytesseract) کاراکترهای متنی از
   روی همان تصویر استخراج می‌شوند.

فایل‌های DOCX مستقیم با python-docx خوانده می‌شوند — این فرمت XML-محور است
و همیشه لایه‌ی متنی دارد، پس نیازی به مسیر OCR ندارد.
"""

import hashlib
import pytesseract
from docx import Document

from app.core.config import settings

import io

if settings.TESSERACT_CMD_PATH:
    pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD_PATH


class UnreadableResumeFileError(Exception):
    """
    وقتی فایل رزومه به‌کلی خراب، رمزگذاری‌شده با گذرواژه، یا کاملاً ناخوانا باشد
    پرتاب می‌شود — تمایز دادنش از خطاهای غیرمنتظره باعث می‌شود لایه‌ی بالادستی
    (Worker) بتواند دقیقاً همین حالت مشخص را با پیام روشن لاگ کند.
    """


def extract_raw_text(file_bytes: bytes, filename: str, *, with_layout: bool = False):
    """
    نقطه‌ی ورود اصلی ماژول: از روی پسوند فایل، مسیر پردازش مناسب (PDF یا DOCX)
    را انتخاب و متن خام یکپارچه‌ی آن را برمی‌گرداند.

    در صورت ناخوانا/خراب بودن فایل، UnreadableResumeFileError پرتاب می‌شود
    (نه یک استثنای خام و نامشخص) تا فراخوان بتواند فرآیند را متوقف کرده و
    خطای مشخص و قابل‌فهم لاگ کند.
    """
    lowered_filename = filename.lower()

    if lowered_filename.endswith(".pdf"):
        result = _extract_from_pdf(file_bytes)
        return result if with_layout else result["raw_text"]

    if lowered_filename.endswith(".docx"):
        text = _extract_from_docx(file_bytes)
        return (
            dict(
                version=2,
                file_sha256=hashlib.sha256(file_bytes).hexdigest(),
                raw_text=text,
                pages=[],
                warnings=["docx_page_geometry_unavailable"],
                status="completed",
            )
            if with_layout
            else text
        )

    raise UnreadableResumeFileError("unsupported_format")


def _extract_from_pdf(file_bytes: bytes) -> dict:
    from app.core.pdf_layout import extract_pdf

    try:
        return extract_pdf(file_bytes)
    except (ValueError, RuntimeError) as error:
        code = (
            str(error)
            if str(error) in {"encrypted_pdf", "invalid_pdf", "no_readable_text"}
            else "pdf_extraction_failed"
        )
        raise UnreadableResumeFileError(code) from None


def _extract_from_docx(file_bytes: bytes) -> str:
    try:
        document = Document(io.BytesIO(file_bytes))
    except Exception as error:
        raise UnreadableResumeFileError(f"فایل DOCX خراب یا ناخوانا است: {error}") from error

    paragraphs = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]

    table_cells_text = [
        cell.text for table in document.tables for row in table.rows for cell in row.cells if cell.text.strip()
    ]

    combined_text = "\n".join([*paragraphs, *table_cells_text])

    if not combined_text.strip():
        raise UnreadableResumeFileError("فایل DOCX هیچ متن قابل‌استخراجی نداشت.")

    return _normalize_text(combined_text)


def _normalize_text(text: str) -> str:
    """
    متن استخراج‌شده را یکپارچه می‌کند: فاصله‌های نامتعارف/تکراری و خط‌های خالی
    اضافه حذف می‌شوند تا نتیجه‌ی نهایی یک متن تمیز و یکدست (بدون به‌هم‌ریختگی
    کاراکتری) باشد که مستقیماً در ستون raw_text ذخیره می‌شود.
    """
    normalized_lines = [" ".join(line.split()) for line in text.splitlines()]
    non_empty_lines = [line for line in normalized_lines if line]
    return "\n".join(non_empty_lines).strip()
