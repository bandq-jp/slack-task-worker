from typing import Optional
from src.domain.entities.task import TaskRequest, TaskStatus
from src.domain.entities.user import User
from src.domain.repositories.task_repository import TaskRepositoryInterface
from src.domain.repositories.user_repository import UserRepositoryInterface
from src.application.dto.task_dto import (
    CreateTaskRequestDto,
    TaskApprovalDto,
    TaskResponseDto,
    ReviseTaskRequestDto,
)
from src.application.services.task_metrics_service import TaskMetricsApplicationService


class TaskApplicationService:
    """タスク管理アプリケーションサービス"""

    def __init__(
        self,
        task_repository: TaskRepositoryInterface,
        user_repository: UserRepositoryInterface,
        slack_service,  # SlackServiceインターフェース
        notion_service,  # NotionServiceインターフェース
        task_metrics_service: Optional[TaskMetricsApplicationService] = None,
    ):
        self.task_repository = task_repository
        self.user_repository = user_repository
        self.slack_service = slack_service
        self.notion_service = notion_service
        self.task_metrics_service = task_metrics_service

    async def create_task_request(self, dto: CreateTaskRequestDto) -> TaskResponseDto:
        """タスク依頼を作成"""
        # 依頼者と依頼先のユーザー情報を取得
        requester = await self.slack_service.get_user_info(dto.requester_slack_id)
        assignee = await self.slack_service.get_user_info(dto.assignee_slack_id)

        print(f"🔍 Requester info: {requester}")
        print(f"🔍 Assignee info: {assignee}")

        requester_email = requester.get("profile", {}).get("email")
        assignee_email = assignee.get("profile", {}).get("email")

        print(f"📧 Requester email: {requester_email}")
        print(f"📧 Assignee email: {assignee_email}")

        # タスクエンティティを作成
        print(f"🔧 DTO values: task_type='{dto.task_type}', urgency='{dto.urgency}'")
        
        task = TaskRequest(
            requester_slack_id=dto.requester_slack_id,
            assignee_slack_id=dto.assignee_slack_id,
            title=dto.title,
            description=dto.description,
            due_date=dto.due_date,
            task_type=dto.task_type,
            urgency=dto.urgency,
        )
        
        print(f"🚀 Created task: task_type='{task.task_type}', urgency='{task.urgency}'")

        # 即座にNotionにタスクを保存（承認待ち状態で）
        notion_page_id = await self.notion_service.create_task(
            task=task,
            requester_email=requester_email,
            assignee_email=assignee_email,
        )

        if not notion_page_id:
            raise ValueError("Notionへのタスク保存に失敗しました。サーバーログを確認してください。")

        task.notion_page_id = notion_page_id

        # インメモリリポジトリにも保存（承認処理で必要）
        saved_task = await self.task_repository.save(task)

        # 依頼先にDMで通知
        await self.slack_service.send_approval_request(
            assignee_slack_id=dto.assignee_slack_id,
            task=saved_task,
            requester_name=requester.get("real_name", "Unknown"),
        )

        await self._sync_metrics(task.notion_page_id)

        return self._to_response_dto(saved_task)

    async def revise_task_request(self, dto: ReviseTaskRequestDto) -> TaskResponseDto:
        """差し戻されたタスクを修正して再送信"""
        task = await self.task_repository.find_by_id(dto.task_id)
        if not task:
            raise ValueError(f"Task not found: {dto.task_id}")

        if task.requester_slack_id != dto.requester_slack_id:
            raise ValueError("Only the original requester can revise this task")

        requester_info = await self.slack_service.get_user_info(dto.requester_slack_id)
        assignee_info = await self.slack_service.get_user_info(dto.assignee_slack_id)

        requester_email = requester_info.get("profile", {}).get("email")
        assignee_email = assignee_info.get("profile", {}).get("email")

        task.revise(
            assignee_slack_id=dto.assignee_slack_id,
            title=dto.title,
            description=dto.description,
            due_date=dto.due_date,
            task_type=dto.task_type,
            urgency=dto.urgency,
        )

        if task.notion_page_id:
            await self.notion_service.update_task_revision(
                task=task,
                requester_email=requester_email,
                assignee_email=assignee_email,
            )
        else:
            notion_page_id = await self.notion_service.create_task(
                task=task,
                requester_email=requester_email,
                assignee_email=assignee_email,
            )
            if not notion_page_id:
                raise ValueError("Notionへのタスク更新に失敗しました。サーバーログを確認してください。")
            task.notion_page_id = notion_page_id

        updated_task = await self.task_repository.update(task)

        requester_name = requester_info.get("real_name") or requester_info.get("profile", {}).get("real_name", "Unknown")

        await self.slack_service.send_approval_request(
            assignee_slack_id=dto.assignee_slack_id,
            task=updated_task,
            requester_name=requester_name,
        )

        await self.notion_service.record_audit_log(
            task_page_id=task.notion_page_id,
            event_type="再依頼",
            detail=f"タスクを修正して再送信\n納期: {dto.due_date.strftime('%Y-%m-%d %H:%M')}",
            actor_email=requester_email,
        )

        await self._sync_metrics(task.notion_page_id)

        return self._to_response_dto(updated_task)

    async def handle_task_approval(self, dto: TaskApprovalDto) -> TaskResponseDto:
        """タスクの承認/差し戻しを処理"""
        # タスクを取得
        task = await self.task_repository.find_by_id(dto.task_id)
        if not task:
            raise ValueError(f"Task not found: {dto.task_id}")

        # 承認または差し戻し
        if dto.action == "approve":
            task.approve()

            # Notionのステータスを更新
            if task.notion_page_id:
                await self.notion_service.update_task_status(
                    page_id=task.notion_page_id,
                    status=task.status.value,
                )

            # 依頼者に承認通知
            await self.slack_service.notify_approval(
                requester_slack_id=task.requester_slack_id,
                task=task,
            )

        elif dto.action == "reject":
            if not dto.rejection_reason:
                raise ValueError("Rejection reason is required")

            task.reject(dto.rejection_reason)

            # Notionのステータスを更新
            if task.notion_page_id:
                await self.notion_service.update_task_status(
                    page_id=task.notion_page_id,
                    status=task.status.value,
                    rejection_reason=dto.rejection_reason,
                )

            # 依頼者に差し戻し通知
            await self.slack_service.notify_rejection(
                requester_slack_id=task.requester_slack_id,
                task=task,
            )
        else:
            raise ValueError(f"Invalid action: {dto.action}")

        # タスクを更新
        updated_task = await self.task_repository.update(task)

        await self._sync_metrics(task.notion_page_id)

        return self._to_response_dto(updated_task)

    async def _sync_metrics(self, notion_page_id: Optional[str]) -> None:
        if not notion_page_id or not self.task_metrics_service:
            return

        snapshot = await self.notion_service.get_task_snapshot(notion_page_id)
        if snapshot:
            await self.task_metrics_service.sync_snapshot(snapshot)
            await self.task_metrics_service.refresh_assignee_summaries()

    def _to_response_dto(self, task: TaskRequest) -> TaskResponseDto:
        """タスクエンティティをレスポンスDTOに変換"""
        return TaskResponseDto(
            id=task.id,
            requester_slack_id=task.requester_slack_id,
            assignee_slack_id=task.assignee_slack_id,
            title=task.title,
            description=task.description,
            due_date=task.due_date,
            task_type=task.task_type,
            urgency=task.urgency,
            status=task.status.value,
            rejection_reason=task.rejection_reason,
            created_at=task.created_at,
            updated_at=task.updated_at,
            notion_page_id=task.notion_page_id,
        )
