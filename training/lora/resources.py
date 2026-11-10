"""محافظ منابع میزبان ویندوز پس از مشاهدهٔ کمبود حافظه و خطای pagefile."""

from __future__ import annotations

import ctypes
import os
import shutil
from contextlib import contextmanager
from pathlib import Path

GIB = 1024**3
START_COMMIT_RESERVE_GIB = 8
RUNTIME_COMMIT_RESERVE_GIB = 2
DISK_RESERVE_GIB = 2


def _execution_state(flags: int) -> int | None:
    if os.name != "nt":
        return None
    function = ctypes.WinDLL("kernel32").SetThreadExecutionState
    function.argtypes = [ctypes.c_uint32]
    function.restype = ctypes.c_uint32
    previous = function(flags)
    if not previous:
        raise OSError("درخواست جلوگیری از sleep خودکار پذیرفته نشد")
    return previous


@contextmanager
def keep_awake():
    """درخواست موقت همین thread؛ تنظیم برق، نمایشگر و رفتار بستن در لپ‌تاپ تغییر نمی‌کند."""
    continuous = 0x80000000
    previous = _execution_state(continuous | 0x00000001)
    try:
        yield
    finally:
        if previous is not None:
            _execution_state(previous | continuous)


def windows_memory() -> dict[str, int] | None:
    """مقادیر لحظه‌ای API رسمی؛ حافظهٔ commit با فضای آدرس مجازی اشتباه نمی‌شود."""
    if os.name != "nt":
        return None

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_uint32),
            ("load", ctypes.c_uint32),
            *[
                (name, ctypes.c_uint64)
                for name in (
                    "total_phys",
                    "avail_phys",
                    "total_commit",
                    "avail_commit",
                    "total_virtual",
                    "avail_virtual",
                    "avail_extended",
                )
            ],
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    function = ctypes.WinDLL("kernel32", use_last_error=True).GlobalMemoryStatusEx
    function.argtypes = [ctypes.POINTER(MemoryStatus)]
    function.restype = ctypes.c_int
    if not function(ctypes.byref(status)):
        raise ctypes.WinError(ctypes.get_last_error())
    return {"physical_available": status.avail_phys, "commit_available": status.avail_commit}


def check_resources(output_root: Path, *, starting: bool = False) -> dict:
    """قبل از بارگذاری و بین ریزگام‌ها حاشیهٔ آزاد کنترل می‌شود؛ تنظیم سیستم تغییر نمی‌کند."""
    location = output_root.resolve()
    while not location.exists():
        location = location.parent
    disk_free = shutil.disk_usage(location).free
    memory = windows_memory()
    report = {"disk_free_gib": round(disk_free / GIB, 2)}
    if memory is not None:
        report.update({f"{key}_gib": round(value / GIB, 2) for key, value in memory.items()})
        minimum = START_COMMIT_RESERVE_GIB if starting else RUNTIME_COMMIT_RESERVE_GIB
        if memory["commit_available"] < minimum * GIB:
            raise RuntimeError(
                f"توقف محافظ حافظه: commit آزاد {report['commit_available_gib']} GiB؛ "
                f"حداقل احتیاطی این مرحله {minimum} GiB است. آخرین checkpoint حفظ شده است."
            )
    if disk_free < DISK_RESERVE_GIB * GIB:
        raise RuntimeError(f"توقف محافظ دیسک: فقط {report['disk_free_gib']} GiB آزاد است؛ checkpoint قبلی حفظ شد.")
    return report
