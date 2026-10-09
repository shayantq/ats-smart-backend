"""تست واحد پارسر عبارت جستجوی AND/OR (app/core/search_query.py::build_resume_search_tsquery)."""

import pytest

from app.core.search_query import build_resume_search_tsquery


@pytest.mark.parametrize("raw", [None, "", "   ", "!!! --- ;;"])
def test_empty_or_meaningless_input_returns_none(raw):
    assert build_resume_search_tsquery(raw) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Python", "Python"),
        ("Python AND Django", "(Python & Django)"),
        ("React OR Vue", "(React | Vue)"),
        ("python and django", "(python & django)"),  # عملگرها Case-Insensitive‌اند
        ("Python Django", "(Python & Django)"),  # بدون عملگر صریح → AND پیش‌فرض
        ("Python AND Django OR Flask", "((Python & Django) | Flask)"),  # چپ به راست، با پرانتزبندی صریح
        ("پایتون OR جنگو", "(پایتون | جنگو)"),  # فارسی
    ],
)
def test_builds_valid_tsquery(raw, expected):
    assert build_resume_search_tsquery(raw) == expected


def test_special_characters_are_stripped_to_prevent_tsquery_syntax_errors():
    assert build_resume_search_tsquery("C++ AND 'Node.js'") == "(C & (Node & js))"


def test_words_containing_operator_letters_are_not_operators():
    # «Andrew» و «Orlando» شامل AND/OR هستند ولی عملگر نیستند
    assert build_resume_search_tsquery("Andrew Orlando") == "(Andrew & Orlando)"
