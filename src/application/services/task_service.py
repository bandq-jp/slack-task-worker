from typing import Optional
from src.domain.entities.task import TaskRequest, TaskStatus
from src.domain.entities.user import User
from src.domain.repositories.task_repository import TaskRepositoryInterface
from src.domain.repositories.user_repository import UserRepositoryInterface
from src.application.dto.task_dto import CreateTaskRequestDto, TaskApprovalDto, TaskResponseDto


class TaskApplicationService:
    """タスク管理アプリケーションサービス"""

    def __init__(
        self,
        task_repository: TaskRepositoryInterface,
        user_repository: UserRepositoryInterface,
        slack_service,  # SlackServiceインターフェース
        notion_service,  # NotionServiceインターフェース
    ):
        self.task_repository = task_repository
        self.user_repository = user_repository
        self.slack_service = slack_service
        self.notion_service = notion_service

    async def create_task_request(self, dto: CreateTaskRequestDto) -> TaskResponseDto:
        """タスク依頼を作成"""
        # 依頼者と依頼先のユーザー情報を取得
        requester = await self.slack_service.get_user_info(dto.requester_slack_id)
        assignee = await self.slack_service.get_user_info(dto.assignee_slack_id)

        # タスクエンティティを作成
        task = TaskRequest(
            requester_slack_id=dto.requester_slack_id,
            assignee_slack_id=dto.assignee_slack_id,
            title=dto.title,
            description=dto.description,
            due_date=dto.due_date,
        )

        # タスクを保存
        saved_task = await self.task_repository.save(task)

        # 依頼先にDMで通知
        await self.slack_service.send_approval_request(
            assignee_slack_id=dto.assignee_slack_id,
            task=saved_task,
            requester_name=requester.get("real_name", "Unknown"),
        )

        return self._to_response_dto(saved_task)

    async def handle_task_approval(self, dto: TaskApprovalDto) -> TaskResponseDto:
        """タスクの承認/差し戻しを処理"""
        # タスクを取得
        task = await self.task_repository.find_by_id(dto.task_id)
        if not task:
            raise ValueError(f"Task not found: {dto.task_id}")

        # 承認または差し戻し
        if dto.action == "approve":
            task.approve()

            # Notionにタスクを保存
            requester_info = await self.slack_service.get_user_info(task.requester_slack_id)
            assignee_info = await self.slack_service.get_user_info(task.assignee_slack_id)

            notion_page_id = await self.notion_service.create_task(
                task=task,
                requester_email=requester_info.get("profile", {}).get("email"),
                assignee_email=assignee_info.get("profile", {}).get("email"),
            )

            task.notion_page_id = notion_page_id

            # 依頼者に承認通知
            await self.slack_service.notify_approval(
                requester_slack_id=task.requester_slack_id,
                task=task,
            )

        elif dto.action == "reject":
            if not dto.rejection_reason:
                raise ValueError("Rejection reason is required")

            task.reject(dto.rejection_reason)

            # 依頼者に差し戻し通知
            await self.slack_service.notify_rejection(
                requester_slack_id=task.requester_slack_id,
                task=task,
            )
        else:
            raise ValueError(f"Invalid action: {dto.action}")

        # タスクを更新
        updated_task = await self.task_repository.update(task)

        return self._to_response_dto(updated_task)

    def _to_response_dto(self, task: TaskRequest) -> TaskResponseDto:
        """タスクエンティティをレスポンスDTOに変換"""
        return TaskResponseDto(
            id=task.id,
            requester_slack_id=task.requester_slack_id,
            assignee_slack_id=task.assignee_slack_id,
            title=task.title,
            description=task.description,
            due_date=task.due_date,
            status=task.status.value,
            rejection_reason=task.rejection_reason,
            created_at=task.created_at,
            updated_at=task.updated_at,
            notion_page_id=task.notion_page_id,
        )