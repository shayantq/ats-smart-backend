"""دریافت محدوده‌ای واقعی روی HTTP محلی: ادامه‌ی فایل ناقص و رد هش یا پاسخ نادرست."""

import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from training.lora.download import download_file, verified_file


@pytest.fixture
def range_server():
    payload = bytes(range(256)) * 80
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            start, end = map(int, self.headers["Range"].removeprefix("bytes=").split("-"))
            requests.append((start, end))
            self.send_response(206 if self.path == "/range" else 200)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(payload)}")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            self.wfile.write(payload[start : end + 1])

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", payload, requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_range_download_resumes_partial_chunks_and_verifies_before_replacement(tmp_path, range_server):
    url, payload, requests = range_server
    digest = hashlib.sha256(payload).hexdigest()
    destination = tmp_path / "model.safetensors"
    parts = tmp_path / ".parts" / digest
    parts.mkdir(parents=True)
    (parts / "000000.part").write_bytes(payload[:1024])
    (parts / "000001.part").write_bytes(payload[4096:8192])
    download_file(f"{url}/range", destination, len(payload), digest, chunk_bytes=4096, workers=2)
    assert destination.read_bytes() == payload
    assert (1024, 4095) in requests
    assert (4096, 8191) not in requests
    assert not list(parts.glob("*.part"))
    before = len(requests)
    download_file(f"{url}/range", destination, len(payload), digest, chunk_bytes=4096)
    assert len(requests) == before  # فایل تأییدشده دوباره دانلود نمی‌شود


def test_wrong_checksum_preserves_existing_destination(tmp_path, range_server):
    url, payload, _ = range_server
    destination = tmp_path / "model.safetensors"
    destination.write_bytes(b"previous file")
    with pytest.raises(ValueError, match="هش"):
        download_file(f"{url}/range", destination, len(payload), "0" * 64, chunk_bytes=4096)
    assert destination.read_bytes() == b"previous file"


def test_server_ignoring_range_is_rejected(tmp_path, range_server):
    url, payload, _ = range_server
    with pytest.raises(ValueError, match="محدوده"):
        download_file(f"{url}/ignore", tmp_path / "model", len(payload), hashlib.sha256(payload).hexdigest())
    assert not (tmp_path / "model").exists()


def test_git_blob_checksum_covers_the_header_and_contents(tmp_path):
    path = tmp_path / "config.json"
    payload = b'{"hidden_size":32}'
    path.write_bytes(payload)
    blob = hashlib.sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest()
    assert verified_file(path, len(payload), None, blob)
    path.write_bytes(b"x" * len(payload))
    assert not verified_file(path, len(payload), None, blob)
