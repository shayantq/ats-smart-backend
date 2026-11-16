"""مولد منبع ساختگی؛ نام‌ها و تماس‌ها متعلق به اشخاص واقعی نیستند."""

import html
from pathlib import Path

import fitz


def render(case, directory, font_dir):
    target = Path(directory) / (case.id + ".pdf")
    target.parent.mkdir(parents=True, exist_ok=True)
    if case.input_type == "corrupt":
        target.write_bytes(b"synthetic-corrupt-pdf")
        return target
    doc = fitz.open()
    for index, lines in enumerate(case.pages):
        page = doc.new_page(width=595, height=842)
        groups = [lines]
        if case.layout in {"columns", "table"}:
            middle = len(lines) // 2
            groups = [lines[:middle], lines[middle:]]
        for col, group in enumerate(groups):
            width = 535 / len(groups)
            box = fitz.Rect(30 + col * width, 35, 30 + (col + 1) * width - 12, 805)
            rows = "".join(f'<div dir="auto">{html.escape(line) or "&nbsp;"}</div>' for line in group)
            if case.layout == "table":
                rows = '<table border="1"><tr><td>' + rows + "</td></tr></table>"
            # فونت داخلی MuPDF با fallback فارسی؛ فایل WOFF2 مرورگر در FreeType این تصویر پشتیبانی نمی‌شود.
            css = "body{font-family:sans-serif;font-size:11px;line-height:1.5}"
            spare, scale = page.insert_htmlbox(box, rows, css=css, archive=fitz.Archive(str(font_dir)), scale_low=1)
            if spare < 0 or scale != 1:
                raise ValueError("fixture_overflow")
        if case.input_type == "image" or (case.input_type == "hybrid" and index % 2 == 1):
            image = page.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png")
            doc.delete_page(index)
            page = doc.new_page(pno=index, width=595, height=842)
            page.insert_image(page.rect, stream=image)
    doc.save(target, no_new_id=True)
    doc.close()
    return target
