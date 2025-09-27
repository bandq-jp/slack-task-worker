import json
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException, Form, Depends
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional, List
from src.application.services.task_service import TaskApplicationService
from src.application.dto.task_dto import CreateTaskRequestDto, TaskApprovalDto, ReviseTaskRequestDto
from src.infrastructure.slack.slack_service import SlackService, REMINDER_STAGE_LABELS
from src.infrastructure.notion.admin_metrics_service import AdminMetricsNotionService
from src.application.services.task_metrics_service import TaskMetricsApplicationService
from src.infrastructure.notion.dynamic_notion_service import (
    DynamicNotionService,
    REMINDER_STAGE_BEFORE,
    REMINDER_STAGE_DUE,
    REMINDER_STAGE_OVERDUE,
    REMINDER_STAGE_PENDING_APPROVAL,
    EXTENSION_STATUS_PENDING,
    COMPLETION_STATUS_REQUESTED,
    COMPLETION_STATUS_APPROVED,
    TASK_STATUS_PENDING,
    TASK_STATUS_APPROVED,
)
from src.infrastructure.repositories.notion_user_repository_impl import NotionUserRepositoryImpl
from src.infrastructure.repositories.slack_user_repository_impl import SlackUserRepositoryImpl
from src.application.services.user_mapping_service import UserMappingApplicationService
from src.domain.services.user_mapping_domain_service import UserMappingDomainService
from src.infrastructure.repositories.task_repository_impl import InMemoryTaskRepository
from src.infrastructure.repositories.user_repository_impl import InMemoryUserRepository
from src.infrastructure.google.google_calendar_service import GoogleCalendarService
from src.infrastructure.repositories.calendar_task_repository_impl import GoogleCalendarTaskRepository
from src.application.services.calendar_task_service import CalendarTaskApplicationService
from src.services.ai_service import TaskAIService, TaskInfo, AIAnalysisResult
from src.utils.text_converter import convert_rich_text_to_plain_text
from src.domain.value_objects.email import Email
from zoneinfo import ZoneInfo
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    slack_token: str = ""
    slack_bot_token: str = ""
    slack_signing_secret: str = ""
    notion_token: str = ""
    notion_database_id: str = ""
    notion_audit_database_id: str = ""
    mapping_database_id: str = ""
    notion_metrics_database_id: str = ""
    notion_assignee_summary_database_id: str = ""
    gcs_bucket_name: str = ""
    google_application_credentials: str = ""
    service_account_json: str = ""
    env: str = "local"
    gemini_api_key: str = ""
    gemini_timeout_seconds: float = 30.0
    gemini_model: str = "gemini-2.5-flash"
    gemini_history_path: str = ".ai_conversations.json"

    class Config:
        env_file = ".env"

    @property
    def slack_command_name(self) -> str:
        """環境に応じてスラッシュコマンド名を返す"""
        if self.env == "production":
            return "/task-request"
        else:
            return "/task-request-dev"

    @property
    def app_name_suffix(self) -> str:
        """環境に応じてアプリ名の接尾辞を返す"""
        if self.env == "production":
            return ""
        else:
            return " (Dev)"


router = APIRouter(prefix="/slack", tags=["slack"])
settings = Settings()
JST = ZoneInfo("Asia/Tokyo")

# セッション情報を一時的に保存する辞書
modal_sessions = {}

print("🚀 Slack-Notion Task Management System initialized!")
print(f"🌍 Environment: {settings.env}")
print(f"📋 Slack Command: {settings.slack_command_name}{settings.app_name_suffix}")
print(f"📊 Notion Database: {settings.notion_database_id}")
if settings.notion_metrics_database_id:
    print(f"📈 Metrics Database: {settings.notion_metrics_database_id}")
if settings.notion_assignee_summary_database_id:
    print(f"👤 Summary Database: {settings.notion_assignee_summary_database_id}")
print("🔄 Using dynamic user search (no mapping files)")

# リポジトリとサービスのインスタンス化（DDD版DI）
task_repository = InMemoryTaskRepository()
user_repository = InMemoryUserRepository()
slack_service = SlackService(settings.slack_token, settings.slack_bot_token, settings.env)

# 新しいDDD実装のサービス初期化
notion_user_repository = NotionUserRepositoryImpl(
    notion_token=settings.notion_token,
    default_database_id=settings.notion_database_id
)
slack_user_repository = SlackUserRepositoryImpl(slack_token=settings.slack_bot_token)
mapping_domain_service = UserMappingDomainService()
user_mapping_service = UserMappingApplicationService(
    notion_user_repository=notion_user_repository,
    slack_user_repository=slack_user_repository,
    mapping_domain_service=mapping_domain_service
)

# 動的Notionサービス（DDD ベース）
notion_service = DynamicNotionService(
    notion_token=settings.notion_token,
    database_id=settings.notion_database_id,
    user_mapping_service=user_mapping_service,
    audit_database_id=settings.notion_audit_database_id,
)
admin_metrics_service = AdminMetricsNotionService(
    notion_token=settings.notion_token,
    metrics_database_id=settings.notion_metrics_database_id,
    summary_database_id=settings.notion_assignee_summary_database_id,
)
task_metrics_service = TaskMetricsApplicationService(admin_metrics_service=admin_metrics_service)
ai_service = (
    TaskAIService(
        settings.gemini_api_key,
        timeout_seconds=settings.gemini_timeout_seconds,
        model_name=settings.gemini_model,
        history_storage_path=settings.gemini_history_path,
    )
    if settings.gemini_api_key
    else None
)

task_service = TaskApplicationService(
    task_repository=task_repository,
    user_repository=user_repository,
    slack_service=slack_service,
    notion_service=notion_service,
    task_metrics_service=task_metrics_service,
)

# Google Calendar サービスの初期化（オプショナル）
calendar_task_service = None
if settings.service_account_json:
    try:
        google_calendar_service = GoogleCalendarService(
            service_account_json=settings.service_account_json,
            env=settings.env
        )
        calendar_task_repository = GoogleCalendarTaskRepository(google_calendar_service)
        calendar_task_service = CalendarTaskApplicationService(
            calendar_task_repository=calendar_task_repository,
            user_mapping_service=user_mapping_service
        )
        print("✅ Google Calendar integration initialized")
    except Exception as e:
        print(f"⚠️ Google Calendar initialization failed: {e}")
        print("   Calendar integration will be disabled")


@router.post("/cron/run-reminders")
async def run_reminders():
    """Notionタスクのリマインドを実行（Cloud Scheduler用）"""
    now = datetime.now(timezone.utc)
    try:
        snapshots = await notion_service.fetch_active_tasks()
    except Exception as fetch_error:
        print(f"⚠️ Failed to fetch tasks for reminders: {fetch_error}")
        return {"error": "notion_fetch_failed"}

    email_cache: Dict[str, Optional[str]] = {}
    notifications: List[Dict[str, Any]] = []
    errors: List[str] = []

    metrics_cache = await task_metrics_service.ensure_metrics_for_snapshots(snapshots)

    async def resolve_slack_id(email: Optional[str]) -> Optional[str]:
        if not email:
            return None
        if email in email_cache:
            return email_cache[email]
        try:
            slack_user = await slack_user_repository.find_by_email(Email(email))
            if slack_user:
                slack_id = str(slack_user.user_id)
                email_cache[email] = slack_id
                return slack_id
        except Exception as lookup_error:
            print(f"⚠️ Slack lookup failed for {email}: {lookup_error}")
            errors.append(f"slack_lookup:{email}")
        email_cache[email] = None
        return None

    for snapshot in snapshots:
        try:
            stage = determine_reminder_stage(snapshot, now)

            metrics = metrics_cache.get(snapshot.page_id)

            if stage is None:
                if metrics and metrics.overdue_points and _should_clear_overdue_points(snapshot, now):
                    updated_metrics = await task_metrics_service.update_overdue_points(snapshot.page_id, 0)
                    if updated_metrics:
                        metrics_cache[snapshot.page_id] = updated_metrics
                continue

            if stage == REMINDER_STAGE_PENDING_APPROVAL and metrics and metrics.overdue_points:
                updated_metrics = await task_metrics_service.update_overdue_points(snapshot.page_id, 0)
                if updated_metrics:
                    metrics_cache[snapshot.page_id] = updated_metrics
                    metrics = updated_metrics

            if stage == snapshot.reminder_stage:
                await task_metrics_service.update_reminder_stage(snapshot.page_id, stage, now)
                continue

            assignee_slack_id = await resolve_slack_id(snapshot.assignee_email)
            if not assignee_slack_id:
                errors.append(f"assignee_missing:{snapshot.page_id}")
                continue

            requester_slack_id = await resolve_slack_id(snapshot.requester_email)

            if stage == REMINDER_STAGE_OVERDUE:
                requested_before_due = _requested_on_time(
                    snapshot.completion_requested_at,
                    snapshot.due_date,
                )
                completion_safe = (
                    snapshot.completion_status in {COMPLETION_STATUS_REQUESTED, COMPLETION_STATUS_APPROVED}
                    and requested_before_due
                )
                eligible_for_overdue_points = getattr(snapshot, "status", None) == TASK_STATUS_APPROVED
                target_points = 1 if (eligible_for_overdue_points and not completion_safe) else 0
                current_points = metrics.overdue_points if metrics else 0
                if current_points != target_points:
                    updated_metrics = await task_metrics_service.update_overdue_points(snapshot.page_id, target_points)
                    if updated_metrics:
                        metrics_cache[snapshot.page_id] = updated_metrics
                        metrics = updated_metrics
            else:
                current_points = metrics.overdue_points if metrics else 0
                if current_points and _should_clear_overdue_points(snapshot, now):
                    updated_metrics = await task_metrics_service.update_overdue_points(snapshot.page_id, 0)
                    if updated_metrics:
                        metrics_cache[snapshot.page_id] = updated_metrics
                        metrics = updated_metrics

            await slack_service.send_task_reminder(
                assignee_slack_id=assignee_slack_id,
                snapshot=snapshot,
                stage=stage,
                requester_slack_id=requester_slack_id,
            )

            await notion_service.update_reminder_state(snapshot.page_id, stage, now)
            await task_metrics_service.update_reminder_stage(snapshot.page_id, stage, now)
            snapshot.reminder_stage = stage

            detail = f"{REMINDER_STAGE_LABELS.get(stage, stage)}\n納期: {_format_datetime_text(snapshot.due_date)}"
            event_type = "期限超過" if stage == REMINDER_STAGE_OVERDUE else "リマインド送信"
            await notion_service.record_audit_log(
                task_page_id=snapshot.page_id,
                event_type=event_type,
                detail=detail,
            )

            notifications.append(
                {
                    "page_id": snapshot.page_id,
                    "stage": stage,
                    "assignee_slack_id": assignee_slack_id,
                    "requester_slack_id": requester_slack_id,
                }
            )

        except Exception as reminder_error:
            print(f"⚠️ Reminder processing failed for task {getattr(snapshot, 'page_id', 'unknown')}: {reminder_error}")
            errors.append(f"reminder_error:{getattr(snapshot, 'page_id', 'unknown')}")

    await task_metrics_service.refresh_assignee_summaries()

    return {
        "timestamp": now.isoformat(),
        "checked": len(snapshots),
        "notified": len(notifications),
        "notifications": notifications,
        "errors": errors,
    }


@router.post("/commands")
async def handle_slash_command(request: Request):
    """スラッシュコマンドのハンドラー"""
    form = await request.form()
    command = form.get("command")
    trigger_id = form.get("trigger_id")
    user_id = form.get("user_id")

    if command == settings.slack_command_name:
        # タスク作成モーダルを開く（即時ACK + バックグラウンドで続行）
        import asyncio
        asyncio.create_task(slack_service.open_task_modal(trigger_id, user_id))
        return JSONResponse(content={"response_type": "ephemeral", "text": ""})

    return JSONResponse(
        content={"response_type": "ephemeral", "text": "Unknown command"}
    )


