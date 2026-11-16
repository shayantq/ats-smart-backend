"""پیش‌نمایش با سند ساختگی؛ هندسهٔ رندر باید با شاهد هم‌نسخه باشد."""

import base64
import hashlib

import fitz
import pytest

from app.core.document_preview import PreviewError, render_document_page


def test_render_matches_unrotated_crop_geometry_and_is_bounded(tmp_path, monkeypatch):
    doc = fitz.open()
    page = doc.new_page(width=600, height=900)
    page.insert_text((30, 60), "Synthetic resume")
    page.set_cropbox(fitz.Rect(10, 20, 590, 880))
    page.set_rotation(90)
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(doc.tobytes())
    doc.close()
    monkeypatch.setattr("app.core.document_preview.resolve_local_media_path", lambda _: path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result = render_document_page("local", 1, digest)
    assert result["width"] == 580 and result["height"] == 860
    assert result["file_sha256"] == digest and result["pages"] == 1
    image = fitz.Pixmap(base64.b64decode(result["image"].split(",", 1)[1]))
    assert image.width <= 960 and image.height <= 1440
    with pytest.raises(PreviewError, match="") as error:
        render_document_page("local", 1, "0" * 64)
    assert error.value.code == "document_evidence_version_mismatch"
    with pytest.raises(PreviewError) as error:
        render_document_page("local", 2)
    assert error.value.status == 404


def test_external_storage_and_corrupt_files_do_not_trigger_fetch(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.document_preview.resolve_local_media_path", lambda _: None)
    with pytest.raises(PreviewError) as error:
        render_document_page("http://untrusted.invalid/private", 1)
    assert error.value.status == 501
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(b"broken pdf")
    monkeypatch.setattr("app.core.document_preview.resolve_local_media_path", lambda _: path)
    with pytest.raises(PreviewError) as error:
        render_document_page("local", 1)
    assert error.value.code == "document_unreadable"
