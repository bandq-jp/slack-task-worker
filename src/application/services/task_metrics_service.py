from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Iterable, Optional, Sequence

from src.domain.entities.task_metrics import TaskMetricsRecord
from src.domain.services.task_metrics_domain_service import TaskMetricsDomainService
from src.infrastructure.notion.admin_metrics_service import AdminMetricsNotionService
from src.infrastructure.notion.dynamic_notion_service import NotionTaskSnapshot


class _DisabledAdminMetricsService:
    """No-op replacement for AdminMetricsNotionService when metrics更新を無効化する場合に使用。"""

    async def get_metrics_by_task_id(self, task_page_id: str) -> Optional[TaskMetricsRecord]:
        return None

    async def upsert_task_metrics(self, record: TaskMetricsRecord) -> TaskMetricsRecord:
        return record

    async def update_overdue_points(self, task_page_id: str, points: int) -> Optional[TaskMetricsRecord]:
        return None

    async def update_reminder_stage(
        self,
        task_page_id: str,
        stage: Optional[str],
        timestamp: datetime,
    ) -> Optional[TaskMetricsRecord]:
        return None

    async def fetch_all_metrics(self) -> Sequence[TaskMetricsRecord]:
        return ()

    async def upsert_assignee_summaries(self, summaries: Sequence) -> None:
        return None


class TaskMetricsApplicationService:
    """タスクメトリクス管理アプリケーションサービス"""

    def __init__(
        self,
        admin_metrics_service: AdminMetricsNotionService,
        domain_service: Optional[TaskMetricsDomainService] = None,
        *,
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self._real_admin_metrics_service = admin_metrics_service
        self.admin_metrics_service = (
            admin_metrics_service if enabled else _DisabledAdminMetricsService()
        )
        self.domain_service = domain_service or TaskMetricsDomainService()

    async def ensure_metrics_for_snapshots(
        self,
        snapshots: Iterable[NotionTaskSnapshot],
    ) -> Dict[str, TaskMetricsRecord]:
        if not self.enabled:
            return {}
        metrics: Dict[str, TaskMetricsRecord] = {}
        for snapshot in snapshots:
            record = await self.sync_snapshot(snapshot)
            metrics[snapshot.page_id] = record
        return metrics

    async def sync_snapshot(
        self,
        snapshot: NotionTaskSnapshot,
        *,
        reminder_stage: Optional[str] = None,
        overdue_points: Optional[int] = None,
    ) -> TaskMetricsRecord:
        now_utc = datetime.now(timezone.utc)
        record = TaskMetricsRecord(
            task_page_id=snapshot.page_id,
            task_title=snapshot.title,
            assignee_email=snapshot.assignee_email,
            assignee_notion_id=snapshot.assignee_notion_id,
            assignee_name=None,
            due_date=snapshot.due_date,
            status=snapshot.status,
            reminder_stage=reminder_stage or snapshot.reminder_stage,
            overdue_points=overdue_points if overdue_points is not None else 0,
            completion_status=snapshot.completion_status,
            extension_status=snapshot.extension_status,
        )

        existing: Optional[TaskMetricsRecord] = None
        if self.enabled:
            existing = await self.admin_metrics_service.get_metrics_by_task_id(snapshot.page_id)
        if existing:
            record.metrics_page_id = existing.metrics_page_id
            record.assignee_name = existing.assignee_name
            record.last_synced_at = datetime.now(timezone.utc)
            if record.assignee_email is None:
                record.assignee_email = existing.assignee_email
            if record.assignee_notion_id is None:
                record.assignee_notion_id = existing.assignee_notion_id
            if reminder_stage is None:
                record.reminder_stage = existing.reminder_stage
            if overdue_points is None:
                record.overdue_points = existing.overdue_points
        else:
            record.last_synced_at = now_utc
            if overdue_points is None:
                record.overdue_points = 0

        # 延期などで納期が未来になった場合はポイントを必ず0にする（即時リセット）
        if overdue_points is None:
            if record.due_date and record.due_date.tzinfo:
                due_utc = record.due_date.astimezone(timezone.utc)
            else:
                due_utc = record.due_date.replace(tzinfo=timezone.utc) if record.due_date else None
            if due_utc and due_utc > now_utc:
                record.overdue_points = 0

        if not self.enabled:
            return record

        return await self.admin_metrics_service.upsert_task_metrics(record)

    async def update_overdue_points(self, task_page_id: str, points: int) -> Optional[TaskMetricsRecord]:
        if not self.enabled:
            return None
        return await self.admin_metrics_service.update_overdue_points(task_page_id, points)

    async def update_reminder_stage(
        self,
        task_page_id: str,
        stage: Optional[str],
        timestamp: datetime,
    ) -> Optional[TaskMetricsRecord]:
        if not self.enabled:
            return None
        return await self.admin_metrics_service.update_reminder_stage(task_page_id, stage, timestamp)

    async def refresh_assignee_summaries(self) -> None:
        if not self.enabled:
            return None
        metrics = await self.admin_metrics_service.fetch_all_metrics()
        print(f"📈 Metrics fetched for summary: {len(metrics)} 件")
        summaries = self.domain_service.build_assignee_summaries(metrics, datetime.now(timezone.utc))
        print(f"🧾 Summaries to upsert: {len(summaries)} 件")
        await self.admin_metrics_service.upsert_assignee_summaries(summaries)