@router.post("/interactive")
async def handle_interactive(request: Request):
    """インタラクティブコンポーネント（ボタン、モーダル）のハンドラー"""
    form = await request.form()
    payload = json.loads(form.get("payload", "{}"))

    interaction_type = payload.get("type")
    print(f"🔍 Interactive payload received: type={interaction_type}")

    if interaction_type == "block_actions":
        # ボタンアクションの処理
        action = payload["actions"][0]
        action_id = action["action_id"]
        task_id = action.get("value", "")
        trigger_id = payload["trigger_id"]
        view = payload.get("view", {})
        view_id = view.get("id")
        user_id = payload.get("user", {}).get("id", "unknown")
        
        print(f"🎯 Block action received: action_id={action_id}, user_id={user_id}")
        print(f"🔍 Available actions: {[a.get('action_id') for a in payload.get('actions', [])]}")

        if action_id == "approve_task":
            try:
                # 即座にローディング表示（3秒制限回避）
                loading_response = {
                    "response_action": "update",
                    "text": "⏳ タスクを承認中...",
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": "⏳ *タスクを承認しています...*\n\nしばらくお待ちください。"
                            }
                        }
                    ]
                }
                
                # バックグラウンドで承認処理を実行
                import asyncio
                
                async def run_approval():
                    try:
                        dto = TaskApprovalDto(
                            task_id=task_id,
                            action="approve",
                            rejection_reason=None,
                        )
                        approval_result = await task_service.handle_task_approval(dto)
                        print("✅ 承認処理成功")

                        # Google Calendar にタスクを追加（オプショナル）
                        calendar_notes: List[str] = []
                        saved_task = None
                        if calendar_task_service:
                            try:
                                # まずTaskRequestを取得してnotion_page_idを確認
                                saved_task = await task_service.task_repository.find_by_id(task_id)
                                if saved_task and saved_task.notion_page_id:
                                    print(f"🔍 TaskRequest found: {task_id}, notion_page_id: {saved_task.notion_page_id}")
                                    # Notionからタスク情報を取得
                                    task_data = await notion_service.get_task_by_id(saved_task.notion_page_id)
                                    if task_data:
                                        # 承認者のSlack IDを取得
                                        approver_slack_id = payload.get("user", {}).get("id")

                                        # カレンダータスクを作成
                                        calendar_task = await calendar_task_service.create_task_on_approval(
                                            task_data=task_data,
                                            approver_slack_user_id=approver_slack_id
                                        )

                                        if calendar_task:
                                            calendar_notes.append("📅 Googleカレンダーのタスクに追加しました")
                                            print("✅ Google Calendar task created")
                                        else:
                                            calendar_notes.append("⚠️ Googleカレンダーへの追加はスキップされました（メールアドレスが見つかりません）")
                                    else:
                                        calendar_notes.append("⚠️ Notionからタスクデータを取得できませんでした")
                                        print(f"⚠️ Could not get task data from Notion for page_id: {saved_task.notion_page_id}")
                                else:
                                    calendar_notes.append("⚠️ タスクまたはNotionページIDが見つかりません")
                                    print(f"⚠️ TaskRequest not found or missing notion_page_id: task_id={task_id}")
                            except Exception as cal_error:
                                print(f"⚠️ Calendar task creation error: {cal_error}")
                                calendar_notes.append("⚠️ Googleカレンダーへの追加に失敗しました")

                        # 成功メッセージを表示（チャンネル、TS、メッセージIDが必要）
                        # Slack メッセージ更新のためのチャンネルとTSを取得
                        message = payload.get("message", {})
                        channel = payload.get("channel", {}).get("id")
                        message_ts = message.get("ts")
                        
                        if channel and message_ts:
                            try:
                                if not saved_task:
                                    saved_task = await task_service.task_repository.find_by_id(task_id)

                                notion_page_id = approval_result.notion_page_id or (
                                    saved_task.notion_page_id if saved_task else None
                                )
                                requester_slack_id = approval_result.requester_slack_id or (
                                    saved_task.requester_slack_id if saved_task else None
                                )
                                title_text = (approval_result.title or (saved_task.title if saved_task else "タスク")).strip()
                                title_text = title_text.replace("\n", " ")
                                stage_label = REMINDER_STAGE_LABELS.get("承認済", "承認済み")
                                header_text = f"{stage_label} - {title_text}"[:150]

                                status_lines = ["✅ このタスクは承認され、Notionに登録されました"]
                                status_lines.extend(calendar_notes)
                                status_text = "\n".join(status_lines)

                                blocks: List[Dict[str, Any]] = [
                                    {
                                        "type": "header",
                                        "text": {"type": "plain_text", "text": header_text, "emoji": True},
                                    },
                                    {
                                        "type": "section",
                                        "text": {"type": "mrkdwn", "text": status_text},
                                    },
                                ]

                                action_payload = None
                                notion_url = None
                                if notion_page_id:
                                    notion_url = f"https://www.notion.so/{notion_page_id.replace('-', '')}"
                                    title_display = title_text or "(件名未設定)"
                                    due_source = approval_result.due_date or (saved_task.due_date if saved_task else None)
                                    due_text = _format_datetime_text(due_source)

                                    blocks.append(
                                        {
                                            "type": "section",
                                            "fields": [
                                                {
                                                    "type": "mrkdwn",
                                                    "text": f"件名: <{notion_url}|{title_display}>",
                                                },
                                                {
                                                    "type": "mrkdwn",
                                                    "text": f"納期: {due_text if due_text else '-'}",
                                                },
                                            ],
                                        }
                                    )

                                    if requester_slack_id:
                                        action_payload = json.dumps(
                                            {
                                                "page_id": notion_page_id,
                                                "stage": "承認済",
                                                "requester_slack_id": requester_slack_id,
                                            }
                                        )

                                action_elements: List[Dict[str, Any]] = []
                                if notion_url:
                                    action_elements.append(
                                        {
                                            "type": "button",
                                            "action_id": "open_notion_page",
                                            "text": {"type": "plain_text", "text": "📝 Notionを開く", "emoji": True},
                                            "url": notion_url,
                                        }
                                    )

                                if action_payload:
                                    action_elements.append(
                                        {
                                            "type": "button",
                                            "text": {"type": "plain_text", "text": "✅ 完了報告", "emoji": True},
                                            "style": "primary",
                                            "action_id": "open_completion_modal",
                                            "value": action_payload,
                                        }
                                    )
                                    action_elements.append(
                                        {
                                            "type": "button",
                                            "text": {"type": "plain_text", "text": "⏳ 延期申請", "emoji": True},
                                            "action_id": "open_extension_modal",
                                            "value": action_payload,
                                        }
                                    )

                                if action_elements:
                                    blocks.append(
                                        {
                                            "type": "actions",
                                            "elements": action_elements,
                                        }
                                    )

                                if action_payload:
                                    blocks.append(
                                        {
                                            "type": "context",
                                            "elements": [
                                                {
                                                    "type": "mrkdwn",
                                                    "text": "完了報告は依頼者に送信されます。延期申請は依頼者による承認後に反映されます。",
                                                }
                                            ],
                                        }
                                    )

                                slack_service.client.chat_update(
                                    channel=channel,
                                    ts=message_ts,
                                    text="✅ タスクを承認しました",
                                    blocks=blocks,
                                )
                            except Exception as update_error:
                                print(f"⚠️ メッセージ更新エラー: {update_error}")
                                
                    except Exception as e:
                        print(f"❌ 承認処理エラー: {e}")
                        
                        # エラー時の表示（再試行ボタン付き）
                        message = payload.get("message", {})
                        channel = payload.get("channel", {}).get("id")
                        message_ts = message.get("ts")
                        
                        if channel and message_ts:
                            try:
                                slack_service.client.chat_update(
                                    channel=channel,
                                    ts=message_ts,
                                    text="❌ 承認処理でエラーが発生しました",
                                    blocks=[
                                        {
                                            "type": "section",
                                            "text": {
                                                "type": "mrkdwn",
                                                "text": f"❌ *承認処理でエラーが発生しました*\n\n{str(e)}"
                                            }
                                        },
                                        {
                                            "type": "actions",
                                            "elements": [
                                                {
                                                    "type": "button",
                                                    "text": {"type": "plain_text", "text": "🔄 再試行"},
                                                    "style": "primary",
                                                    "value": task_id,
                                                    "action_id": "approve_task",
                                                },
                                            ]
                                        }
                                    ]
                                )
                            except Exception as update_error:
                                print(f"⚠️ エラーメッセージ更新失敗: {update_error}")
                
                # 非同期タスクを開始
                asyncio.create_task(run_approval())
                
                # 即座にローディング表示を返す
                return JSONResponse(content=loading_response)
            except ValueError as e:
                # エラーメッセージを表示
                return JSONResponse(
                    content={
                        "response_action": "update",
                        "text": "❌ 承認処理でエラーが発生しました",
                        "blocks": [
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": f"❌ エラー: {str(e)}",
                                },
                            }
                        ],
                    }
                )

        elif action_id == "reject_task":
            # 差し戻しモーダルを開く
            await slack_service.open_rejection_modal(trigger_id, task_id)
            return JSONResponse(content={})

        elif action_id == "open_revision_modal":
            try:
                value_data = json.loads(action.get("value", "{}"))
            except json.JSONDecodeError:
                print("⚠️ Invalid payload for open_revision_modal")
                return JSONResponse(content={})

            task_id = value_data.get("task_id")
            if not task_id:
                return JSONResponse(content={})

            task = await task_service.task_repository.find_by_id(task_id)
            if not task:
                try:
                    dm = slack_service.client.conversations_open(users=user_id)
                    slack_service.client.chat_postMessage(
                        channel=dm["channel"]["id"],
                        text="タスク情報が見つかりませんでした。新しく依頼を作成してください。",
                    )
                except Exception as dm_error:
                    print(f"⚠️ Failed to notify requester about missing task: {dm_error}")
                return JSONResponse(content={})

            if task.requester_slack_id != user_id:
                try:
                    dm = slack_service.client.conversations_open(users=user_id)
                    slack_service.client.chat_postMessage(
                        channel=dm["channel"]["id"],
                        text="この差し戻しタスクを修正できるのは依頼者のみです。",
                    )
                except Exception as dm_error:
                    print(f"⚠️ Failed to notify non-requester user: {dm_error}")
                return JSONResponse(content={})

            source_channel = payload.get("channel", {}).get("id")
            message = payload.get("message", {})
            source_ts = message.get("ts")

            metadata: Dict[str, Any] = {}
            if source_channel:
                metadata["source_channel"] = source_channel
            if source_ts:
                metadata["source_ts"] = source_ts
            if task.rejection_reason:
                metadata["rejection_reason"] = task.rejection_reason

            await slack_service.open_task_revision_modal(
                trigger_id=trigger_id,
                task=task,
                requester_slack_id=user_id,
                private_metadata=metadata,
                rejection_reason=task.rejection_reason,
            )

            return JSONResponse(content={})

        elif action_id == "mark_reminder_read":
            try:
                value_data = json.loads(action.get("value", "{}"))
            except json.JSONDecodeError:
                print("⚠️ Invalid payload for mark_reminder_read")
                return JSONResponse(content={})

            page_id = value_data.get("page_id")
            stage = value_data.get("stage")
            channel_id = payload.get("channel", {}).get("id")
            message = payload.get("message", {})
            message_ts = message.get("ts")
            message_blocks = message.get("blocks", [])

            import asyncio

            async def run_mark_read():
                if not page_id:
                    try:
                        dm = slack_service.client.conversations_open(users=user_id)
                        slack_service.client.chat_postMessage(
                            channel=dm["channel"]["id"],
                            text="タスク情報の取得に失敗しました。管理者に連絡してください。",
                        )
                    except Exception as dm_error:
                        print(f"⚠️ Failed to notify user about missing page_id: {dm_error}")
                    return

                read_time = datetime.now(JST)
                try:
                    await notion_service.mark_reminder_read(page_id, read_time, stage)
                    snapshot = await notion_service.get_task_snapshot(page_id)
                    user_info = await slack_service.get_user_info(user_id)
                    actor_email = user_info.get("profile", {}).get("email") if user_info else None
                    stage_label = REMINDER_STAGE_LABELS.get(stage, stage or "リマインド")
                    detail = f"{stage_label} を既読 ({read_time.astimezone().strftime('%Y-%m-%d %H:%M')})"
                    await notion_service.record_audit_log(
                        task_page_id=page_id,
                        event_type="リマインド既読",
                        detail=detail,
                        actor_email=actor_email,
                    )

                    if channel_id and message_ts and message_blocks:
                        try:
                            updated_text = f"✅ <@{user_id}> が{stage_label}を既読 ({_format_datetime_text(datetime.now(JST))})"
                            updated_blocks = _mark_read_update_blocks(message_blocks, updated_text)
                            slack_service.client.chat_update(
                                channel=channel_id,
                                ts=message_ts,
                                blocks=updated_blocks,
                                text=updated_text,
                            )
                        except Exception as update_error:
                            print(f"⚠️ Failed to update reminder message: {update_error}")

                except Exception as ack_error:
                    print(f"⚠️ Failed to mark reminder as read: {ack_error}")

            asyncio.create_task(run_mark_read())
            return JSONResponse(content={})

        elif action_id == "open_extension_modal":
            try:
                value_data = json.loads(action.get("value", "{}"))
            except json.JSONDecodeError:
                print("⚠️ Invalid payload for open_extension_modal")
                return JSONResponse(content={})

            page_id = value_data.get("page_id")
            stage = value_data.get("stage")
            requester_slack_id = value_data.get("requester_slack_id")

            snapshot = await notion_service.get_task_snapshot(page_id)
            if not snapshot:
                try:
                    dm = slack_service.client.conversations_open(users=user_id)
                    slack_service.client.chat_postMessage(
                        channel=dm["channel"]["id"],
                        text="Notionのタスク情報を取得できませんでした。少し待って再試行してください。",
                    )
                except Exception as dm_error:
                    print(f"⚠️ Failed to notify user about missing snapshot: {dm_error}")
                return JSONResponse(content={})

            if not requester_slack_id and snapshot.requester_email:
                try:
                    requester_user = await slack_user_repository.find_by_email(Email(snapshot.requester_email))
                    if requester_user:
                        requester_slack_id = str(requester_user.user_id)
                except Exception as lookup_error:
                    print(f"⚠️ Failed to lookup requester Slack ID: {lookup_error}")

            if not requester_slack_id:
                try:
                    dm = slack_service.client.conversations_open(users=user_id)
                    slack_service.client.chat_postMessage(
                        channel=dm["channel"]["id"],
                        text="依頼者のSlackアカウントが見つからず、延期申請を開始できません。管理者にお問い合わせください。",
                    )
                except Exception as dm_error:
                    print(f"⚠️ Failed to notify user about missing requester Slack ID: {dm_error}")
                return JSONResponse(content={})

            await slack_service.open_extension_modal(
                trigger_id=trigger_id,
                snapshot=snapshot,
                stage=stage,
                requester_slack_id=requester_slack_id,
                assignee_slack_id=user_id,
            )
            return JSONResponse(content={})

        elif action_id == "open_completion_modal":
            try:
                value_data = json.loads(action.get("value", "{}"))
            except json.JSONDecodeError:
                print("⚠️ Invalid payload for open_completion_modal")
                return JSONResponse(content={})

            page_id = value_data.get("page_id")
            stage = value_data.get("stage")
            requester_slack_id = value_data.get("requester_slack_id")

            snapshot = await notion_service.get_task_snapshot(page_id)
            if not snapshot:
                try:
                    dm = slack_service.client.conversations_open(users=user_id)
                    slack_service.client.chat_postMessage(
                        channel=dm["channel"]["id"],
                        text="Notionのタスク情報を取得できませんでした。しばらくして再試行してください。",
                    )
                except Exception as dm_error:
                    print(f"⚠️ Failed to notify user about missing snapshot: {dm_error}")
                return JSONResponse(content={})

            if not requester_slack_id and snapshot.requester_email:
                try:
                    requester_user = await slack_user_repository.find_by_email(Email(snapshot.requester_email))
                    if requester_user:
                        requester_slack_id = str(requester_user.user_id)
                except Exception as lookup_error:
                    print(f"⚠️ Failed to lookup requester Slack ID for completion modal: {lookup_error}")

            if not requester_slack_id:
                try:
                    dm = slack_service.client.conversations_open(users=user_id)
                    slack_service.client.chat_postMessage(
                        channel=dm["channel"]["id"],
                        text="依頼者のSlackアカウントが見つかりません。管理者にお問い合わせください。",
                    )
                except Exception as dm_error:
                    print(f"⚠️ Failed to notify user about missing requester Slack ID: {dm_error}")
                return JSONResponse(content={})

            await slack_service.open_completion_modal(
                trigger_id=trigger_id,
                snapshot=snapshot,
                stage=stage,
                requester_slack_id=requester_slack_id,
                assignee_slack_id=user_id,
            )
            return JSONResponse(content={})

        elif action_id == "approve_completion_request":
            try:
                value_data = json.loads(action.get("value", "{}"))
            except json.JSONDecodeError:
                print("⚠️ Invalid payload for approve_completion_request")
                return JSONResponse(content={})

            page_id = value_data.get("page_id")
            assignee_slack_id = value_data.get("assignee_slack_id")
            requester_slack_id = value_data.get("requester_slack_id", user_id)
            channel_id = payload.get("channel", {}).get("id")
            message = payload.get("message", {})
            message_ts = message.get("ts")
            message_blocks = message.get("blocks", [])

            import asyncio

            async def run_completion_approval():
                if not page_id:
                    return
                try:
                    snapshot = await notion_service.get_task_snapshot(page_id)
                    if not snapshot:
                        slack_service.client.chat_postMessage(
                            channel=slack_service.client.conversations_open(users=user_id)["channel"]["id"],
                            text="Notionのタスク情報を取得できず承認できませんでした。",
                        )
                        return

                    approval_time = datetime.now(JST)
                    requested_before_due = _requested_on_time(
                        snapshot.completion_requested_at if snapshot else None,
                        snapshot.due_date if snapshot else None,
                    )
                    eligible_for_overdue_points = getattr(snapshot, "status", None) == TASK_STATUS_APPROVED

                    await notion_service.approve_completion(
                        page_id,
                        approval_time,
                        requested_before_due,
                    )
                    await notion_service.update_task_status(page_id, "completed")

                    user_info = await slack_service.get_user_info(user_id)
                    actor_email = user_info.get("profile", {}).get("email") if user_info else None
                    await notion_service.record_audit_log(
                        task_page_id=page_id,
                        event_type="完了承認",
                        detail=f"完了承認 {approval_time.astimezone().strftime('%Y-%m-%d %H:%M')}",
                        actor_email=actor_email,
                    )

                    if channel_id and message_ts and message_blocks:
                        try:
                            updated_blocks = _replace_actions_with_context(
                                message_blocks,
                                f"✅ 完了を承認しました ({_format_datetime_text(datetime.now(JST))})",
                            )
                            slack_service.client.chat_update(
                                channel=channel_id,
                                ts=message_ts,
                                blocks=updated_blocks,
                                text="完了を承認しました",
                            )
                        except Exception as update_error:
                            print(f"⚠️ Failed to update completion approval message: {update_error}")

                    await slack_service.notify_completion_approved(
                        assignee_slack_id=assignee_slack_id,
                        requester_slack_id=requester_slack_id,
                        snapshot=snapshot,
                        approval_time=approval_time,
                    )

                    target_points = 1 if (eligible_for_overdue_points and not requested_before_due) else 0
                    refreshed_snapshot = await notion_service.get_task_snapshot(page_id)
                    snapshot_for_metrics = refreshed_snapshot or snapshot
                    await task_metrics_service.sync_snapshot(
                        snapshot_for_metrics,
                        overdue_points=target_points,
                    )
                    await task_metrics_service.refresh_assignee_summaries()

                except Exception as approval_error:
                    print(f"⚠️ Completion approval failed: {approval_error}")

            asyncio.create_task(run_completion_approval())
            return JSONResponse(content={})

        elif action_id == "reject_completion_request":
            try:
                value_data = json.loads(action.get("value", "{}"))
            except json.JSONDecodeError:
                print("⚠️ Invalid payload for reject_completion_request")
                return JSONResponse(content={})

            page_id = value_data.get("page_id")
            assignee_slack_id = value_data.get("assignee_slack_id")
            requester_slack_id = value_data.get("requester_slack_id", user_id)

            snapshot = await notion_service.get_task_snapshot(page_id)
            if not snapshot:
                slack_service.client.chat_postMessage(
                    channel=slack_service.client.conversations_open(users=user_id)["channel"]["id"],
                    text="Notionのタスク情報を取得できませんでした。",
                )
                return JSONResponse(content={})

            await slack_service.open_completion_reject_modal(
                trigger_id=trigger_id,
                snapshot=snapshot,
                assignee_slack_id=assignee_slack_id,
                requester_slack_id=requester_slack_id,
            )
            return JSONResponse(content={})

        elif action_id == "approve_extension_request":
            try:
                value_data = json.loads(action.get("value", "{}"))
            except json.JSONDecodeError:
                print("⚠️ Invalid payload for approve_extension_request")
                return JSONResponse(content={})

            page_id = value_data.get("page_id")
            assignee_slack_id = value_data.get("assignee_slack_id")
            requester_slack_id = value_data.get("requester_slack_id", user_id)
            channel_id = payload.get("channel", {}).get("id")
            message = payload.get("message", {})
            message_ts = message.get("ts")
            message_blocks = message.get("blocks", [])

            import asyncio

            async def run_extension_approval():
                if not page_id:
                    return
                try:
                    snapshot = await notion_service.get_task_snapshot(page_id)
                    if not snapshot or not snapshot.extension_requested_due:
                        info = "延期申請が見つからないため承認できませんでした。"
                        slack_service.client.chat_postMessage(
                            channel=slack_service.client.conversations_open(users=user_id)["channel"]["id"],
                            text=info,
                        )
                        return

                    approved_due = snapshot.extension_requested_due
                    previous_due = snapshot.due_date

                    await notion_service.approve_extension(page_id, approved_due)
                    user_info = await slack_service.get_user_info(user_id)
                    actor_email = user_info.get("profile", {}).get("email") if user_info else None
                    detail = (
                        f"延期承認: {_format_datetime_text(previous_due)} → {_format_datetime_text(approved_due)}"
                        if previous_due
                        else f"延期承認: 新期日 {_format_datetime_text(approved_due)}"
                    )
                    await notion_service.record_audit_log(
                        task_page_id=page_id,
                        event_type="延期承認",
                        detail=detail,
                        actor_email=actor_email,
                    )

                    updated_blocks = _replace_actions_with_context(
                        message_blocks,
                        f"✅ 延期を承認しました ({_format_datetime_text(datetime.now(JST))})",
                    ) if message_blocks else None

                    if channel_id and message_ts and updated_blocks:
                        try:
                            slack_service.client.chat_update(
                                channel=channel_id,
                                ts=message_ts,
                                blocks=updated_blocks,
                                text="延期を承認しました",
                            )
                        except Exception as update_error:
                            print(f"⚠️ Failed to update approval message: {update_error}")

                    await slack_service.notify_extension_approved(
                        assignee_slack_id=assignee_slack_id,
                        requester_slack_id=requester_slack_id,
                        snapshot=snapshot,
                        new_due=approved_due,
                    )

                    refreshed_snapshot = await notion_service.get_task_snapshot(page_id)
                    snapshot_for_metrics = refreshed_snapshot or snapshot
                    await task_metrics_service.sync_snapshot(
                        snapshot_for_metrics,
                        reminder_stage=snapshot_for_metrics.reminder_stage,
                    )
                    await task_metrics_service.refresh_assignee_summaries()

                except Exception as approval_error:
                    print(f"⚠️ Extension approval failed: {approval_error}")

            asyncio.create_task(run_extension_approval())
            return JSONResponse(content={})

        elif action_id == "reject_extension_request":
            try:
                value_data = json.loads(action.get("value", "{}"))
            except json.JSONDecodeError:
                print("⚠️ Invalid payload for reject_extension_request")
                return JSONResponse(content={})

            page_id = value_data.get("page_id")
            assignee_slack_id = value_data.get("assignee_slack_id")
            requester_slack_id = value_data.get("requester_slack_id", user_id)
            channel_id = payload.get("channel", {}).get("id")
            message = payload.get("message", {})
            message_ts = message.get("ts")
            message_blocks = message.get("blocks", [])

            import asyncio

            async def run_extension_rejection():
                if not page_id:
                    return
                try:
                    snapshot = await notion_service.get_task_snapshot(page_id)
                    await notion_service.reject_extension(page_id)
                    user_info = await slack_service.get_user_info(user_id)
                    actor_email = user_info.get("profile", {}).get("email") if user_info else None
                    await notion_service.record_audit_log(
                        task_page_id=page_id,
                        event_type="延期却下",
                        detail="依頼者が延期申請を却下しました",
                        actor_email=actor_email,
                    )

                    if channel_id and message_ts and message_blocks:
                        try:
                            updated_blocks = _replace_actions_with_context(
                                message_blocks,
                                f"⚠️ 延期申請を却下しました ({_format_datetime_text(datetime.now(JST))})",
                            )
                            slack_service.client.chat_update(
                                channel=channel_id,
                                ts=message_ts,
                                blocks=updated_blocks,
                                text="延期申請を却下しました",
                            )
                        except Exception as update_error:
                            print(f"⚠️ Failed to update rejection message: {update_error}")

                    await slack_service.notify_extension_rejected(
                        assignee_slack_id=assignee_slack_id,
                        requester_slack_id=requester_slack_id,
                        snapshot=snapshot,
                    )

                    refreshed_snapshot = await notion_service.get_task_snapshot(page_id)
                    snapshot_for_metrics = refreshed_snapshot or snapshot
                    await task_metrics_service.sync_snapshot(
                        snapshot_for_metrics,
                        reminder_stage=snapshot_for_metrics.reminder_stage,
                    )
                    await task_metrics_service.refresh_assignee_summaries()

                except Exception as rejection_error:
                    print(f"⚠️ Extension rejection failed: {rejection_error}")

            asyncio.create_task(run_extension_rejection())
            return JSONResponse(content={})

        elif action_id == "open_notion_page":
            # URLボタンはクライアント側で開かれるためACKのみ返す
            return JSONResponse(content={})

        elif action_id == "ai_enhance_button":
            # AI補完ボタンの処理: まず即時ACKし、その後非同期で更新
            print(f"🤖 AI補完ボタン押下: user_id={user_id}, action_id={action_id}")
            return await handle_ai_enhancement_async(payload, trigger_id, view_id, user_id)
        
        else:
            print(f"⚠️ Unknown action_id: {action_id}")
            return JSONResponse(content={"response_action": "errors", "errors": {"general": f"不明なアクション: {action_id}"}})

    elif interaction_type == "view_submission":
        # モーダル送信の処理
        view = payload["view"]
        callback_id = view["callback_id"]

        if callback_id == "create_task_modal":
            try:
                # タスク作成モーダルの処理（非同期化）
                values = view["state"]["values"]
                private_metadata = json.loads(view.get("private_metadata", "{}"))
                view_id = view.get("id")
                
                # デバッグ: 受信したデータ構造を確認
                print(f"🔍 Modal values keys: {list(values.keys())}")
                for key, value in values.items():
                    print(f"  {key}: {list(value.keys())}")

                # 新しいフィールドを取得（存在しない場合はデフォルト値）
                task_type = "社内タスク"  # デフォルト値
                if "task_type_block" in values and "task_type_select" in values["task_type_block"]:
                    task_type_data = values["task_type_block"]["task_type_select"].get("selected_option")
                    if task_type_data:
                        task_type = task_type_data["value"]
                
                urgency = "1週間以内"  # デフォルト値
                if "urgency_block" in values and "urgency_select" in values["urgency_block"]:
                    urgency_data = values["urgency_block"]["urgency_select"].get("selected_option")
                    if urgency_data:
                        urgency = urgency_data["value"]
                
                print(f"🎯 取得したフィールド: task_type={task_type}, urgency={urgency}")
                
                # リッチテキストを取得（オプショナル）
                description_data = None
                if "description_block" in values and values["description_block"]["description_input"].get("rich_text_value"):
                    description_rich = values["description_block"]["description_input"]["rich_text_value"]
                    description_data = description_rich

                # 納期をdatetimeに変換
                due_date_unix = values["due_date_block"]["due_date_picker"]["selected_date_time"]
                due_date = datetime.fromtimestamp(due_date_unix, tz=timezone.utc).astimezone(JST)

                dto = CreateTaskRequestDto(
                    requester_slack_id=private_metadata["requester_id"],
                    assignee_slack_id=values["assignee_block"]["assignee_select"]["selected_option"]["value"],
                    title=values["title_block"]["title_input"]["value"],
                    description=description_data,  # リッチテキストデータを渡す（オプショナル）
                    due_date=due_date,
                    task_type=task_type,
                    urgency=urgency,
                )

                # 1) 即座にローディング画面を返す（3秒制限回避）
                loading_view = {
                    "type": "modal",
                    "callback_id": "task_creating_loading",
                    "title": {"type": "plain_text", "text": "タスク依頼作成中"},
                    "close": {"type": "plain_text", "text": "キャンセル"},
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": "⏳ *タスク依頼を作成しています...*\n\nしばらくお待ちください。"
                            }
                        }
                    ]
                }

                # 2) バックグラウンドでタスク作成処理を実行
                import asyncio
                
                async def run_task_creation():
                    try:
                        print("🔄 バックグラウンドタスク作成開始...")
                        await task_service.create_task_request(dto)
                        print("✅ タスク作成成功")
                        
                        # 成功時: 成功メッセージを表示
                        if view_id:
                            try:
                                success_view = {
                                    "type": "modal",
                                    "callback_id": "task_created_success",
                                    "title": {"type": "plain_text", "text": "タスク依頼完了"},
                                    "close": {"type": "plain_text", "text": "閉じる"},
                                    "blocks": [
                                        {
                                            "type": "section",
                                            "text": {
                                                "type": "mrkdwn",
                                                "text": f"✅ *タスク依頼が正常に送信されました*\n\n*件名:* {dto.title}\n*依頼先:* <@{dto.assignee_slack_id}>\n\n承認待ちです。結果はDMでお知らせします。"
                                            }
                                        }
                                    ]
                                }
                                slack_service.client.views_update(view_id=view_id, view=success_view)
                            except Exception as e:
                                print(f"⚠️ 成功メッセージ表示エラー: {e}")
                                
                    except Exception as e:
                        print(f"❌ タスク作成エラー: {e}")
                        
                        # 失敗時: 元のフォームに戻る（値を保持）
                        if view_id:
                            try:
                                # 元のフォーム構造を再構築
                                error_view = {
                                    "type": "modal",
                                    "callback_id": "create_task_modal",
                                    "title": {"type": "plain_text", "text": "タスク依頼作成"},
                                    "submit": {"type": "plain_text", "text": "作成"},
                                    "close": {"type": "plain_text", "text": "キャンセル"},
                                    "blocks": [
                                        {
                                            "type": "section",
                                            "text": {
                                                "type": "mrkdwn",
                                                "text": f"❌ *エラーが発生しました*\n{str(e)}\n\n下記のフォームで再度お試しください："
                                            }
                                        },
                                        # 元のフォームブロックを再構築（値を保持）
                                        *_rebuild_task_form_blocks_with_values(values, task_type, urgency)
                                    ],
                                    "private_metadata": json.dumps(private_metadata)
                                }
                                slack_service.client.views_update(view_id=view_id, view=error_view)
                            except Exception as update_error:
                                print(f"⚠️ エラーメッセージ表示失敗: {update_error}")

                # 非同期タスクを開始
                asyncio.create_task(run_task_creation())

                # 即座にローディング画面を返す
                return JSONResponse(
                    content={
                        "response_action": "update",
                        "view": loading_view
                    }
                )
            except ValueError as e:
                # タスク作成エラーの場合
                return JSONResponse(
                    content={
                        "response_action": "errors",
                        "errors": {
                            "title_block": f"エラー: {str(e)}"
                        }
                    }
                )

        elif callback_id == "revise_task_modal":
            values = view["state"]["values"]
            private_metadata = json.loads(view.get("private_metadata", "{}"))
            view_id = view.get("id")

            task_id = private_metadata.get("task_id")
            requester_slack_id = private_metadata.get("requester_slack_id") or payload.get("user", {}).get("id")
            if not task_id or not requester_slack_id:
                return JSONResponse(content={"response_action": "clear"})

            assignee_option = values.get("assignee_block", {}).get("assignee_select", {}).get("selected_option")
            title_value = values.get("title_block", {}).get("title_input", {}).get("value")
            due_picker = values.get("due_date_block", {}).get("due_date_picker", {})

            if not assignee_option or not title_value or not due_picker.get("selected_date_time"):
                errors: Dict[str, Optional[str]] = {}
                if not assignee_option:
                    errors["assignee_block"] = "依頼先を選択してください"
                if not title_value:
                    errors["title_block"] = "件名を入力してください"
                if not due_picker.get("selected_date_time"):
                    errors["due_date_block"] = "納期を選択してください"
                return JSONResponse(
                    content={
                        "response_action": "errors",
                        "errors": errors,
                    }
                )

            task_type_option = values.get("task_type_block", {}).get("task_type_select", {}).get("selected_option")
            urgency_option = values.get("urgency_block", {}).get("urgency_select", {}).get("selected_option")

            task_type = task_type_option["value"] if task_type_option else "社内タスク"
            urgency = urgency_option["value"] if urgency_option else "1週間以内"

            description_data = None
            description_payload = values.get("description_block", {}).get("description_input", {})
            if description_payload.get("rich_text_value"):
                description_data = description_payload.get("rich_text_value")

            due_date = datetime.fromtimestamp(due_picker["selected_date_time"], tz=timezone.utc).astimezone(JST)

            dto = ReviseTaskRequestDto(
                task_id=task_id,
                requester_slack_id=requester_slack_id,
                assignee_slack_id=assignee_option["value"],
                title=title_value,
                description=description_data,
                due_date=due_date,
                task_type=task_type,
                urgency=urgency,
            )

            loading_view = {
                "type": "modal",
                "callback_id": "revise_task_modal_loading",
                "title": {"type": "plain_text", "text": "タスク依頼を修正"},
                "close": {"type": "plain_text", "text": "閉じる"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "⏳ *修正したタスクを送信しています...*\n数秒お待ちください。",
                        },
                    }
                ],
            }

            source_channel = private_metadata.get("source_channel")
            source_ts = private_metadata.get("source_ts")

            import asyncio

            async def run_task_revision():
                try:
                    response = await task_service.revise_task_request(dto)

                    if source_channel and source_ts:
                        try:
                            formatted_due = _format_datetime_text(due_date)
                            updated_blocks = [
                                {
                                    "type": "header",
                                    "text": {"type": "plain_text", "text": "✏️ タスクを修正して再送信しました"},
                                },
                                {
                                    "type": "section",
                                    "text": {
                                        "type": "mrkdwn",
                                        "text": f"*件名:* {response.title}\n*依頼先:* <@{dto.assignee_slack_id}>\n*納期:* {formatted_due}",
                                    },
                                },
                                {
                                    "type": "context",
                                    "elements": [
                                        {"type": "mrkdwn", "text": "修正内容を送信し、再び承認待ちになりました。"},
                                    ],
                                },
                            ]

                            slack_service.client.chat_update(
                                channel=source_channel,
                                ts=source_ts,
                                text="タスクを修正して再送しました",
                                blocks=updated_blocks,
                            )
                        except Exception as update_error:
                            print(f"⚠️ Failed to update rejection message after revision: {update_error}")

                    if view_id:
                        try:
                            success_view = {
                                "type": "modal",
                                "callback_id": "revise_task_modal_success",
                                "title": {"type": "plain_text", "text": "タスク依頼を修正"},
                                "close": {"type": "plain_text", "text": "閉じる"},
                                "blocks": [
                                    {
                                        "type": "section",
                                        "text": {
                                            "type": "mrkdwn",
                                            "text": "✅ *修正したタスクを送信しました*\n承認結果は依頼先からの通知をお待ちください。",
                                        },
                                    }
                                ],
                            }
                            slack_service.client.views_update(view_id=view_id, view=success_view)
                        except Exception as update_error:
                            print(f"⚠️ 修正成功ビューの表示に失敗: {update_error}")

                except Exception as revision_error:
                    print(f"⚠️ Task revision failed: {revision_error}")
                    if view_id:
                        try:
                            error_view = {
                                "type": "modal",
                                "callback_id": "revise_task_modal_error",
                                "title": {"type": "plain_text", "text": "タスク依頼を修正"},
                                "close": {"type": "plain_text", "text": "閉じる"},
                                "blocks": [
                                    {
                                        "type": "section",
                                        "text": {
                                            "type": "mrkdwn",
                                            "text": f"⚠️ *修正したタスクの送信に失敗しました*\n{revision_error}",
                                        },
                                    }
                                ],
                            }
                            slack_service.client.views_update(view_id=view_id, view=error_view)
                        except Exception as update_error:
                            print(f"⚠️ 修正エラービューの表示に失敗: {update_error}")

            asyncio.create_task(run_task_revision())

            return JSONResponse(
                content={
                    "response_action": "update",
                    "view": loading_view,
                }
            )

        elif callback_id == "reject_task_modal":
            try:
                # 差し戻しモーダルの処理（非同期化）
                values = view["state"]["values"]
                private_metadata = json.loads(view.get("private_metadata", "{}"))
                view_id = view.get("id")
                task_id = private_metadata["task_id"]
                reason = values["reason_block"]["reason_input"]["value"]

                # 即座にローディング表示
                loading_view = {
                    "type": "modal",
                    "callback_id": "task_rejecting_loading",
                    "title": {"type": "plain_text", "text": "差し戻し中"},
                    "close": {"type": "plain_text", "text": "キャンセル"},
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": "⏳ *タスクを差し戻しています...*\n\nしばらくお待ちください。"
                            }
                        }
                    ]
                }
                
                # バックグラウンドで差し戻し処理を実行
                import asyncio
                
                async def run_rejection():
                    try:
                        dto = TaskApprovalDto(
                            task_id=task_id,
                            action="reject",
                            rejection_reason=reason,
                        )
                        await task_service.handle_task_approval(dto)
                        print("✅ 差し戻し処理成功")
                        
                        # 成功時：モーダルを閉じる
                        if view_id:
                            try:
                                success_view = {
                                    "type": "modal",
                                    "callback_id": "task_rejected_success",
                                    "title": {"type": "plain_text", "text": "差し戻し完了"},
                                    "close": {"type": "plain_text", "text": "閉じる"},
                                    "blocks": [
                                        {
                                            "type": "section",
                                            "text": {
                                                "type": "mrkdwn",
                                                "text": f"✅ *タスクを差し戻しました*\n\n*理由:* {reason}"
                                            }
                                        }
                                    ]
                                }
                                slack_service.client.views_update(view_id=view_id, view=success_view)
                            except Exception as update_error:
                                print(f"⚠️ 成功メッセージ表示エラー: {update_error}")
                                
                    except Exception as e:
                        print(f"❌ 差し戻し処理エラー: {e}")
                        
                        # エラー時：元のフォームに戻る（値を保持）
                        if view_id:
                            try:
                                error_view = {
                                    "type": "modal",
                                    "callback_id": "reject_task_modal",
                                    "title": {"type": "plain_text", "text": "差し戻し理由"},
                                    "submit": {"type": "plain_text", "text": "差し戻す"},
                                    "close": {"type": "plain_text", "text": "キャンセル"},
                                    "blocks": [
                                        {
                                            "type": "section",
                                            "text": {
                                                "type": "mrkdwn",
                                                "text": f"❌ *エラーが発生しました*\n{str(e)}\n\n下記のフォームで再度お試しください："
                                            }
                                        },
                                        {
                                            "type": "input",
                                            "block_id": "reason_block",
                                            "element": {
                                                "type": "plain_text_input",
                                                "multiline": True,
                                                "action_id": "reason_input",
                                                "placeholder": {"type": "plain_text", "text": "差し戻し理由を入力してください"},
                                                "initial_value": reason  # 入力した理由を保持
                                            },
                                            "label": {"type": "plain_text", "text": "差し戻し理由"},
                                        },
                                    ],
                                    "private_metadata": json.dumps(private_metadata)
                                }
                                slack_service.client.views_update(view_id=view_id, view=error_view)
                            except Exception as update_error:
                                print(f"⚠️ エラーメッセージ表示失敗: {update_error}")
                
                # 非同期タスクを開始
                asyncio.create_task(run_rejection())
                
                # 即座にローディング画面を返す
                return JSONResponse(
                    content={
                        "response_action": "update",
                        "view": loading_view
                    }
                )
            except ValueError as e:
                # エラーレスポンスを返す
                return JSONResponse(
                    content={
                        "response_action": "errors",
                        "errors": {
                            "reason_block": f"エラー: {str(e)}"
                        }
                    }
                )
        
        elif callback_id == "ai_additional_info_modal":
            # 追加情報入力モーダルの処理
            return await handle_additional_info_submission(payload)
            
        elif callback_id == "ai_content_confirmation_modal":
            # 内容確認モーダルの処理
            return await handle_content_confirmation(payload)

        elif callback_id == "extension_request_modal":
            values = view["state"]["values"]
            private_metadata = json.loads(view.get("private_metadata", "{}"))

            due_data = values.get("new_due_block", {}).get("new_due_picker", {})
            selected_ts = due_data.get("selected_date_time")
            if not selected_ts:
                return JSONResponse(
                    content={
                        "response_action": "errors",
                        "errors": {
                            "new_due_block": "新しい納期を選択してください。",
                        },
                    }
                )

            reason = _get_text_input_value(values, "reason_block", "reason_input")
            if not reason:
                return JSONResponse(
                    content={
                        "response_action": "errors",
                        "errors": {
                            "reason_block": "延期理由を入力してください。",
                        },
                    }
                )

            requested_due = datetime.fromtimestamp(selected_ts, tz=timezone.utc).astimezone(JST)
            page_id = private_metadata.get("page_id")
            stage = private_metadata.get("stage")
            requester_slack_id = private_metadata.get("requester_slack_id")
            assignee_slack_id = private_metadata.get("assignee_slack_id")

            if not page_id:
                return JSONResponse(content={"response_action": "clear"})

            snapshot = await notion_service.get_task_snapshot(page_id)
            if not snapshot:
                return JSONResponse(
                    content={
                        "response_action": "errors",
                        "errors": {
                            "reason_block": "Notionデータの取得に失敗しました。再度お試しください。",
                        },
                    }
                )

            await notion_service.set_extension_request(page_id, requested_due, reason)
            await notion_service.record_audit_log(
                task_page_id=page_id,
                event_type="延期申請",
                detail=f"{_format_datetime_text(snapshot.due_date)} → {_format_datetime_text(requested_due)}\n理由: {reason}",
                actor_email=snapshot.assignee_email,
            )

            target_requester_slack_id = requester_slack_id
            if not target_requester_slack_id and snapshot.requester_email:
                try:
                    slack_user = await slack_user_repository.find_by_email(Email(snapshot.requester_email))
                    if slack_user:
                        target_requester_slack_id = str(slack_user.user_id)
                except Exception as lookup_error:
                    print(f"⚠️ Failed to lookup requester Slack ID during extension submission: {lookup_error}")

            if target_requester_slack_id:
                try:
                    await slack_service.send_extension_request_to_requester(
                        requester_slack_id=target_requester_slack_id,
                        assignee_slack_id=assignee_slack_id,
                        snapshot=snapshot,
                        requested_due=requested_due,
                        reason=reason,
                    )
                except Exception as send_error:
                    print(f"⚠️ Failed to send extension approval request: {send_error}")
            else:
                print("⚠️ Requester Slack ID not resolved. Extension approval request not delivered.")

            if assignee_slack_id:
                await slack_service.notify_extension_request_submitted(
                    assignee_slack_id=assignee_slack_id,
                    requested_due=requested_due,
                )

            return JSONResponse(content={})

        elif callback_id == "completion_request_modal":
            values = view["state"]["values"]
            private_metadata = json.loads(view.get("private_metadata", "{}"))
            require_reason = private_metadata.get("require_reason", False)

            note = _get_text_input_value(values, "note_block", "note_input")

            if require_reason and not note:
                return JSONResponse(
                    content={
                        "response_action": "errors",
                        "errors": {"note_block": "遅延理由を入力してください"},
                    }
                )

            page_id = private_metadata.get("page_id")
            requester_slack_id = private_metadata.get("requester_slack_id")
            assignee_slack_id = private_metadata.get("assignee_slack_id")
            view_id = view.get("id")

            loading_view = {
                "type": "modal",
                "callback_id": "completion_request_loading",
                "title": {"type": "plain_text", "text": "完了申請"},
                "close": {"type": "plain_text", "text": "閉じる"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "⏳ *完了申請を送信しています...*\n数秒お待ちください。"
                        }
                    }
                ]
            }

            import asyncio

            async def run_completion_request():
                requested_at = datetime.now(JST)
                try:
                    snapshot = await notion_service.get_task_snapshot(page_id)
                    if not snapshot:
                        raise ValueError("Notionタスクが取得できませんでした")

                    resolved_requester = requester_slack_id
                    if not resolved_requester and snapshot.requester_email:
                        requester_user = await slack_user_repository.find_by_email(Email(snapshot.requester_email))
                        if requester_user:
                            resolved_requester = str(requester_user.user_id)

                    if not resolved_requester:
                        raise ValueError("依頼者のSlackアカウントが見つかりません")

                    requested_before_due = _requested_on_time(requested_at, snapshot.due_date)
                    eligible_for_overdue_points = getattr(snapshot, "status", None) == TASK_STATUS_APPROVED

                    await notion_service.request_completion(
                        page_id=page_id,
                        request_time=requested_at,
                        note=note,
                        requested_before_due=requested_before_due,
                    )

                    target_points = 1 if (eligible_for_overdue_points and not requested_before_due) else 0
                    refreshed_snapshot = await notion_service.get_task_snapshot(page_id)
                    snapshot_for_metrics = refreshed_snapshot or snapshot
                    await task_metrics_service.sync_snapshot(
                        snapshot_for_metrics,
                        overdue_points=target_points,
                    )
                    await task_metrics_service.refresh_assignee_summaries()

                    await notion_service.record_audit_log(
                        task_page_id=page_id,
                        event_type="完了申請",
                        detail=f"完了日時: {_format_datetime_text(requested_at)}\nメモ: {note or '（なし）'}",
                        actor_email=snapshot.assignee_email,
                    )

                    await slack_service.send_completion_request_to_requester(
                        requester_slack_id=resolved_requester,
                        assignee_slack_id=assignee_slack_id,
                        snapshot=snapshot,
                        completion_note=note,
                        requested_at=requested_at,
                        overdue=not requested_before_due,
                    )

                    if assignee_slack_id:
                        await slack_service.notify_completion_request_submitted(assignee_slack_id)

                    if view_id:
                        try:
                            success_view = {
                                "type": "modal",
                                "callback_id": "completion_request_success",
                                "title": {"type": "plain_text", "text": "完了申請"},
                                "close": {"type": "plain_text", "text": "閉じる"},
                                "blocks": [
                                    {
                                        "type": "section",
                                        "text": {
                                            "type": "mrkdwn",
                                            "text": f"✅ *完了申請を送信しました*\n承認結果は依頼者からの通知をお待ちください。"
                                        }
                                    }
                                ]
                            }
                            slack_service.client.views_update(view_id=view_id, view=success_view)
                        except Exception as update_error:
                            print(f"⚠️ 完了申請成功ビューの表示に失敗: {update_error}")

                except Exception as req_error:
                    print(f"⚠️ Completion request failed: {req_error}")
                    if view_id:
                        try:
                            error_view = {
                                "type": "modal",
                                "callback_id": "completion_request_error",
                                "title": {"type": "plain_text", "text": "完了申請"},
                                "close": {"type": "plain_text", "text": "閉じる"},
                                "blocks": [
                                    {
                                        "type": "section",
                                        "text": {
                                            "type": "mrkdwn",
                                            "text": f"⚠️ *完了申請に失敗しました*\n{req_error}"
                                        }
                                    }
                                ]
                            }
                            slack_service.client.views_update(view_id=view_id, view=error_view)
                        except Exception as update_error:
                            print(f"⚠️ 完了申請エラービューの表示に失敗: {update_error}")

            asyncio.create_task(run_completion_request())

            return JSONResponse(
                content={
                    "response_action": "update",
                    "view": loading_view,
                }
            )

        elif callback_id == "completion_reject_modal":
            values = view["state"]["values"]
            private_metadata = json.loads(view.get("private_metadata", "{}"))

            new_due_ts = values.get("new_due_block", {}).get("new_due_picker", {}).get("selected_date_time")
            reason = _get_text_input_value(values, "reason_block", "reason_input")

            if not new_due_ts:
                return JSONResponse(
                    content={
                        "response_action": "errors",
                        "errors": {"new_due_block": "新しい納期を選択してください"},
                    }
                )

            if not reason:
                return JSONResponse(
                    content={
                        "response_action": "errors",
                        "errors": {"reason_block": "却下理由を入力してください"},
                    }
                )

            page_id = private_metadata.get("page_id")
            assignee_slack_id = private_metadata.get("assignee_slack_id")
            requester_slack_id = private_metadata.get("requester_slack_id") or payload.get("user", {}).get("id")
            new_due = datetime.fromtimestamp(new_due_ts, tz=timezone.utc).astimezone(JST)
            view_id = view.get("id")

            loading_view = {
                "type": "modal",
                "callback_id": "completion_reject_loading",
                "title": {"type": "plain_text", "text": "完了却下"},
                "close": {"type": "plain_text", "text": "閉じる"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "⏳ *完了申請を却下しています...*\n数秒お待ちください。"
                        }
                    }
                ]
            }

            import asyncio

            async def run_completion_rejection():
                try:
                    snapshot = await notion_service.get_task_snapshot(page_id)

                    await notion_service.reject_completion(page_id, new_due, reason)
                    await notion_service.record_audit_log(
                        task_page_id=page_id,
                        event_type="完了却下",
                        detail=f"新しい納期: {_format_datetime_text(new_due)}\n理由: {reason}",
                        actor_email=snapshot.requester_email if snapshot else None,
                    )

                    if snapshot:
                        await slack_service.notify_completion_rejected(
                            assignee_slack_id=assignee_slack_id,
                            requester_slack_id=requester_slack_id,
                            snapshot=snapshot,
                            reason=reason,
                            new_due=new_due,
                        )

                    if view_id:
                        try:
                            success_view = {
                                "type": "modal",
                                "callback_id": "completion_reject_success",
                                "title": {"type": "plain_text", "text": "完了却下"},
                                "close": {"type": "plain_text", "text": "閉じる"},
                                "blocks": [
                                    {
                                        "type": "section",
                                        "text": {
                                            "type": "mrkdwn",
                                            "text": f"⚠️ *完了申請を却下しました*\n新しい納期: {_format_datetime_text(new_due)}"
                                        }
                                    }
                                ]
                            }
                            slack_service.client.views_update(view_id=view_id, view=success_view)
                        except Exception as update_error:
                            print(f"⚠️ 完了却下成功ビューの表示に失敗: {update_error}")

                except Exception as reject_error:
                    print(f"⚠️ Completion rejection failed: {reject_error}")
                    if view_id:
                        try:
                            error_view = {
                                "type": "modal",
                                "callback_id": "completion_reject_modal",
                                "title": {"type": "plain_text", "text": "完了却下"},
                                "submit": {"type": "plain_text", "text": "送信"},
                                "close": {"type": "plain_text", "text": "キャンセル"},
                                "blocks": view.get("blocks", []),
                                "private_metadata": view.get("private_metadata", "{}"),
                            }
                            slack_service.client.views_update(view_id=view_id, view=error_view)
                        except Exception as update_error:
                            print(f"⚠️ 完了却下エラービューの表示に失敗: {update_error}")

            asyncio.create_task(run_completion_rejection())

            return JSONResponse(
                content={
                    "response_action": "update",
                    "view": loading_view,
                }
            )

        else:
            print(f"⚠️ Unknown callback_id: {callback_id}")

    print(f"⚠️ Unhandled interaction_type: {interaction_type}")
    return JSONResponse(content={})


