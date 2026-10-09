"""تست واحد ماشین وضعیت صلب بورد کانبان (app/core/state_machine.py)."""

import pytest

from app.core.state_machine import (
    FUNNEL_STAGES,
    TERMINAL_STATUSES,
    ApplicationStatus,
    get_allowed_next_statuses,
    is_transition_allowed,
)

LINEAR_PATH = ["Draft", "Applied", "Screening", "Technical Interview", "HR Interview", "Offer", "Accepted", "Hired"]


@pytest.mark.parametrize(("current", "following"), list(zip(LINEAR_PATH, LINEAR_PATH[1:])))
def test_moving_to_the_immediate_next_stage_is_allowed(current, following):
    assert is_transition_allowed(current, following)


@pytest.mark.parametrize("current", LINEAR_PATH[:-1])
def test_rejection_is_allowed_from_every_non_terminal_stage(current):
    assert is_transition_allowed(current, "Rejected")


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("Screening", "Hired"),  # پرش از روی چند مرحله
        ("Draft", "Screening"),  # پرش از روی یک مرحله
        ("Offer", "HR Interview"),  # حرکت رو به عقب
        ("Applied", "Applied"),  # ماندن در همان وضعیت
    ],
)
def test_skipping_or_going_back_is_forbidden(current, target):
    assert not is_transition_allowed(current, target)


@pytest.mark.parametrize("terminal", sorted(TERMINAL_STATUSES))
def test_terminal_statuses_have_no_way_out(terminal):
    assert get_allowed_next_statuses(terminal) == frozenset()


def test_unknown_status_allows_nothing():
    assert get_allowed_next_statuses("Archived") == frozenset()
    assert not is_transition_allowed("Archived", "Applied")


def test_each_stage_has_exactly_two_exits():
    assert get_allowed_next_statuses("Offer") == {"Accepted", "Rejected"}


def test_funnel_stages_follow_the_linear_path_without_draft_and_rejected():
    assert FUNNEL_STAGES == LINEAR_PATH[1:]
    assert "Rejected" not in FUNNEL_STAGES
    assert {status.value for status in ApplicationStatus} == set(LINEAR_PATH) | {"Rejected"}
