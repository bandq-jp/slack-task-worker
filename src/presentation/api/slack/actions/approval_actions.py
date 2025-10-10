import asyncio
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi.responses import JSONResponse

from src.application.dto.task_dto import TaskApprovalDto
from src.domain.entities.task import TaskRequest, TaskStatus
from src.infrastructure.notion.dynamic_notion_service import (
    TASK_STATUS_PENDING,
    TASK_STATUS_APPROVED,
    TASK_STATUS_REJECTED,
    TASK_STATUS_COMPLETED,
)
from src.domain.value_objects.email import Email
from src.presentation.api.slack.context import SlackDependencies


async def handle_approve_task_action(
    payload: Dict[str, Any],
    dependencies: SlackDependencies,
    trigger_id: str,
    task_id: str,
    page_id: Optional[str],
) -> JSONResponse:
    """承認ボタン押下時の処理。処理中モーダルを表示し、完了後に更新する。"""

    slack_service = dependencies.slack_service
    notion_service = dependencies.notion_service
    task_service = dependencies.task_service
    calendar_task_service = dependencies.calendar_task_service
    settings = dependencies.settings

    modal_title = f"承認処理{settings.app_name_suffix}"
    processing_message = "タスクを承認しています。しばらくお待ちください。"
    success_title = "承認が完了しました"
    error_title = "承認に失敗しました"

    processing_view_id = slack_service.open_processing_modal(
        trigger_id=trigger_id,
        title=modal_title,
        message=processing_message,
    )

    async def ensure_task_in_repository() -> Optional[TaskRequest]:
        task = await dependencies.task_service.task_repository.find_by_id(task_id)
        if task:
            return task

        if not page_id:
            return None

        snapshot = await dependencies.notion_service.get_task_snapshot(page_id)
        if not snapshot:
            return None

        requester_slack_id = None
        assignee_slack_id = payload.get("user", {}).get("id")

        if snapshot.requester_email:
            requester_user = await dependencies.slack_user_repository.find_by_email(Email(snapshot.requester_email))
            if requester_user:
                requester_slack_id = str(requester_user.user_id)

        if snapshot.assignee_email and not assignee_slack_id:
            assignee_user = await dependencies.slack_user_repository.find_by_email(Email(snapshot.assignee_email))
            if assignee_user:
                assignee_slack_id = str(assignee_user.user_id)

        due_date = snapshot.due_date or datetime.now()
        status_map = {
            TASK_STATUS_PENDING: TaskStatus.PENDING,
            TASK_STATUS_APPROVED: TaskStatus.APPROVED,
            TASK_STATUS_REJECTED: TaskStatus.REJECTED,
            TASK_STATUS_COMPLETED: TaskStatus.APPROVED,
        }
        status = status_map.get(getattr(snapshot, "status", None), TaskStatus.PENDING)

        hydrated = TaskRequest(
            id=task_id,
            requester_slack_id=requester_slack_id or "",
            assignee_slack_id=assignee_slack_id or "",
            title=snapshot.title,
            description=None,
            due_date=due_date,
            task_type=getattr(snapshot, "task_type", ""),
            urgency=getattr(snapshot, "urgency", ""),
            status=status,
            notion_page_id=snapshot.page_id,
        )

        if snapshot.created_time:
            hydrated.created_at = snapshot.created_time
        hydrated.updated_at = datetime.now()

        await dependencies.task_repository.save(hydrated)
        return hydrated

    async def run_approval_with_modal() -> None:
        try:
            print(f"🔄 承認処理開始: task_id={task_id}")

            dto = TaskApprovalDto(
                task_id=task_id,
                action="approve",
                rejection_reason=None,
            )

            await ensure_task_in_repository()
            result = await task_service.handle_task_approval(dto)
            print("✅ 承認処理成功 - 親メッセージとスレッド通知が送信されました")

            if calendar_task_service and page_id:
                try:
                    task_data = await notion_service.get_task_by_id(page_id)
                    if task_data:
                        approver_slack_id = payload.get("user", {}).get("id")
                        calendar_task = await calendar_task_service.create_task_on_approval(
                            task_data=task_data,
                            approver_slack_user_id=approver_slack_id,
                        )

                        if calendar_task:
                            print("✅ Google Calendar task created")
                            saved_task = await task_service.task_repository.find_by_id(task_id)
                            if saved_task and saved_task.notion_page_id:
                                snapshot = await notion_service.get_task_snapshot(saved_task.notion_page_id)
                                if snapshot and snapshot.assignee_thread_ts and snapshot.assignee_thread_channel:
                                    slack_service.client.chat_postMessage(
                                        channel=snapshot.assignee_thread_channel,
                                        thread_ts=snapshot.assignee_thread_ts,
                                        text="📅 Googleカレンダーのタスクに追加しました",
                                    )
                    else:
                        print(f"⚠️ Could not get task data from Notion for page_id: {page_id}")
                except Exception as cal_error:
                    print(f"⚠️ Calendar task creation error: {cal_error}")

            success_message = f"タスク「{result.title}」を承認しました。"
            slack_service.update_modal_message(
                view_id=processing_view_id,
                title=success_title,
                message=success_message,
                emoji="✅",
                close_text="閉じる",
            )

        except Exception as error:
            print(f"❌ 承認処理エラー: {error}")
            slack_service.update_modal_message(
                view_id=processing_view_id,
                title=error_title,
                message=f"エラーが発生しました: {str(error)}",
                emoji="⚠️",
                close_text="閉じる",
            )
            import traceback

            traceback.print_exc()

    asyncio.create_task(run_approval_with_modal())
    return JSONResponse(content={})