def _replace_actions_with_context(blocks: List[Dict[str, Any]], text: str) -> List[Dict[str, Any]]:
    updated_blocks: List[Dict[str, Any]] = []
    replaced = False
    for block in blocks:
        if not replaced and block.get("type") == "actions":
            updated_blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": text,
                    }
                ],
            })
            replaced = True
        else:
            updated_blocks.append(block)

    if not replaced:
        updated_blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": text,
                }
            ],
        })

    return updated_blocks


def _mark_read_update_blocks(blocks: List[Dict[str, Any]], text: str) -> List[Dict[str, Any]]:
    updated: List[Dict[str, Any]] = []
    context_added = False

    for block in blocks:
        if block.get("type") == "actions":
            elements = block.get("elements", [])
            remaining = [el for el in elements if el.get("action_id") != "mark_reminder_read"]

            if remaining:
                updated.append({**block, "elements": remaining})
            if not context_added:
                updated.append(
                    {
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": text}],
                    }
                )
                context_added = True
        else:
            updated.append(block)

    if not context_added:
        updated.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": text}],
            }
        )

    return updated


def _format_datetime_text(value: Optional[datetime]) -> str:
    if not value:
        return "-"
    if value.tzinfo:
        localized = value.astimezone(JST)
    else:
        localized = value.replace(tzinfo=JST)
    return localized.strftime("%Y-%m-%d %H:%M")


