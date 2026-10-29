"""
تست واحد پارسر عبارت جستجوی AND/OR و نرمال‌سازی کلمات ایندکس کور رزومه (app/core/search_query.py).
"""

import pytest
from sqlalchemy import Text, column
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ARRAY

from app.core.crypto import blind_index_token
from app.core.search_query import parse_search_query, resume_blind_index_condition, resume_search_words


@pytest.mark.parametrize("raw", [None, "", "   ", "!!! --- ;;"])
def test_empty_or_meaningless_input_returns_nothing(raw):
    assert parse_search_query(raw) == []
    assert resume_blind_index_condition(raw, column("search_tokens", ARRAY(Text))) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Python", [("&", ["python"])]),
        ("Python AND Django", [("&", ["python"]), ("&", ["django"])]),
        ("React OR Vue", [("&", ["react"]), ("|", ["vue"])]),
        ("python and django", [("&", ["python"]), ("&", ["django"])]),  # عملگرها Case-Insensitive‌اند
        ("Python Django", [("&", ["python", "django"])]),  # بدون عملگر صریح → AND پیش‌فرض
        ("Python AND Django OR Flask", [("&", ["python"]), ("&", ["django"]), ("|", ["flask"])]),  # چپ به راست
        ("پایتون OR جنگو", [("&", ["پایتون"]), ("|", ["جنگو"])]),  # فارسی
    ],
)
def test_parses_terms_and_operators(raw, expected):
    assert parse_search_query(raw) == expected


def test_special_characters_split_words_like_the_resume_index():
    assert parse_search_query("C++ AND 'Node.js'") == [("&", ["c"]), ("&", ["node", "js"])]
    assert resume_search_words("Node.js، C# و ASP.NET — Django_REST") == [
        "node",
        "js",
        "c",
        "و",
        "asp",
        "net",
        "django",
        "rest",
    ]


def test_words_containing_operator_letters_are_not_operators():
    # «Andrew» و «Orlando» شامل AND/OR هستند ولی عملگر نیستند
    assert parse_search_query("Andrew Orlando") == [("&", ["andrew", "orlando"])]


def test_condition_contains_only_hashes_never_the_search_words():
    condition = resume_blind_index_condition("Python AND Django OR Flask", column("search_tokens", ARRAY(Text)))
    sql = str(condition.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    for word in ("python", "django", "flask"):
        assert word not in sql.lower()
        assert blind_index_token(word) in sql
    assert " OR " in sql and " AND " in sql and "@>" in sql
