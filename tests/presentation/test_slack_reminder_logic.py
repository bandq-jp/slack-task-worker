from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.infrastructure.notion.dynamic_notion_service import (
    REMINDER_STAGE_BEFORE,
    REMINDER_STAGE_OVERDUE,
    REMINDER_STAGE_PENDING_APPROVAL,
    EXTENSION_STATUS_PENDING,
    COMPLETION_STATUS_REQUESTED,
    COMPLETION_STATUS_APPROVED,
    TASK_STATUS_PENDING,
    TASK_STATUS_APPROVED,
)
from src.presentation.api.slack_endpoints import (
    determine_reminder_stage,
    _should_clear_overdue_points,
)


def _snapshot(**overrides):
    now = datetime.now(timezone.utc)
    base = {
        "status": TASK_STATUS_APPROVED,
        "completion_status": None,
        "due_date": now + timedelta(days=2),
        "extension_status": None,
        "completion_requested_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_determine_stage_for_pending_task_returns_pending_stage():
    now = datetime.now(timezone.utc)
    snapshot = _snapshot(status=TASK_STATUS_PENDING)

    stage = determine_reminder_stage(snapshot, now)

    assert stage == REMINDER_STAGE_PENDING_APPROVAL


def test_determine_stage_before_due_when_approved():
    now = datetime.now(timezone.utc)
    snapshot = _snapshot(due_date=now + timedelta(hours=8))

    stage = determine_reminder_stage(snapshot, now)

    assert stage == REMINDER_STAGE_BEFORE


def test_determine_stage_skips_when_extension_pending():
    now = datetime.now(timezone.utc)
    snapshot = _snapshot(due_date=now + timedelta(hours=8), extension_status=EXTENSION_STATUS_PENDING)

    stage = determine_reminder_stage(snapshot, now)

    assert stage is None


def test_determine_stage_overdue_when_past_due():
    now = datetime.now(timezone.utc)
    snapshot = _snapshot(due_date=now - timedelta(hours=1))

    stage = determine_reminder_stage(snapshot, now)

    assert stage == REMINDER_STAGE_OVERDUE


def test_should_clear_points_when_due_in_future():
    now = datetime.now(timezone.utc)
    snapshot = _snapshot(due_date=now + timedelta(days=1))

    assert _should_clear_overdue_points(snapshot, now)


def test_should_clear_points_when_task_pending():
    now = datetime.now(timezone.utc)
    snapshot = _snapshot(status=TASK_STATUS_PENDING, due_date=now - timedelta(days=1))

    assert _should_clear_overdue_points(snapshot, now)


def test_should_clear_points_when_completion_requested_on_time():
    now = datetime.now(timezone.utc)
    due = now - timedelta(hours=2)
    snapshot = _snapshot(
        due_date=due,
        completion_status=COMPLETION_STATUS_REQUESTED,
        completion_requested_at=due - timedelta(minutes=5),
    )

    assert _should_clear_overdue_points(snapshot, now)


def test_should_keep_points_when_completion_requested_late():
    now = datetime.now(timezone.utc)
    due = now - timedelta(hours=2)
    snapshot = _snapshot(
        due_date=due,
        completion_status=COMPLETION_STATUS_APPROVED,
        completion_requested_at=due + timedelta(hours=1),
    )

    assert not _should_clear_overdue_points(snapshot, now)