def _get_text_input_value(values: Dict[str, Any], block_id: str, action_id: str) -> str:
    block_state = values.get(block_id)
    if not isinstance(block_state, dict):
        return ""
    action_state = block_state.get(action_id)
    if not isinstance(action_state, dict):
        return ""
    value = action_state.get("value")
    if isinstance(value, str):
        return value.strip()
    return ""


def _to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if not dt:
        return None
    if dt.tzinfo:
        return dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=JST).astimezone(timezone.utc)


def _requested_on_time(requested_at: Optional[datetime], due: Optional[datetime]) -> bool:
    req_utc = _to_utc(requested_at)
    due_utc = _to_utc(due)
    if not req_utc or not due_utc:
        return False
    return req_utc <= due_utc


def determine_reminder_stage(snapshot, reference_time: datetime) -> Optional[str]:
    """リマインド対象ステージを判定"""
    task_status = getattr(snapshot, "status", None)
    if task_status == TASK_STATUS_PENDING:
        return REMINDER_STAGE_PENDING_APPROVAL

    if snapshot.completion_status in {COMPLETION_STATUS_REQUESTED, COMPLETION_STATUS_APPROVED}:
        return None

    due = getattr(snapshot, "due_date", None)
    if not due:
        return None

    due_value = due.astimezone(timezone.utc) if due.tzinfo else due.replace(tzinfo=timezone.utc)
    now_value = reference_time

    if snapshot.extension_status == EXTENSION_STATUS_PENDING:
        return None

    due_date_only = due_value.date()
    today = now_value.date()

    if due_date_only > today:
        hours_until_due = (due_value - now_value).total_seconds() / 3600
        if hours_until_due <= 24:
            return REMINDER_STAGE_BEFORE
        return None

    if due_date_only == today:
        if (due_value - now_value).total_seconds() >= 0:
            return REMINDER_STAGE_DUE
        return REMINDER_STAGE_OVERDUE

    return REMINDER_STAGE_OVERDUE


