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

import io
import logging

import fitz  # PyMuPDF
import pytesseract
from docx import Document
from PIL import Image

from app.core.config import settings

logger = logging.getLogger("ats_smart.text_extraction")

# اگر متن استخراج‌شده‌ی مستقیم یک PDF کمتر از این تعداد کاراکتر باشد،
# فرض می‌شود سند اسکن‌شده/تصویری است و باید به مسیر OCR هدایت شود.
_MIN_TEXT_LAYER_CHARS = 40

# کیفیت رندر صفحه به تصویر پیش از OCR (DPI بالاتر = دقت بهتر ولی کندتر)
_OCR_RENDER_DPI = 300

if settings.TESSERACT_CMD_PATH:
    pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD_PATH


class UnreadableResumeFileError(Exception):
    """
    وقتی فایل رزومه به‌کلی خراب، رمزگذاری‌شده با گذرواژه، یا کاملاً ناخوانا باشد
    پرتاب می‌شود — تمایز دادنش از خطاهای غیرمنتظره باعث می‌شود لایه‌ی بالادستی
    (Worker) بتواند دقیقاً همین حالت مشخص را با پیام روشن لاگ کند.
    """


def extract_raw_text(file_bytes: bytes, filename: str) -> str:
    """
    نقطه‌ی ورود اصلی ماژول: از روی پسوند فایل، مسیر پردازش مناسب (PDF یا DOCX)
    را انتخاب و متن خام یکپارچه‌ی آن را برمی‌گرداند.

    در صورت ناخوانا/خراب بودن فایل، UnreadableResumeFileError پرتاب می‌شود
    (نه یک استثنای خام و نامشخص) تا فراخوان بتواند فرآیند را متوقف کرده و
    خطای مشخص و قابل‌فهم لاگ کند.
    """
    lowered_filename = filename.lower()

    if lowered_filename.endswith(".pdf"):
        return _extract_from_pdf(file_bytes)

    if lowered_filename.endswith(".docx"):
        return _extract_from_docx(file_bytes)

    raise UnreadableResumeFileError(f"فرمت فایل پشتیبانی نمی‌شود: {filename}")


def _extract_from_pdf(file_bytes: bytes) -> str:
    try:
        document = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as error:
        raise UnreadableResumeFileError(f"فایل PDF خراب یا ناخوانا است: {error}") from error

    if document.needs_pass:
        document.close()
        raise UnreadableResumeFileError("فایل PDF با گذرواژه قفل شده و بدون رمز عبور قابل باز شدن نیست.")

    try:
        direct_text_pages = [page.get_text().strip() for page in document]
        direct_text = "\n".join(page_text for page_text in direct_text_pages if page_text)

        if len(direct_text) >= _MIN_TEXT_LAYER_CHARS:
            return _normalize_text(direct_text)

        # لایه‌ی متنی ناکافی بود -> احتمالاً رزومه‌ی اسکن‌شده/تصویری؛ مسیر OCR فعال می‌شود
        logger.info("لایه‌ی متنی PDF ناکافی بود؛ مسیر OCR (Tesseract) فعال شد.")
        ocr_text_pages: list[str] = []
        for page in document:
            pixmap = page.get_pixmap(dpi=_OCR_RENDER_DPI)
            image = Image.open(io.BytesIO(pixmap.tobytes("png")))
            page_ocr_text = pytesseract.image_to_string(image, lang=settings.OCR_LANGUAGES)
            ocr_text_pages.append(page_ocr_text.strip())

        ocr_text = "\n".join(text for text in ocr_text_pages if text)
        if not ocr_text.strip():
            raise UnreadableResumeFileError("نه لایه‌ی متنی و نه OCR توانستند متنی از فایل PDF استخراج کنند.")

        return _normalize_text(ocr_text)
    finally:
        document.close()


def _extract_from_docx(file_bytes: bytes) -> str:
    try:
        document = Document(io.BytesIO(file_bytes))
    except Exception as error:
        raise UnreadableResumeFileError(f"فایل DOCX خراب یا ناخوانا است: {error}") from error

    paragraphs = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]

    table_cells_text = [
        cell.text
        for table in document.tables
        for row in table.rows
        for cell in row.cells
        if cell.text.strip()
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
