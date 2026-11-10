"""دانلود چندبخشی ادامه‌پذیر با نسخه‌ی ثابت و بررسی اندازه و هش فایل‌های مدل پایه."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from pathlib import Path

import httpx

from training.lora.config import MODEL_ENV_FILE, load_env_file

REPO_ENV = "LORA_BASE_MODEL_REPO"
DEFAULT_ATTEMPTS = 3
CHUNK_BYTES = 4 * 1024**2
SUFFIXES = (".json", ".safetensors", ".txt", ".model", ".jinja")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verified_file(path: Path, size: int, sha256: str | None, blob_id: str | None = None) -> bool:
    if not path.is_file() or path.stat().st_size != size:
        return False
    if sha256:
        return sha256_of(path) == sha256
    if blob_id:
        digest = hashlib.sha1(f"blob {size}\0".encode())
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest() == blob_id
    raise ValueError("هش مورد انتظار فایل مشخص نیست")


def _download_chunk(client, url: str, part: Path, start: int, end: int, attempts: int) -> None:
    size = end - start + 1
    for attempt in range(attempts):
        offset = part.stat().st_size if part.exists() else 0
        if offset == size:
            return
        if offset > size:
            raise ValueError("اندازه‌ی بخش موقت از محدوده بیشتر است")
        try:
            with client.stream("GET", url, headers={"Range": f"bytes={start + offset}-{end}"}) as response:
                response.raise_for_status()
                expected = f"bytes {start + offset}-{end}/"
                if response.status_code != 206 or not response.headers.get("content-range", "").startswith(expected):
                    raise ValueError("سرور محدوده‌ی درخواستی را رعایت نکرد")
                with part.open("ab") as handle:
                    for chunk in response.iter_bytes(65536):
                        if handle.tell() + len(chunk) > size:
                            raise ValueError("داده‌ی پاسخ از اندازه‌ی بخش بیشتر است")
                        handle.write(chunk)
            if part.stat().st_size != size:
                raise OSError("پاسخ دانلود ناقص است")
            return
        except (httpx.HTTPError, OSError) as error:
            print(
                json.dumps(
                    {
                        "retrying_part": part.name,
                        "attempt": attempt + 1,
                        "error": type(error).__name__,
                        "status": error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None,
                    }
                ),
                flush=True,
            )
            if attempt + 1 == attempts:
                raise RuntimeError("دانلود بخش پس از تلاش‌های محدود کامل نشد") from None
            time.sleep(2 ** (attempt + 1))


def _progress(destination: Path, parts: list[Path], size: int, original: int, started: float) -> None:
    current = sum(part.stat().st_size for part in parts if part.exists())
    speed = (current - original) / max(time.monotonic() - started, 0.01)
    print(
        json.dumps(
            {
                "file": destination.name,
                "downloaded_mib": round(current / 1024**2, 1),
                "total_mib": round(size / 1024**2, 1),
                "kib_per_second": round(speed / 1024, 1),
                "eta_hours": round((size - current) / speed / 3600, 2) if speed else None,
            }
        ),
        flush=True,
    )


def download_file(
    url: str,
    destination: Path,
    size: int,
    sha256: str | None,
    *,
    blob_id: str | None = None,
    workers: int = 8,
    attempts: int = DEFAULT_ATTEMPTS,
    chunk_bytes: int = CHUNK_BYTES,
) -> None:
    """بخش‌های کامل حفظ می‌شوند؛ فایل نهایی فقط پس از تأیید هش جایگزین می‌شود."""
    if size <= 0 or workers <= 0 or attempts <= 0 or chunk_bytes <= 0 or not (sha256 or blob_id):
        raise ValueError("اندازه، هش یا تنظیمات دانلود نامعتبر است")
    if verified_file(destination, size, sha256, blob_id):
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    parts_dir = destination.parent / ".parts" / (sha256 or blob_id)
    parts_dir.mkdir(parents=True, exist_ok=True)
    ranges = [(start, min(size - 1, start + chunk_bytes - 1)) for start in range(0, size, chunk_bytes)]
    parts = [parts_dir / f"{index:06}.part" for index in range(len(ranges))]
    original = sum(part.stat().st_size for part in parts if part.exists())
    required = 2 * size - original + 512 * 1024**2
    if shutil.disk_usage(destination.parent).free < required:
        raise OSError("فضای آزاد برای بخش‌ها و مونتاژ تأییدشده‌ی فایل کافی نیست")
    started = time.monotonic()
    limits = httpx.Limits(max_connections=workers, max_keepalive_connections=workers)
    with httpx.Client(timeout=httpx.Timeout(30, connect=15), limits=limits, follow_redirects=True) as client:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            pending = {
                executor.submit(_download_chunk, client, url, part, start, end, attempts)
                for part, (start, end) in zip(parts, ranges)
            }
            while pending:
                done, pending = wait(pending, timeout=15, return_when=FIRST_EXCEPTION)
                for future in done:
                    if future.exception() is not None:
                        for waiting in pending:
                            waiting.cancel()
                        future.result()
                _progress(destination, parts, size, original, started)
    assembled = destination.with_suffix(destination.suffix + ".assembling")
    with assembled.open("wb") as output:
        for part in parts:
            with part.open("rb") as source:
                shutil.copyfileobj(source, output)
    if not verified_file(assembled, size, sha256, blob_id):
        raise ValueError("هش فایل دانلودشده نادرست است؛ فایل نهایی جایگزین نشد")
    assembled.replace(destination)
    # فقط بخش‌های ساخته‌شده‌ی همین فایل، پس از تأیید مستقل هش، پاک می‌شوند.
    for part in parts:
        part.unlink()


def download(repo_id: str, out_dir: Path, attempts: int = DEFAULT_ATTEMPTS, workers: int = 8) -> Path:
    from huggingface_hub import HfApi, hf_hub_url

    info = HfApi().model_info(repo_id, files_metadata=True, timeout=20)
    files = [s for s in info.siblings if "/" not in s.rfilename and s.rfilename.endswith(SUFFIXES)]
    if not any(s.rfilename.endswith(".safetensors") for s in files):
        raise ValueError("وزن قابل آموزش در مخزن مدل پیدا نشد")
    out_dir.mkdir(parents=True, exist_ok=True)
    # تنظیمات کوچک اول می‌آیند؛ تمام فایل‌ها از یک commit ثابت دریافت می‌شوند.
    for entry in sorted(files, key=lambda item: item.size or 0):
        if Path(entry.rfilename).name != entry.rfilename:
            raise ValueError("نام فایل مخزن نامعتبر است")
        download_file(
            hf_hub_url(repo_id, entry.rfilename, revision=info.sha),
            out_dir / entry.rfilename,
            entry.size,
            entry.lfs.sha256 if entry.lfs else None,
            blob_id=entry.blob_id,
            workers=workers,
            attempts=attempts,
        )
    manifest = {"revision": info.sha, "files": {s.rfilename: s.size for s in files}, "verified": True}
    (out_dir / "download_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return out_dir


def tokenizer_report(model_dir: Path, reference: Path) -> dict:
    model_tokenizer = model_dir / "tokenizer.json"
    report = {"model_tokenizer": model_tokenizer.exists(), "reference_tokenizer": reference.exists()}
    if model_tokenizer.exists() and reference.exists():
        report.update(model_sha256=sha256_of(model_tokenizer), reference_sha256=sha256_of(reference))
        report["match"] = report["model_sha256"] == report["reference_sha256"]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m training.lora.download")
    parser.add_argument("--repo-id", default=os.environ.get(REPO_ENV) or load_env_file(MODEL_ENV_FILE).get(REPO_ENV))
    parser.add_argument("--out", type=Path, default=Path("models/base-model"))
    parser.add_argument("--reference-tokenizer", type=Path, default=Path("data/tokenizer/tokenizer.json"))
    parser.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)
    if not args.repo_id or args.attempts <= 0 or args.workers <= 0:
        parser.error("شناسه‌ی مدل، تعداد تلاش و تعداد اتصال معتبر لازم است")
    try:
        model_dir = download(args.repo_id, args.out, args.attempts, args.workers)
        report = tokenizer_report(model_dir, args.reference_tokenizer)
        report["weights_mib"] = round(sum(p.stat().st_size for p in model_dir.glob("*.safetensors")) / 1024**2, 1)
        print(json.dumps(report, indent=2), flush=True)
        return 0 if report.get("match") and report["weights_mib"] > 0 else 1
    except Exception as error:  # noqa: BLE001 — URL امضاشده یا اطلاعات احراز هویت هرگز چاپ نشوند
        print(json.dumps({"download_failed": type(error).__name__, "resumable": True}), flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