def _should_clear_overdue_points(snapshot, reference_time: datetime) -> bool:
    """納期超過ポイントをクリアすべきかどうか判定"""
    due = getattr(snapshot, "due_date", None)
    due_utc = _to_utc(due)
    now_utc = _to_utc(reference_time)

    # 納期が存在せず、あるいは未来に再設定された場合はクリア
    if not due_utc or (now_utc and due_utc > now_utc):
        return True

    # タスクが承認待ちのままならポイントは付与しない
    if getattr(snapshot, "status", None) == TASK_STATUS_PENDING:
        return True

    completion_status = getattr(snapshot, "completion_status", None)
    if completion_status in {COMPLETION_STATUS_REQUESTED, COMPLETION_STATUS_APPROVED}:
        requested_at = getattr(snapshot, "completion_requested_at", None)
        if _requested_on_time(requested_at, due):
            return True

    return False


def _extract_plain_text_from_rich_text(rich_text: Dict[str, Any]) -> str:
    """リッチテキストからプレーンテキストを抽出"""
    text_parts = []

    for element in rich_text.get("elements", []):
        for item in element.get("elements", []):
            if item.get("type") == "text":
                text_parts.append(item.get("text", ""))
            elif item.get("type") == "link":
                text_parts.append(item.get("url", ""))

    return "".join(text_parts)


