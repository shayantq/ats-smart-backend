"""رندر محدود و بدون cache دیسکی؛ هیچ نشانی خارجی از کاربر واکشی نمی‌شود."""

import base64
import hashlib

import fitz

from app.core.storage import resolve_local_media_path


class PreviewError(Exception):
    def __init__(self, code, status=422):
        self.code, self.status = code, status


def render_document_page(file_url, number, expected_sha256=None):
    path = resolve_local_media_path(file_url)
    if path is None:
        raise PreviewError("document_storage_preview_unavailable", 501)
    if path.suffix.lower() != ".pdf":
        raise PreviewError("document_is_not_pdf", 415)
    try:
        if not path.is_file():
            raise PreviewError("document_missing", 404)
        with path.open("rb") as stream:
            content = stream.read(10 * 1024 * 1024 + 1)
    except OSError:
        raise PreviewError("document_unavailable", 503) from None
    if len(content) > 10 * 1024 * 1024:
        raise PreviewError("document_too_large", 413)
    digest = hashlib.sha256(content).hexdigest()
    if expected_sha256 and digest != expected_sha256:
        raise PreviewError("document_evidence_version_mismatch", 409)
    try:
        with fitz.open(stream=content, filetype="pdf") as doc:
            if doc.needs_pass:
                raise PreviewError("document_encrypted")
            if not 1 <= number <= len(doc):
                raise PreviewError("document_page_missing", 404)
            page = doc[number - 1]
            page.set_rotation(0)
            width, height = page.rect.width, page.rect.height
            if width <= 0 or height <= 0:
                raise PreviewError("document_invalid_page")
            zoom = min(960 / width, 1440 / height, 2)
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            return dict(
                page=number,
                pages=len(doc),
                width=width,
                height=height,
                coordinate_space="unrotated_crop_points",
                file_sha256=digest,
                image="data:image/png;base64," + base64.b64encode(pix.tobytes("png")).decode("ascii"),
            )
    except PreviewError:
        raise
    except (ValueError, RuntimeError):
        raise PreviewError("document_unreadable") from None
