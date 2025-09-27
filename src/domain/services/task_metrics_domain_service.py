from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional

from src.domain.entities.task_metrics import AssigneeMetricsSummary, TaskMetricsRecord

_COMPLETION_APPROVED_LABELS = {"完了承認", "完了"}
_STATUS_COMPLETED_LABELS = {"完了"}


def _normalize_reference_time(reference_time: Optional[datetime]) -> datetime:
    if reference_time is None:
        return datetime.now(timezone.utc)
    if reference_time.tzinfo is None:
        return reference_time.replace(tzinfo=timezone.utc)
    return reference_time


class TaskMetricsDomainService:
    """タスクメトリクス集計のドメインロジック"""

    def build_assignee_summaries(
        self,
        metrics_records: Iterable[TaskMetricsRecord],
        reference_time: Optional[datetime] = None,
    ) -> List[AssigneeMetricsSummary]:
        ref_time = _normalize_reference_time(reference_time)
        due_soon_threshold = ref_time + timedelta(days=3)

        grouped: dict[str, list[TaskMetricsRecord]] = defaultdict(list)
        for record in metrics_records:
            key = record.assignee_email or record.assignee_notion_id or "__unassigned__"
            grouped[key].append(record)

        summaries: List[AssigneeMetricsSummary] = []
        for records in grouped.values():
            if not records:
                continue

            assignee_email = records[0].assignee_email
            assignee_notion_id = records[0].assignee_notion_id
            assignee_name = records[0].assignee_name

            overdue_tasks = 0
            due_within_three_days = 0
            next_due_candidate: Optional[datetime] = None
            total_overdue_points = 0

            for record in records:
                total_overdue_points += max(record.overdue_points, 0)

                due_date = record.due_date
                completed = self._is_completed(record)

                if due_date:
                    due_date = self._ensure_timezone(due_date)
                    if not completed:
                        if due_date < ref_time:
                            overdue_tasks += 1
                        if ref_time <= due_date <= due_soon_threshold:
                            due_within_three_days += 1
                        if due_date >= ref_time:
                            if next_due_candidate is None or due_date < next_due_candidate:
                                next_due_candidate = due_date

            summaries.append(
                AssigneeMetricsSummary(
                    assignee_email=assignee_email,
                    assignee_notion_id=assignee_notion_id,
                    assignee_name=assignee_name,
                    total_tasks=len(records),
                    overdue_tasks=overdue_tasks,
                    due_within_three_days=due_within_three_days,
                    next_due_date=next_due_candidate,
                    total_overdue_points=total_overdue_points,
                )
            )

        return summaries

    @staticmethod
    def _ensure_timezone(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _is_completed(record: TaskMetricsRecord) -> bool:
        status = (record.status or "").strip()
        completion_status = (record.completion_status or "").strip()

        if status in _STATUS_COMPLETED_LABELS:
            return True
        if completion_status in _COMPLETION_APPROVED_LABELS:
            return True
        return False