async def handle_ai_enhancement(payload: dict, trigger_id: str) -> JSONResponse:
    """[Deprecated] 互換用: 同期処理版（未使用）"""
    return JSONResponse(content={"response_action": "errors", "errors": {"ai_helper_section": "Deprecated handler"}}, status_code=200)


async def handle_ai_enhancement_async(payload: dict, trigger_id: str, view_id: Optional[str], user_id: str) -> JSONResponse:
    """AI補完処理（非同期化）: 3秒以内にACKして処理中表示 → 後でviews.update"""
    print(f"🚀 handle_ai_enhancement_async 開始: user_id={user_id}, view_id={view_id}")
    try:
        print(f"🔍 AI service check: ai_service={ai_service is not None}")
        if not ai_service:
            print("❌ AI service is None - GEMINI_API_KEY not configured")
            return JSONResponse(
                content={
                    "response_action": "errors",
                    "errors": {
                        "ai_helper_section": "AI機能が利用できません。GEMINI_API_KEYを設定してください。"
                    }
                },
                status_code=200
            )
        
        # 現在のモーダルの値を取得
        print("🔍 モーダル値取得中...")
        view = payload.get("view", {})
        values = view.get("state", {}).get("values", {})
        print(f"🔍 Values keys: {list(values.keys())}")
        
        # タイトルをチェック（必須条件）
        title = ""
        print("🔍 タイトル取得中...")
        if "title_block" in values:
            title = values["title_block"].get("title_input", {}).get("value", "")
        print(f"🔍 取得したタイトル: '{title}'")

        # titleがNoneの場合の処理
        if title is None:
            title = ""

        if not title.strip():
            print("❌ タイトルが空のためエラーを返します")
            return JSONResponse(
                content={
                    "response_action": "errors",
                    "errors": {
                        "title_block": "AI補完を使用するには、まずタイトルを入力してください。"
                    }
                },
                status_code=200
            )

        # 現在のタスク情報を収集
        print("🔍 TaskInfo作成中...")
        task_info = TaskInfo(title=title.strip())
        print(f"🔍 TaskInfo作成完了: {task_info.title}")
        
        # タスク種類
        if "task_type_block" in values:
            task_type_data = values["task_type_block"].get("task_type_select", {}).get("selected_option")
            if task_type_data:
                task_info.task_type = task_type_data["value"]
        
        # 緊急度
        if "urgency_block" in values:
            urgency_data = values["urgency_block"].get("urgency_select", {}).get("selected_option")
            if urgency_data:
                task_info.urgency = urgency_data["value"]
        
        # 納期
        if "due_date_block" in values:
            due_date_unix = values["due_date_block"].get("due_date_picker", {}).get("selected_date_time")
            if due_date_unix:
                due_date = datetime.fromtimestamp(due_date_unix, tz=timezone.utc).astimezone(JST)
                task_info.due_date = due_date.strftime('%Y年%m月%d日 %H:%M')
        
        # 現在の内容
        if "description_block" in values:
            current_desc = values["description_block"].get("description_input", {}).get("rich_text_value")
            if current_desc:
                task_info.current_description = convert_rich_text_to_plain_text(current_desc)
        
        # セッションIDの生成と管理
        pm_raw = view.get("private_metadata")
        pm = {}
        try:
            pm = json.loads(pm_raw) if pm_raw else {}
        except Exception:
            pm = {}

        # AI補完用の一意なセッションIDを生成（フォーム入力中のみ有効）
        # タイムスタンプを含めて一意性を確保
        import time
        session_id = f"ai_session_{user_id}_{int(time.time() * 1000)}"
        print(f"🔍 AI補完セッション開始: {session_id}")
        
        # 現在のフォーム値を全て保存
        current_values = {
            "assignee": None,
            "title": title,
            "due_date": None,
            "task_type": None,
            "urgency": None,
            "description": None
        }

        # 依頼先
        if "assignee_block" in values:
            assignee_data = values["assignee_block"].get("assignee_select", {}).get("selected_option")
            if assignee_data:
                current_values["assignee"] = assignee_data

        # 納期（Unix timestamp）
        if "due_date_block" in values:
            due_date_unix = values["due_date_block"].get("due_date_picker", {}).get("selected_date_time")
            if due_date_unix:
                current_values["due_date"] = due_date_unix

        # タスク種類
        if "task_type_block" in values:
            task_type_data = values["task_type_block"].get("task_type_select", {}).get("selected_option")
            if task_type_data:
                current_values["task_type"] = task_type_data

        # 緊急度
        if "urgency_block" in values:
            urgency_data = values["urgency_block"].get("urgency_select", {}).get("selected_option")
            if urgency_data:
                current_values["urgency"] = urgency_data

        # 内容（リッチテキスト）
        if "description_block" in values:
            current_desc = values["description_block"].get("description_input", {}).get("rich_text_value")
            if current_desc:
                current_values["description"] = current_desc

        # セッション情報を保存（private_metadataサイズ制限対策）
        requester_id = pm.get("requester_id")
        modal_sessions[session_id] = {
            "original_view": view,
            "current_values": current_values,
            "user_id": user_id,
            "trigger_id": trigger_id,
            "task_info": task_info,
            "view_id": view_id,
            "requester_id": requester_id,
        }

        # 1) まず即時ACK（処理中ビューに置換）
        print("🔍 処理中ビュー作成中...")
        processing_view = create_processing_view(session_id, title="AI補完 - 実行中", description="AIが内容を整理中です… しばらくお待ちください。")
        print("✅ 処理中ビュー作成完了")

        # 非同期でGemini処理 → 結果に応じてviews.update
        import asyncio
        print("🔍 非同期AI処理開始準備中...")

        async def run_analysis_and_update():
            try:
                print(f"🤖 AI分析処理開始: session_id={session_id}")
                # 新しいAI補完セッションを開始（古い会話履歴をクリア）
                print("🔍 AI履歴セッション開始中...")
                ai_service.history.start_new_session(session_id)
                print("🔍 AI分析実行中...")
                result = await ai_service.analyze_task_info(session_id, task_info)
                print(f"✅ AI分析完了: status={result.status}")
                if not view_id:
                    return
                if result.status == "insufficient_info":
                    new_view = create_additional_info_modal_view(session_id, result, requester_id)
                elif result.status == "ready_to_format":
                    modal_sessions[session_id]["generated_content"] = result.formatted_content
                    new_view = create_content_confirmation_modal_view(session_id, result, requester_id)
                else:
                    new_view = create_error_view(session_id, f"AI処理でエラーが発生しました: {result.message}")

                # private_metadata をマージして付与（requester_id維持 + session_id追加）
                base_pm = {}
                try:
                    base_pm = json.loads(view.get("private_metadata", "{}"))
                except Exception:
                    base_pm = {}
                base_pm["session_id"] = session_id
                new_view["private_metadata"] = json.dumps(base_pm)
                slack_service.client.views_update(view_id=view_id, view=new_view)
            except Exception as e:
                err_view = create_error_view(session_id, f"AI処理エラー: {str(e)}")
                try:
                    if view_id:
                        slack_service.client.views_update(view_id=view_id, view=err_view)
                except Exception:
                    pass

        print("🔍 非同期タスク作成中...")
        asyncio.create_task(run_analysis_and_update())
        print("✅ 非同期タスク作成完了")

        print("🔍 処理中ビューを返却中...")
        return JSONResponse(content={"response_action": "update", "view": processing_view}, status_code=200)
            
    except Exception as e:
        error_msg = str(e)
        print(f"❌ AI enhancement error: {e}")
        
        # trigger_id期限切れや特定のSlack APIエラーの場合
        if any(keyword in error_msg.lower() for keyword in ["expired_trigger_id", "trigger_expired", "expired"]):
            return JSONResponse(
                content={
                    "response_action": "errors",
                    "errors": {
                        "ai_helper_section": "⏰ AI処理に時間がかかりすぎました。処理を高速化してもう一度お試しください。"
                    }
                },
                status_code=200
            )
        
        return JSONResponse(
            content={
                "response_action": "errors",
                "errors": {
                    "ai_helper_section": f"AI処理でエラーが発生しました: {error_msg[:100]}..."
                }
            },
            status_code=200
        )


