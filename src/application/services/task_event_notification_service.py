import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from src.domain.entities.task import TaskRequest
from src.domain.repositories.slack_user_repository import SlackUserRepositoryInterface
from src.domain.value_objects.email import Email
from src.infrastructure.slack.slack_service import SlackService

logger = logging.getLogger(__name__)

JST = ZoneInfo("Asia/Tokyo")


class TaskEventNotificationService:
    """タスクイベント発生時に監視者へ通知するアプリケーションサービス"""

    def __init__(
        self,
        slack_service: SlackService,
        slack_user_repository: SlackUserRepositoryInterface,
        notification_emails: Sequence[str],
    ) -> None:
        self._slack_service = slack_service
        self._slack_user_repository = slack_user_repository
        self._emails: List[Email] = self._normalize_emails(notification_emails)
        self._email_cache: Dict[str, Optional[str]] = {}

    @property
    def enabled(self) -> bool:
        return bool(self._emails)

    async def notify_task_approved(
        self,
        *,
        task: TaskRequest,
        approval_time: datetime,
        requester_name: str,
        assignee_name: str,
    ) -> None:
        """タスク承認時の通知"""
        if not self.enabled:
            return

        notion_url = self._build_notion_url(task.notion_page_id)
        due_text = self._format_datetime(task.due_date)
        approval_text = self._format_datetime(approval_time)

        header_text = "✅ *タスクが承認されました*"
        if notion_url:
            task_line = f"<{notion_url}|{task.title}>"
        else:
            task_line = task.title

        from_person = self._format_person_line(requester_name, task.requester_slack_id)
        to_person = self._format_person_line(assignee_name, task.assignee_slack_id)

        fields = [
            {"type": "mrkdwn", "text": f"*タスク*\n{task_line}"},
            {"type": "mrkdwn", "text": f"*納期*\n{due_text}"},
            {
                "type": "mrkdwn",
                "text": f"*From*\n{from_person}",
            },
            {
                "type": "mrkdwn",
                "text": f"*To*\n{to_person}",
            },
        ]

        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": header_text}},
            {"type": "section", "fields": fields},
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"承認日時: {approval_text}"},
                ],
            },
        ]

        text = f"タスク承認: {task.title}"
        await self._broadcast(text=text, blocks=blocks)

    async def notify_completion_approved(
        self,
        *,
        notion_page_id: Optional[str],
        title: str,
        due_date: Optional[datetime],
        approval_time: datetime,
        requester_slack_id: str,
        requester_name: str,
        assignee_slack_id: str,
        assignee_name: str,
    ) -> None:
        """完了承認時の通知"""
        if not self.enabled:
            return

        notion_url = self._build_notion_url(notion_page_id)
        due_text = self._format_datetime(due_date)
        approval_text = self._format_datetime(approval_time)
        overdue_flag, overdue_label = self._completion_due_status(due_date, approval_time)

        header_prefix = "🏁"
        status_line = f"*完了承認 ({overdue_label})*"

        if notion_url:
            task_line = f"<{notion_url}|{title}>"
        else:
            task_line = title

        from_person = self._format_person_line(requester_name, requester_slack_id)
        to_person = self._format_person_line(assignee_name, assignee_slack_id)

        fields = [
            {"type": "mrkdwn", "text": f"*タスク*\n{task_line}"},
            {"type": "mrkdwn", "text": f"*納期*\n{due_text}"},
            {
                "type": "mrkdwn",
                "text": f"*ステータス*\n{overdue_flag}",
            },
            {
                "type": "mrkdwn",
                "text": f"*完了承認日時*\n{approval_text}",
            },
            {
                "type": "mrkdwn",
                "text": f"*From*\n{from_person}",
            },
            {
                "type": "mrkdwn",
                "text": f"*To*\n{to_person}",
            },
        ]

        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"{header_prefix} {status_line}"},
            },
            {"type": "section", "fields": fields},
        ]

        text = f"タスク完了承認: {title} ({overdue_flag})"
        await self._broadcast(text=text, blocks=blocks)

    def _normalize_emails(self, raw_emails: Sequence[str]) -> List[Email]:
        normalized: List[Email] = []
        for raw in raw_emails:
            email = (raw or "").strip()
            if not email:
                continue
            try:
                normalized.append(Email(email))
            except ValueError:
                logger.warning("⚠️ 通知用メールアドレスが不正です: %s", email)
        return normalized

    async def _broadcast(self, *, text: str, blocks: List[Dict[str, Any]]) -> None:
        for email in self._emails:
            slack_user_id = await self._resolve_slack_user_id(email)
            if not slack_user_id:
                logger.warning("⚠️ Slackユーザーが見つかりませんでした: %s", email)
                continue
            try:
                await self._slack_service.send_direct_message(
                    slack_user_id,
                    text=text,
                    blocks=blocks,
                )
            except Exception as error:
                logger.error(
                    "⚠️ タスクイベント通知の送信に失敗しました (email=%s): %s",
                    email,
                    error,
                )

    async def _resolve_slack_user_id(self, email: Email) -> Optional[str]:
        normalized_email = email.normalized()
        key = str(normalized_email)
        if key in self._email_cache:
            return self._email_cache[key]

        try:
            slack_user = await self._slack_user_repository.find_by_email(normalized_email)
        except Exception as error:
            logger.error("⚠️ Slackユーザー検索に失敗しました (email=%s): %s", email, error)
            slack_user = None

        slack_user_id = str(slack_user.user_id) if slack_user else None
        self._email_cache[key] = slack_user_id
        return slack_user_id

    def _build_notion_url(self, notion_page_id: Optional[str]) -> Optional[str]:
        if not notion_page_id:
            return None
        return f"https://www.notion.so/{notion_page_id.replace('-', '')}"

    def _format_datetime(self, value: Optional[datetime]) -> str:
        if not value:
            return "未設定"
        localized = self._ensure_jst(value)
        return localized.strftime("%Y-%m-%d %H:%M")

    def _ensure_jst(self, value: datetime) -> datetime:
        if value.tzinfo:
            return value.astimezone(JST)
        return value.replace(tzinfo=JST)

    def _completion_due_status(
        self,
        due_date: Optional[datetime],
        approval_time: datetime,
    ) -> Tuple[str, str]:
        if not due_date:
            return "納期未設定", "納期情報なし"

        due_utc = self._to_utc(due_date)
        approval_utc = self._to_utc(approval_time)

        if approval_utc <= due_utc:
            return "納期以内", "納期以内"
        return "納期超過", "納期超過"

    def _to_utc(self, value: datetime) -> datetime:
        if value.tzinfo:
            return value.astimezone(timezone.utc)
        return value.replace(tzinfo=JST).astimezone(timezone.utc)

    def _format_person_line(self, name: str, slack_id: Optional[str]) -> str:
        if slack_id:
            return f"{name} (<@{slack_id}>)"
        return name
