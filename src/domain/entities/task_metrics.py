from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass(slots=True)
class TaskMetricsRecord:
    task_page_id: str
    task_title: str
    assignee_email: Optional[str]
    assignee_notion_id: Optional[str]
    assignee_name: Optional[str]
    due_date: Optional[datetime]
    status: Optional[str]
    reminder_stage: Optional[str]
    overdue_points: int = 0
    completion_status: Optional[str] = None
    extension_status: Optional[str] = None
    metrics_page_id: Optional[str] = None
    last_synced_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class AssigneeMetricsSummary:
    assignee_email: Optional[str]
    assignee_notion_id: Optional[str]
    assignee_name: Optional[str]
    total_tasks: int
    overdue_tasks: int
    due_within_three_days: int
    next_due_date: Optional[datetime]
    total_overdue_points: int
    summary_page_id: Optional[str] = None
    last_calculated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