async def show_additional_info_modal(trigger_id: str, session_id: str, result: AIAnalysisResult, original_view: dict) -> JSONResponse:
    """[Deprecated] 非同期化により未使用。views.update を使用してください。"""
    return JSONResponse(content={}, status_code=200)


async def show_content_confirmation_modal(trigger_id: str, session_id: str, result: AIAnalysisResult, original_view: dict) -> JSONResponse:
    """[Deprecated] 非同期化により未使用。views.update を使用してください。"""
    return JSONResponse(content={}, status_code=200)


async def handle_additional_info_submission(payload: dict) -> JSONResponse:
    """追加情報入力モーダルの送信処理（非同期化: 即時ACK→views.update）"""
    try:
        if not ai_service:
            return JSONResponse(
                content={
                    "response_action": "errors",
                    "errors": {
                        "additional_info_block": "AI機能が利用できません。"
                    }
                },
                status_code=200
            )
        
        view = payload.get("view", {})
        values = view.get("state", {}).get("values", {})
        view_id = view.get("id")
        private_metadata = json.loads(view.get("private_metadata", "{}"))
        session_id = private_metadata.get("session_id")
        session_data = modal_sessions.get(session_id, {})
        requester_id = session_data.get("requester_id")
        additional_info = values["additional_info_block"]["additional_info_input"].get("value", "")

        print(f"🔍 追加情報入力セッション: {session_id}, 履歴数: {len(ai_service.history.get_conversation(session_id))}")

        if not additional_info.strip():
            return JSONResponse(
                content={
                    "response_action": "errors",
                    "errors": {
                        "additional_info_block": "追加情報を入力してください。"
                    }
                },
                status_code=200
            )

        # 即時ACK: 処理中ビュー
        processing_view = create_processing_view(session_id, title="AI補完 - 再分析中", description="いただいた情報で再分析しています…")

        # 背景でAI改良→views.update
        import asyncio

        async def run_refine_and_update():
            try:
                result = await ai_service.refine_content(session_id, additional_info)
                if result.status == "insufficient_info":
                    new_view = create_additional_info_modal_view(session_id, result, requester_id)
                elif result.status == "ready_to_format":
                    modal_sessions[session_id]["generated_content"] = result.formatted_content
                    new_view = create_content_confirmation_modal_view(session_id, result, requester_id)
                else:
                    new_view = create_error_view(session_id, f"AI処理エラー: {result.message}")
                # private_metadata をマージ（requester_id維持）
                pm = {"session_id": session_id}
                if requester_id:
                    pm["requester_id"] = requester_id
                new_view["private_metadata"] = json.dumps(pm)
                if view_id:
                    slack_service.client.views_update(view_id=view_id, view=new_view)
            except Exception as e:
                err_view = create_error_view(session_id, f"AI処理エラー: {str(e)}")
                try:
                    if view_id:
                        slack_service.client.views_update(view_id=view_id, view=err_view)
                except Exception:
                    pass

        asyncio.create_task(run_refine_and_update())

        return JSONResponse(content={"response_action": "update", "view": processing_view}, status_code=200)
            
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Additional info submission error: {e}")
        
        # APIエラーに対する適切なメッセージ
        if any(keyword in error_msg.lower() for keyword in ["timeout", "expired", "overloaded"]):
            error_text = "⏰ AI処理に時間がかかりました。もう一度お試しください。"
        else:
            error_text = f"処理エラー: {error_msg[:100]}..."
            
        return JSONResponse(
            content={
                "response_action": "errors",
                "errors": {
                    "additional_info_block": error_text
                }
            },
            status_code=200
        )


