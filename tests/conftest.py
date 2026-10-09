"""
پیکربندی مشترک کل مجموعه‌ی تست‌ها.

ساختار (هرم تست):
    tests/unit/          تست‌های واحد — توابع و منطق‌های ایزوله، سریع، بدون دیتابیس/شبکه
    tests/integration/   تست‌های یکپارچه‌سازی — API واقعی (HTTPX AsyncClient) + یک دیتابیس
                         PostgreSQL موقت و جدا (بنگرید tests/integration/conftest.py)

هر تست بر اساس پوشه‌اش خودکار marker می‌گیرد تا بتوان هر لایه را جدا اجرا کرد:
    pytest -m unit
    pytest -m integration
"""

from pathlib import Path

import pytest

_TESTS_ROOT = Path(__file__).resolve().parent


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        layer = Path(item.fspath).resolve().relative_to(_TESTS_ROOT).parts[0]
        if layer in ("unit", "integration"):
            item.add_marker(getattr(pytest.mark, layer))
