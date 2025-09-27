from datetime import datetime, timedelta, timezone

from src.domain.entities.task_metrics import TaskMetricsRecord
from src.domain.services.task_metrics_domain_service import TaskMetricsDomainService


def _record(
    *,
    task_id: str,
    due_offset: timedelta,
    overdue_points: int = 0,
    status: str | None = None,
    completion_status: str | None = None,
) -> TaskMetricsRecord:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    due_date = base + due_offset if due_offset is not None else None
    return TaskMetricsRecord(
        task_page_id=task_id,
        task_title=f"Task {task_id}",
        assignee_email="user@example.com",
        assignee_notion_id=None,
        assignee_name=None,
        due_date=due_date,
        status=status,
        reminder_stage=None,
        overdue_points=overdue_points,
        completion_status=completion_status,
        extension_status=None,
    )


def test_build_assignee_summary_counts():
    service = TaskMetricsDomainService()
    reference = datetime(2024, 1, 1, tzinfo=timezone.utc)

    records = [
        _record(task_id="1", due_offset=timedelta(days=1), status="承認済み"),
        _record(task_id="2", due_offset=timedelta(days=-1), overdue_points=2, status="承認済み"),
        _record(task_id="3", due_offset=timedelta(days=5), overdue_points=0, status="承認済み"),
    ]

    summaries = service.build_assignee_summaries(records, reference)

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.total_tasks == 3
    assert summary.overdue_tasks == 1
    assert summary.due_within_three_days == 1
    assert summary.total_overdue_points == 2
    assert summary.next_due_date == datetime(2024, 1, 2, tzinfo=timezone.utc)


def test_completed_tasks_not_counted_as_overdue():
    service = TaskMetricsDomainService()
    reference = datetime(2024, 1, 10, tzinfo=timezone.utc)

    records = [
        _record(
            task_id="1",
            due_offset=timedelta(days=-2),
            overdue_points=3,
            status="完了",
            completion_status="完了承認",
        ),
        _record(
            task_id="2",
            due_offset=timedelta(days=0),
            overdue_points=1,
            status="承認済み",
            completion_status="進行中",
        ),
    ]

    summaries = service.build_assignee_summaries(records, reference)

    assert summaries[0].overdue_tasks == 0
    assert summaries[0].due_within_three_days == 1
    assert summaries[0].total_overdue_points == 4