async def handle_content_confirmation(payload: dict) -> JSONResponse:
    """内容確認モーダルの処理（非同期化）"""
    try:
        view = payload.get("view", {})
        view_id = view.get("id")
        values = view.get("state", {}).get("values", {})
        private_metadata = json.loads(view.get("private_metadata", "{}"))
        
        session_id = private_metadata.get("session_id")
        session_data = modal_sessions.get(session_id, {})
        generated_content = session_data.get("generated_content")
        requester_id = session_data.get("requester_id")

        print(f"🔍 内容確認セッション: {session_id}, 履歴数: {len(ai_service.history.get_conversation(session_id)) if ai_service else 0}")
        
        # フィードバックがあるかチェック
        feedback = ""
        fb_block = values.get("feedback_block")
        if fb_block and "feedback_input" in fb_block:
            raw = fb_block["feedback_input"].get("value")
            feedback = (raw or "").strip()
        
        # 即時ACK: 処理中ビュー
        processing_view = create_processing_view(session_id, title="AI補完 - 反映中", description="内容を反映しています…")

        import asyncio

        async def run_feedback_apply():
            try:
                if feedback:
                    if not ai_service:
                        new_view = create_error_view(session_id, "AI機能が利用できません。")
                    else:
                        result = await ai_service.refine_content(session_id, feedback)
                        if result.status == "insufficient_info":
                            # 追加質問に戻す
                            new_view = create_additional_info_modal_view(session_id, result, requester_id)
                        elif result.status == "ready_to_format":
                            modal_sessions.setdefault(session_id, {})
                            modal_sessions[session_id]["generated_content"] = result.formatted_content
                            new_view = create_content_confirmation_modal_view(session_id, result, requester_id)
                        else:
                            new_view = create_error_view(session_id, f"AI処理エラー: {result.message}")
                else:
                    # フィードバックなし - 元のモーダルに戻って内容を反映
                    original_view = session_data.get("original_view")
                    current_values = session_data.get("current_values", {})

                    if original_view and generated_content:
                        # views.updateに必要なプロパティのみを抽出
                        clean_view = {
                            "type": original_view.get("type", "modal"),
                            "callback_id": original_view.get("callback_id", "create_task_modal"),
                            "title": original_view.get("title"),
                            "submit": original_view.get("submit"),
                            "close": original_view.get("close"),
                            "blocks": original_view.get("blocks", [])
                        }

                        # 保存した値を各ブロックに復元
                        if "blocks" in clean_view:
                            for block in clean_view["blocks"]:
                                block_id = block.get("block_id")

                                # 依頼先
                                if block_id == "assignee_block" and current_values.get("assignee"):
                                    if "element" in block:
                                        block["element"]["initial_option"] = current_values["assignee"]

                                # タイトル
                                elif block_id == "title_block" and current_values.get("title"):
                                    if "element" in block:
                                        block["element"]["initial_value"] = current_values["title"]

                                # 納期
                                elif block_id == "due_date_block" and current_values.get("due_date"):
                                    if "element" in block:
                                        block["element"]["initial_date_time"] = current_values["due_date"]

                                # タスク種類
                                elif block_id == "task_type_block" and current_values.get("task_type"):
                                    if "element" in block:
                                        block["element"]["initial_option"] = current_values["task_type"]

                                # 緊急度
                                elif block_id == "urgency_block" and current_values.get("urgency"):
                                    if "element" in block:
                                        block["element"]["initial_option"] = current_values["urgency"]

                                # 内容詳細（AI生成内容を設定）
                                elif block_id == "description_block":
                                    if "element" in block:
                                        block["element"]["initial_value"] = {
                                            "type": "rich_text",
                                            "elements": [
                                                {
                                                    "type": "rich_text_section",
                                                    "elements": [
                                                        {
                                                            "type": "text",
                                                            "text": generated_content
                                                        }
                                                    ]
                                                }
                                            ]
                                        }
                        new_view = clean_view
                    else:
                        new_view = create_error_view(session_id, "AI生成内容が見つかりませんでした。最初からやり直してください。")

                # private_metadata をマージ（requester_id維持）
                pm = {"session_id": session_id}
                if requester_id:
                    pm["requester_id"] = requester_id
                new_view["private_metadata"] = json.dumps(pm)
                if view_id:
                    slack_service.client.views_update(view_id=view_id, view=new_view)
            except Exception as e:
                try:
                    if view_id:
                        slack_service.client.views_update(view_id=view_id, view=create_error_view(session_id, f"処理エラー: {str(e)}"))
                except Exception:
                    pass

        asyncio.create_task(run_feedback_apply())

        return JSONResponse(content={"response_action": "update", "view": processing_view}, status_code=200)
            
    except Exception as e:
        print(f"❌ Content confirmation error: {e}")
        return JSONResponse(
            content={
                "response_action": "errors",
                "errors": {
                    "feedback_block": f"処理エラー: {str(e)}"
                }
            },
            status_code=200
        )


def create_additional_info_modal_view(session_id: str, result: AIAnalysisResult, requester_id: str = None) -> dict:
    """追加情報モーダルビューを作成"""
    suggestions_text = "\n".join(f"• {s}" for s in result.suggestions) if result.suggestions else ""

    # private_metadataを構築
    pm = {"session_id": session_id}
    if requester_id:
        pm["requester_id"] = requester_id

    return {
        "type": "modal",
        "callback_id": "ai_additional_info_modal",
        "title": {
            "type": "plain_text",
            "text": "AI補完 - 追加情報"
        },
        "submit": {
            "type": "plain_text",
            "text": "分析実行"
        },
        "close": {
            "type": "plain_text",
            "text": "キャンセル"
        },
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"🤖 *AI分析結果*\n{result.message}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*必要な追加情報:*\n{suggestions_text}"
                }
            },
            {
                "type": "input",
                "block_id": "additional_info_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "additional_info_input",
                    "multiline": True,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "上記の質問に対する回答を入力してください..."
                    }
                },
                "label": {
                    "type": "plain_text",
                    "text": "追加情報"
                }
            }
        ],
        "private_metadata": json.dumps(pm)
    }


def create_content_confirmation_modal_view(session_id: str, result: AIAnalysisResult, requester_id: str = None) -> dict:
    """内容確認モーダルビューを作成"""
    content_text = (result.formatted_content or result.message or "").strip()

    # private_metadataを構築
    pm = {"session_id": session_id}
    if requester_id:
        pm["requester_id"] = requester_id

    return {
        "type": "modal",
        "callback_id": "ai_content_confirmation_modal",
        "title": {
            "type": "plain_text",
            "text": "AI補完 - 内容確認"
        },
        "submit": {
            "type": "plain_text",
            "text": "採用する"
        },
        "close": {
            "type": "plain_text",
            "text": "キャンセル"
        },
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "🤖 *AI生成されたタスク内容*\n以下の内容でよろしければ「採用する」をクリックしてください。"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"```{content_text}```"
                }
            },
            {
                "type": "input",
                "block_id": "feedback_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "feedback_input",
                    "multiline": True,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "修正点があれば入力してください（任意）"
                    }
                },
                "label": {
                    "type": "plain_text",
                    "text": "フィードバック（任意）"
                },
                "optional": True
            }
        ],
        "private_metadata": json.dumps(pm)
    }


def create_processing_view(session_id: str, title: str, description: str) -> dict:
    """処理中プレースホルダービュー（即時ACK用）"""
    return {
        "type": "modal",
        "callback_id": "ai_processing_modal",
        "title": {"type": "plain_text", "text": title[:24] or "処理中"},
        "close": {"type": "plain_text", "text": "キャンセル"},
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"⏳ {description}"}}
        ],
        "private_metadata": json.dumps({"session_id": session_id})
    }


def create_error_view(session_id: str, message: str) -> dict:
    """エラービュー"""
    return {
        "type": "modal",
        "callback_id": "ai_error_modal",
        "title": {"type": "plain_text", "text": "エラー"},
        "close": {"type": "plain_text", "text": "閉じる"},
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"❌ {message}"}}
        ],
        "private_metadata": json.dumps({"session_id": session_id})
    }


def _rebuild_task_form_blocks_with_values(values: dict, task_type: str, urgency: str) -> list:
    """エラー時に値を保持したタスクフォームブロックを再構築"""
    
    # 依頼先は再選択が必要（ユーザーリスト再取得が複雑なため）
    assignee_initial_option = None
    
    # タイトルの初期値
    title_initial_value = ""
    if "title_block" in values and "title_input" in values["title_block"]:
        title_initial_value = values["title_block"]["title_input"].get("value", "")
    
    # 納期の初期値
    due_date_initial = None
    if "due_date_block" in values and "due_date_picker" in values["due_date_block"]:
        due_date_initial = values["due_date_block"]["due_date_picker"].get("selected_date_time")
    
    # 内容詳細の初期値
    description_initial = None
    if "description_block" in values and "description_input" in values["description_block"]:
        description_rich = values["description_block"]["description_input"].get("rich_text_value")
        if description_rich:
            description_initial = description_rich

    blocks = [
        {
            "type": "input",
            "block_id": "assignee_block",
            "element": {
                "type": "static_select",
                "placeholder": {"type": "plain_text", "text": "依頼先を再選択してください"},
                "options": [{"text": {"type": "plain_text", "text": "ユーザーリストを読み込み中..."}, "value": "loading"}],
                "action_id": "assignee_select",
            },
            "label": {"type": "plain_text", "text": "依頼先"},
        },
        {
            "type": "input",
            "block_id": "title_block",
            "element": {
                "type": "plain_text_input",
                "action_id": "title_input",
                "placeholder": {"type": "plain_text", "text": "タスクの件名を入力"},
            },
            "label": {"type": "plain_text", "text": "件名"},
        },
        {
            "type": "input",
            "block_id": "due_date_block",
            "element": {
                "type": "datetimepicker",
                "action_id": "due_date_picker"
            },
            "label": {"type": "plain_text", "text": "納期"},
        },
        {
            "type": "input",
            "block_id": "task_type_block",
            "element": {
                "type": "static_select",
                "placeholder": {"type": "plain_text", "text": "タスク種類を選択"},
                "options": [
                    {"text": {"type": "plain_text", "text": "フリーランス関係"}, "value": "フリーランス関係"},
                    {"text": {"type": "plain_text", "text": "モノテック関連"}, "value": "モノテック関連"},
                    {"text": {"type": "plain_text", "text": "社内タスク"}, "value": "社内タスク"},
                    {"text": {"type": "plain_text", "text": "HH関連"}, "value": "HH関連"},
                    {"text": {"type": "plain_text", "text": "Sales関連"}, "value": "Sales関連"},
                    {"text": {"type": "plain_text", "text": "PL関連"}, "value": "PL関連"},
                ],
                "action_id": "task_type_select",
            },
            "label": {"type": "plain_text", "text": "タスク種類"},
        },
        {
            "type": "input",
            "block_id": "urgency_block",
            "element": {
                "type": "static_select",
                "placeholder": {"type": "plain_text", "text": "緊急度を選択"},
                "options": [
                    {"text": {"type": "plain_text", "text": "ノンコア社内タスク"}, "value": "ノンコア社内タスク"},
                    {"text": {"type": "plain_text", "text": "1週間以内"}, "value": "1週間以内"},
                    {"text": {"type": "plain_text", "text": "最重要"}, "value": "最重要"},
                ],
                "action_id": "urgency_select",
            },
            "label": {"type": "plain_text", "text": "緊急度"},
        },
        {
            "type": "section",
            "block_id": "ai_helper_section",
            "text": {"type": "mrkdwn", "text": "🤖 *AI補完機能*\nタスクの詳細内容をAIに生成・改良してもらえます"},
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "AI補完", "emoji": True},
                "value": "ai_enhance",
                "action_id": "ai_enhance_button",
            },
        },
        {
            "type": "input",
            "block_id": "description_block",
            "element": {
                "type": "rich_text_input",
                "action_id": "description_input",
                "placeholder": {"type": "plain_text", "text": "タスクの詳細を入力（任意）"},
            },
            "label": {"type": "plain_text", "text": "内容詳細"},
            "optional": True,
        },
    ]
    
    # 初期値を設定
    if assignee_initial_option:
        blocks[0]["element"]["initial_option"] = assignee_initial_option
    if title_initial_value:
        blocks[1]["element"]["initial_value"] = title_initial_value
    if due_date_initial:
        blocks[2]["element"]["initial_date_time"] = due_date_initial
    if task_type:
        blocks[3]["element"]["initial_option"] = {"text": {"type": "plain_text", "text": task_type}, "value": task_type}
    if urgency:
        blocks[4]["element"]["initial_option"] = {"text": {"type": "plain_text", "text": urgency}, "value": urgency}
    if description_initial:
        blocks[7]["element"]["initial_value"] = description_initial
    
    return blocks
