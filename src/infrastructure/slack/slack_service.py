import copy
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from src.domain.entities.task import TaskRequest
from src.infrastructure.notion.dynamic_notion_service import REMINDER_STAGE_PENDING_APPROVAL
from src.utils.text_converter import convert_rich_text_to_plain_text
from zoneinfo import ZoneInfo

REMINDER_STAGE_LABELS = {
    "期日前": "⏰ 期日前リマインド",
    "当日": "📅 本日が納期です",
    "超過": "⚠️ 納期超過",
    "既読": "✅ 既読済み",
    "未送信": "ℹ️ リマインド準備中",
    "承認済": "✅ 承認済み",
    "未承認": "📝 承認待ちタスク",
}

TASK_TYPE_OPTIONS: List[Dict[str, Any]] = [
    {"text": {"type": "plain_text", "text": "フリーランス関係"}, "value": "フリーランス関係"},
    {"text": {"type": "plain_text", "text": "モノテック関連"}, "value": "モノテック関連"},
    {"text": {"type": "plain_text", "text": "社内タスク"}, "value": "社内タスク"},
    {"text": {"type": "plain_text", "text": "HH関連"}, "value": "HH関連"},
    {"text": {"type": "plain_text", "text": "Sales関連"}, "value": "Sales関連"},
    {"text": {"type": "plain_text", "text": "PL関連"}, "value": "PL関連"},
]

URGENCY_OPTIONS: List[Dict[str, Any]] = [
    {"text": {"type": "plain_text", "text": "ノンコア社内タスク"}, "value": "ノンコア社内タスク"},
    {"text": {"type": "plain_text", "text": "1週間以内"}, "value": "1週間以内"},
    {"text": {"type": "plain_text", "text": "最重要"}, "value": "最重要"},
]

JST = ZoneInfo("Asia/Tokyo")


class SlackService:
    """Slack APIサービス"""

    def __init__(self, slack_token: str, slack_bot_token: str, env: str = "local"):
        self.client = WebClient(token=slack_bot_token)
        self.user_client = WebClient(token=slack_token)
        self.env = env

    @property
    def app_name_suffix(self) -> str:
        """環境に応じてアプリ名の接尾辞を返す"""
        if self.env == "production":
            return ""
        else:
            return " (Dev)"

    def _format_datetime(self, value: datetime) -> str:
        if not value:
            return ""
        value = self._ensure_jst(value)
        return value.strftime("%Y-%m-%d %H:%M")

    def _ensure_jst(self, value: Optional[datetime]) -> Optional[datetime]:
        if not value:
            return None
        if value.tzinfo:
            return value.astimezone(JST)
        return value.replace(tzinfo=JST)

    def _datetimepicker_initial(self, value: Optional[datetime]) -> int:
        target = self._ensure_jst(value) or datetime.now(JST)
        return int(target.astimezone(timezone.utc).timestamp())

    def _task_type_options(self) -> List[Dict[str, Any]]:
        return copy.deepcopy(TASK_TYPE_OPTIONS)

    def _urgency_options(self) -> List[Dict[str, Any]]:
        return copy.deepcopy(URGENCY_OPTIONS)

    def _get_user_select_options(
        self, selected_user_id: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]], int, bool]:
        users_response = self.client.users_list()
        users = users_response["members"]

        internal_users = [
            user
            for user in users
            if not user.get("is_bot")
            and not user.get("deleted")
            and not user.get("is_restricted")
            and not user.get("is_ultra_restricted")
        ]

        options: List[Dict[str, Any]] = []
        initial_option: Optional[Dict[str, Any]] = None
        max_users = min(len(internal_users), 100)
        limit_hit = len(internal_users) > 100

        for index, user in enumerate(internal_users):
            if index >= max_users:
                break
            option = {
                "text": {
                    "type": "plain_text",
                    "text": user.get("real_name", user.get("name", "Unknown")),
                },
                "value": user["id"],
            }
            options.append(option)

            if selected_user_id and user["id"] == selected_user_id:
                initial_option = option

        if not initial_option and selected_user_id and options:
            # 依頼先が社内メンバーリストに存在しない場合は最初の選択肢を初期値にする
            initial_option = options[0]

        return options, initial_option, len(internal_users), limit_hit

    def _build_rich_text_initial(self, description: Optional[Any]) -> Optional[Dict[str, Any]]:
        if not description:
            return None

        if isinstance(description, dict):
            return copy.deepcopy(description)

        if isinstance(description, str):
            text = description.strip()
            if not text:
                return None
            return {
                "type": "rich_text",
                "elements": [
                    {
                        "type": "rich_text_section",
                        "elements": [
                            {
                                "type": "text",
                                "text": text,
                            }
                        ],
                    }
                ],
            }

        return None

    async def get_user_info(self, user_id: str) -> Dict[str, Any]:
        """ユーザー情報を取得"""
        try:
            print(f"🔍 Getting user info for: {user_id}")
            response = self.client.users_info(user=user_id)
            user_data = response["user"]

            print(f"📋 User data keys: {list(user_data.keys())}")

            # プロフィール情報の詳細チェック
            if "profile" in user_data:
                profile = user_data["profile"]
                print(f"👤 Profile keys: {list(profile.keys())}")
                print(f"📧 Email in profile: {profile.get('email', 'No email')}")
                print(f"🏢 Email (display): {profile.get('display_name', 'No display name')}")
                print(f"🏷️ Real name: {profile.get('real_name', 'No real name')}")
            else:
                print("❌ No profile data found")

            return user_data
        except SlackApiError as e:
            print(f"❌ Error getting user info: {e}")
            print(f"Error details: {e.response}")
            return {}

    async def send_approval_request(
        self, assignee_slack_id: str, task: TaskRequest, requester_name: str
    ):
        """承認依頼をDMで送信"""
        try:
            # DMチャンネルを開く
            dm_response = self.client.conversations_open(users=assignee_slack_id)
            channel_id = dm_response["channel"]["id"]

            # 承認/差し戻しボタンを含むメッセージを送信
            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "📋 新しいタスク依頼があります",
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*依頼者:*\n{requester_name}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*件名:*\n{task.title}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*納期:*\n{task.due_date.strftime('%Y-%m-%d %H:%M')}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*タスク種類:*\n{task.task_type}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*緊急度:*\n{task.urgency}",
                        },
                    ],
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*内容:*\n{convert_rich_text_to_plain_text(task.description)}",
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "✅ 承認",
                            },
                            "style": "primary",
                            "value": task.id,
                            "action_id": "approve_task",
                        },
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "❌ 差し戻し",
                            },
                            "style": "danger",
                            "value": task.id,
                            "action_id": "reject_task",
                        },
                    ],
                },
            ]

            self.client.chat_postMessage(
                channel=channel_id,
                text=f"新しいタスク依頼: {task.title}",
                blocks=blocks,
            )

        except SlackApiError as e:
            print(f"Error sending approval request: {e}")
            raise

    async def notify_approval(self, requester_slack_id: str, task: TaskRequest):
        """承認通知を送信"""
        try:
            dm_response = self.client.conversations_open(users=requester_slack_id)
            channel_id = dm_response["channel"]["id"]

            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "✅ タスクが承認されました",
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*件名:* {task.title}\n"
                        f"*承認日時:* {task.updated_at.strftime('%Y-%m-%d %H:%M')}\n"
                        f"タスクがNotionに登録されました。",
                    },
                },
            ]

            self.client.chat_postMessage(
                channel=channel_id,
                text=f"タスクが承認されました: {task.title}",
                blocks=blocks,
            )

        except SlackApiError as e:
            print(f"Error sending approval notification: {e}")

    async def notify_rejection(self, requester_slack_id: str, task: TaskRequest):
        """差し戻し通知を送信"""
        try:
            dm_response = self.client.conversations_open(users=requester_slack_id)
            channel_id = dm_response["channel"]["id"]

            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "❌ タスクが差し戻されました",
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*件名:* {task.title}\n"
                        f"*差し戻し理由:* {task.rejection_reason}\n"
                        f"*差し戻し日時:* {task.updated_at.strftime('%Y-%m-%d %H:%M')}",
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "style": "primary",
                            "text": {"type": "plain_text", "text": "✏️ 修正して再送", "emoji": True},
                            "action_id": "open_revision_modal",
                            "value": json.dumps({"task_id": task.id}),
                        }
                    ],
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "修正ボタンから内容を編集し、同じタスクを再送できます。",
                        }
                    ],
                },
            ]

            self.client.chat_postMessage(
                channel=channel_id,
                text=f"タスクが差し戻されました: {task.title}",
                blocks=blocks,
            )

        except SlackApiError as e:
            print(f"Error sending rejection notification: {e}")

    async def send_task_reminder(
        self,
        assignee_slack_id: str,
        snapshot,
        stage: str,
        requester_slack_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """タスクリマインド通知を送信"""
        try:
            dm_response = self.client.conversations_open(users=assignee_slack_id)
            channel_id = dm_response["channel"]["id"]

            stage_label = REMINDER_STAGE_LABELS.get(stage, stage or "リマインド")
            due_text = self._format_datetime(snapshot.due_date) if getattr(snapshot, "due_date", None) else "未設定"
            notion_url = f"https://www.notion.so/{snapshot.page_id.replace('-', '')}"
            extension_status = getattr(snapshot, "extension_status", None)
            info_lines = [f"*ステータス:* {getattr(snapshot, 'status', '未取得')}"]
            if stage == REMINDER_STAGE_PENDING_APPROVAL:
                info_lines.append("*承認待ち:* 先にタスクを承認してください。承認後に納期リマインドが開始されます。")
            if extension_status and extension_status != "なし":
                info_lines.append(f"*延期ステータス:* {extension_status}")

            blocks: List[Dict[str, Any]] = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{stage_label} - {snapshot.title}",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*件名:*\n<{notion_url}|{snapshot.title}>",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*納期:*\n{due_text}",
                        },
                    ],
                },
            ]

            if info_lines:
                blocks.append(
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": "\n".join(info_lines)},
                    }
                )

            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "👀 既読", "emoji": True},
                            "style": "primary",
                            "action_id": "mark_reminder_read",
                            "value": json.dumps({
                                "page_id": snapshot.page_id,
                                "stage": stage,
                                "requester_slack_id": requester_slack_id,
                            }),
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "⏳ 延期申請", "emoji": True},
                            "action_id": "open_extension_modal",
                            "value": json.dumps({
                                "page_id": snapshot.page_id,
                                "stage": stage,
                                "requester_slack_id": requester_slack_id,
                            }),
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "✅ 完了", "emoji": True},
                            "style": "primary",
                            "action_id": "open_completion_modal",
                            "value": json.dumps({
                                "page_id": snapshot.page_id,
                                "stage": stage,
                                "requester_slack_id": requester_slack_id,
                            }),
                        },
                    ],
                }
            )

            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "既読でリマインドを終了できます。延期申請は依頼者承認後に反映されます。",
                        }
                    ],
                }
            )

            return self.client.chat_postMessage(
                channel=channel_id,
                text=f"{stage_label}: {snapshot.title}",
                blocks=blocks,
            )

        except SlackApiError as e:
            print(f"Error sending task reminder: {e}")
            raise

    async def open_extension_modal(
        self,
        trigger_id: str,
        snapshot,
        stage: str,
        requester_slack_id: str,
        assignee_slack_id: str,
    ):
        """延期申請モーダルを表示"""
        try:
            due_text = self._format_datetime(snapshot.due_date) if getattr(snapshot, "due_date", None) else "未設定"
            requested_metadata = {
                "page_id": snapshot.page_id,
                "stage": stage,
                "requester_slack_id": requester_slack_id,
                "assignee_slack_id": assignee_slack_id,
            }

            datetimepicker_element: Dict[str, Any] = {
                "type": "datetimepicker",
                "action_id": "new_due_picker",
            }
            if getattr(snapshot, "due_date", None):
                datetimepicker_element["initial_date_time"] = self._datetimepicker_initial(snapshot.due_date)

            modal = {
                "type": "modal",
                "callback_id": "extension_request_modal",
                "title": {"type": "plain_text", "text": "延期申請"},
                "submit": {"type": "plain_text", "text": "申請"},
                "close": {"type": "plain_text", "text": "キャンセル"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*{snapshot.title}*\n現在の納期: {due_text}\nステージ: {REMINDER_STAGE_LABELS.get(stage, stage)}"
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "new_due_block",
                        "element": datetimepicker_element,
                        "label": {"type": "plain_text", "text": "新しい希望納期"},
                    },
                    {
                        "type": "input",
                        "block_id": "reason_block",
                        "label": {"type": "plain_text", "text": "延期理由"},
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "reason_input",
                            "multiline": True,
                            "placeholder": {"type": "plain_text", "text": "延期が必要な理由を記入"},
                        },
                    },
                ],
                "private_metadata": json.dumps(requested_metadata),
            }

            return self.client.views_open(trigger_id=trigger_id, view=modal)

        except SlackApiError as e:
            print(f"Error opening extension request modal: {e}")
            raise

    async def send_extension_request_to_requester(
        self,
        requester_slack_id: str,
        assignee_slack_id: str,
        snapshot,
        requested_due: datetime,
        reason: str,
    ) -> Dict[str, Any]:
        """依頼者へ延期承認リクエストを送信"""
        try:
            dm_response = self.client.conversations_open(users=requester_slack_id)
            channel_id = dm_response["channel"]["id"]

            due_text = self._format_datetime(snapshot.due_date) if getattr(snapshot, "due_date", None) else "未設定"
            requested_due_text = self._format_datetime(requested_due)

            blocks: List[Dict[str, Any]] = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "⏳ 延期承認リクエスト", "emoji": True},
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*タスク:*\n{snapshot.title}"},
                        {"type": "mrkdwn", "text": f"*申請者:*\n<@{assignee_slack_id}>"},
                        {"type": "mrkdwn", "text": f"*現在の納期:*\n{due_text}"},
                        {"type": "mrkdwn", "text": f"*新しい期日案:*\n{requested_due_text}"},
                    ],
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*理由:*\n{reason}"},
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "style": "primary",
                            "text": {"type": "plain_text", "text": "承認", "emoji": True},
                            "action_id": "approve_extension_request",
                            "value": json.dumps({
                                "page_id": snapshot.page_id,
                                "assignee_slack_id": assignee_slack_id,
                                "requester_slack_id": requester_slack_id,
                            }),
                        },
                        {
                            "type": "button",
                            "style": "danger",
                            "text": {"type": "plain_text", "text": "却下", "emoji": True},
                            "action_id": "reject_extension_request",
                            "value": json.dumps({
                                "page_id": snapshot.page_id,
                                "assignee_slack_id": assignee_slack_id,
                                "requester_slack_id": requester_slack_id,
                            }),
                        },
                    ],
                },
            ]

            return self.client.chat_postMessage(
                channel=channel_id,
                text=f"延期承認リクエスト: {snapshot.title}",
                blocks=blocks,
            )

        except SlackApiError as e:
            print(f"Error sending extension approval request: {e}")
            raise

    async def notify_extension_request_submitted(
        self,
        assignee_slack_id: str,
        requested_due: datetime,
    ) -> None:
        try:
            dm_response = self.client.conversations_open(users=assignee_slack_id)
            channel_id = dm_response["channel"]["id"]

            self.client.chat_postMessage(
                channel=channel_id,
                text="延期申請を送信しました。依頼者の承認をお待ちください。",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"⏳ 延期申請を送信しました。\n希望納期: {self._format_datetime(requested_due)}",
                        },
                    }
                ],
            )
        except SlackApiError as e:
            print(f"Error notifying submitter about extension request: {e}")

    async def notify_extension_approved(
        self,
        assignee_slack_id: str,
        requester_slack_id: str,
        snapshot,
        new_due: datetime,
    ) -> None:
        message = f"✅ 延期が承認されました。新しい納期: {self._format_datetime(new_due)}"
        try:
            assignee_dm = self.client.conversations_open(users=assignee_slack_id)
            self.client.chat_postMessage(
                channel=assignee_dm["channel"]["id"],
                text=message,
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"✅ *延期承認*\nタスク: {snapshot.title}\n新しい納期: {self._format_datetime(new_due)}",
                        },
                    }
                ],
            )

            requester_dm = self.client.conversations_open(users=requester_slack_id)
            self.client.chat_postMessage(
                channel=requester_dm["channel"]["id"],
                text=message,
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"✅ 延期申請を承認しました。\nタスク: {snapshot.title}\n新しい納期: {self._format_datetime(new_due)}",
                        },
                    }
                ],
            )
        except SlackApiError as e:
            print(f"Error notifying extension approval: {e}")

    async def notify_extension_rejected(
        self,
        assignee_slack_id: str,
        requester_slack_id: str,
        snapshot,
        reason: Optional[str] = None,
    ) -> None:
        rejection_text = "延期申請は却下されました。"
        detail = reason or "理由は依頼者に確認してください。"
        try:
            assignee_dm = self.client.conversations_open(users=assignee_slack_id)
            self.client.chat_postMessage(
                channel=assignee_dm["channel"]["id"],
                text=rejection_text,
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"⚠️ *延期却下*\nタスク: {snapshot.title}\n理由: {detail}",
                        },
                    }
                ],
            )

            requester_dm = self.client.conversations_open(users=requester_slack_id)
            self.client.chat_postMessage(
                channel=requester_dm["channel"]["id"],
                text=rejection_text,
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"⚠️ 延期申請を却下しました。必要であればメンションで共有してください。",
                        },
                    }
                ],
            )
        except SlackApiError as e:
            print(f"Error notifying extension rejection: {e}")

    async def open_completion_modal(
        self,
        trigger_id: str,
        snapshot,
        stage: str,
        requester_slack_id: str,
        assignee_slack_id: str,
    ):
        """完了報告モーダル"""
        try:
            notion_url = f"https://www.notion.so/{snapshot.page_id.replace('-', '')}"
            now_jst = self._ensure_jst(datetime.now(JST))
            due_jst = self._ensure_jst(snapshot.due_date) if getattr(snapshot, "due_date", None) else None
            overdue = bool(due_jst and now_jst > due_jst)

            note_label = "遅延理由（必須）" if overdue else "完了メモ（任意）"
            note_placeholder = "遅延となった理由を記入してください" if overdue else "完了内容や共有事項を記入"

            modal = {
                "type": "modal",
                "callback_id": "completion_request_modal",
                "title": {"type": "plain_text", "text": "完了報告"},
                "submit": {"type": "plain_text", "text": "送信"},
                "close": {"type": "plain_text", "text": "キャンセル"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                f"*{snapshot.title}*\n納期: {self._format_datetime(snapshot.due_date)}\n"
                                f"状況: {REMINDER_STAGE_LABELS.get(stage, stage)}\n"
                                f"完了日時は送信時刻（JST）に自動記録されます。\n"
                                f"Notion: <{notion_url}|ページを開く>"
                            ),
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "note_block",
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "note_input",
                            "multiline": True,
                            "placeholder": {"type": "plain_text", "text": note_placeholder},
                        },
                        "label": {"type": "plain_text", "text": note_label},
                        "optional": not overdue,
                    },
                ],
                "private_metadata": json.dumps({
                    "page_id": snapshot.page_id,
                    "requester_slack_id": requester_slack_id,
                    "assignee_slack_id": assignee_slack_id,
                    "require_reason": overdue,
                }),
            }

            return self.client.views_open(trigger_id=trigger_id, view=modal)
        except SlackApiError as e:
            print(f"Error opening completion modal: {e}")
            raise

    async def send_completion_request_to_requester(
        self,
        requester_slack_id: str,
        assignee_slack_id: str,
        snapshot,
        completion_note: Optional[str],
        requested_at: datetime,
        overdue: bool,
    ) -> Dict[str, Any]:
        try:
            dm_response = self.client.conversations_open(users=requester_slack_id)
            channel_id = dm_response["channel"]["id"]

            notion_url = f"https://www.notion.so/{snapshot.page_id.replace('-', '')}"
            fields = [
                {"type": "mrkdwn", "text": f"*タスク:*\n<{notion_url}|{snapshot.title}>"},
                {"type": "mrkdwn", "text": f"*申請者:*\n<@{assignee_slack_id}>"},
                {"type": "mrkdwn", "text": f"*現在の納期:*\n{self._format_datetime(snapshot.due_date)}"},
                {"type": "mrkdwn", "text": f"*申請日時:*\n{self._format_datetime(requested_at)}"},
            ]

            blocks: List[Dict[str, Any]] = [
                {"type": "header", "text": {"type": "plain_text", "text": "✅ 完了承認リクエスト", "emoji": True}},
                {"type": "section", "fields": fields},
            ]

            if completion_note:
                label = "遅延理由" if overdue else "完了メモ"
                blocks.append(
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"*{label}:*\n{completion_note}"},
                    }
                )

            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "style": "primary",
                            "text": {"type": "plain_text", "text": "承認", "emoji": True},
                            "action_id": "approve_completion_request",
                            "value": json.dumps({
                                "page_id": snapshot.page_id,
                                "assignee_slack_id": assignee_slack_id,
                                "requester_slack_id": requester_slack_id,
                            }),
                        },
                        {
                            "type": "button",
                            "style": "danger",
                            "text": {"type": "plain_text", "text": "却下", "emoji": True},
                            "action_id": "reject_completion_request",
                            "value": json.dumps({
                                "page_id": snapshot.page_id,
                                "assignee_slack_id": assignee_slack_id,
                                "requester_slack_id": requester_slack_id,
                            }),
                        },
                    ],
                }
            )

            return self.client.chat_postMessage(
                channel=channel_id,
                text=f"完了承認リクエスト: {snapshot.title}",
                blocks=blocks,
            )
        except SlackApiError as e:
            print(f"Error sending completion approval request: {e}")
            raise

    async def notify_completion_request_submitted(
        self,
        assignee_slack_id: str,
    ) -> None:
        try:
            dm = self.client.conversations_open(users=assignee_slack_id)
            self.client.chat_postMessage(
                channel=dm["channel"]["id"],
                text="完了承認を依頼者に送信しました。承認をお待ちください。",
            )
        except SlackApiError as e:
            print(f"Error notifying submitter of completion request: {e}")

    async def notify_completion_approved(
        self,
        assignee_slack_id: str,
        requester_slack_id: str,
        snapshot,
        approval_time: datetime,
    ) -> None:
        notion_url = f"https://www.notion.so/{snapshot.page_id.replace('-', '')}"
        message = f"✅ 完了が承認されました ({self._format_datetime(approval_time)})"
        try:
            assignee_dm = self.client.conversations_open(users=assignee_slack_id)
            self.client.chat_postMessage(
                channel=assignee_dm["channel"]["id"],
                text=message,
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"✅ *完了承認*\nタスク: <{notion_url}|{snapshot.title}>\n承認日時: {self._format_datetime(approval_time)}",
                        },
                    }
                ],
            )

            requester_dm = self.client.conversations_open(users=requester_slack_id)
            self.client.chat_postMessage(
                channel=requester_dm["channel"]["id"],
                text=message,
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"✅ 完了を承認しました。\nタスク: <{notion_url}|{snapshot.title}>\n承認日時: {self._format_datetime(approval_time)}",
                        },
                    }
                ],
            )
        except SlackApiError as e:
            print(f"Error notifying completion approval: {e}")

    async def notify_completion_rejected(
        self,
        assignee_slack_id: str,
        requester_slack_id: str,
        snapshot,
        reason: str,
        new_due: datetime,
    ) -> None:
        notion_url = f"https://www.notion.so/{snapshot.page_id.replace('-', '')}"
        try:
            assignee_dm = self.client.conversations_open(users=assignee_slack_id)
            self.client.chat_postMessage(
                channel=assignee_dm["channel"]["id"],
                text="⚠️ 完了申請が却下されました。",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"⚠️ *完了却下*\nタスク: <{notion_url}|{snapshot.title}>\n新しい納期: {self._format_datetime(new_due)}\n理由: {reason}",
                        },
                    }
                ],
            )

            requester_dm = self.client.conversations_open(users=requester_slack_id)
            self.client.chat_postMessage(
                channel=requester_dm["channel"]["id"],
                text="⚠️ 完了申請を却下しました。",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"⚠️ 完了申請を却下しました。\nタスク: <{notion_url}|{snapshot.title}>\n新しい納期: {self._format_datetime(new_due)}\n理由: {reason}",
                        },
                    }
                ],
            )
        except SlackApiError as e:
            print(f"Error notifying completion rejection: {e}")

    async def open_completion_reject_modal(
        self,
        trigger_id: str,
        snapshot,
        assignee_slack_id: str,
        requester_slack_id: str,
    ):
        try:
            modal = {
                "type": "modal",
                "callback_id": "completion_reject_modal",
                "title": {"type": "plain_text", "text": "完了却下"},
                "submit": {"type": "plain_text", "text": "送信"},
                "close": {"type": "plain_text", "text": "キャンセル"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"完了申請を却下します。新しい納期と理由を入力してください。\nタスク: {snapshot.title}"
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "new_due_block",
                        "label": {"type": "plain_text", "text": "新しい納期"},
                        "element": {
                            "type": "datetimepicker",
                            "action_id": "new_due_picker",
                            "initial_date_time": self._datetimepicker_initial(snapshot.due_date or datetime.now(JST)),
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "reason_block",
                        "label": {"type": "plain_text", "text": "却下理由"},
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "reason_input",
                            "multiline": True,
                            "placeholder": {"type": "plain_text", "text": "理由を入力"},
                        },
                    },
                ],
                "private_metadata": json.dumps({
                    "page_id": snapshot.page_id,
                    "assignee_slack_id": assignee_slack_id,
                    "requester_slack_id": requester_slack_id,
                }),
            }
            return self.client.views_open(trigger_id=trigger_id, view=modal)
        except SlackApiError as e:
            print(f"Error opening completion reject modal: {e}")
            raise

    async def open_task_modal(self, trigger_id: str, user_id: str):
        """タスク作成モーダルを開く"""
        try:
            # まず最小のモーダルを即時に開く（3秒ルール回避）
            loading_modal = {
                "type": "modal",
                "callback_id": "create_task_modal_loading",
                "title": {"type": "plain_text", "text": f"タスク依頼作成{self.app_name_suffix}"},
                "close": {"type": "plain_text", "text": "キャンセル"},
                "blocks": [
                    {"type": "section", "text": {"type": "mrkdwn", "text": "⏳ 初期化中…"}}
                ],
                "private_metadata": json.dumps({"requester_id": user_id}),
            }

            open_resp = self.client.views_open(trigger_id=trigger_id, view=loading_modal)
            view_id = open_resp["view"]["id"]

            # ユーザーリストの取得（少し時間がかかる可能性があるため open 後に実行）
            user_options, _, internal_count, limit_hit = self._get_user_select_options()

            print(f"📊 社内メンバー: {internal_count}人（表示: {min(internal_count, 100)}人）")
            if limit_hit:
                print("⚠️ ユーザー数制限により100人のみ表示")

            full_modal = {
                "type": "modal",
                "callback_id": "create_task_modal",
                "title": {"type": "plain_text", "text": f"タスク依頼作成{self.app_name_suffix}"},
                "submit": {"type": "plain_text", "text": "作成"},
                "close": {"type": "plain_text", "text": "キャンセル"},
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "assignee_block",
                        "element": {
                            "type": "static_select",
                            "placeholder": {"type": "plain_text", "text": "依頼先を選択"},
                            "options": user_options,
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
                        "element": {"type": "datetimepicker", "action_id": "due_date_picker"},
                        "label": {"type": "plain_text", "text": "納期"},
                    },
                    {
                        "type": "input",
                        "block_id": "task_type_block",
                        "element": {
                            "type": "static_select",
                            "placeholder": {"type": "plain_text", "text": "タスク種類を選択"},
                            "options": self._task_type_options(),
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
                            "options": self._urgency_options(),
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
                ],
                "private_metadata": json.dumps({"requester_id": user_id}),
            }

            # ローディングビューから本ビューへ更新
            self.client.views_update(view_id=view_id, view=full_modal)

        except SlackApiError as e:
            print(f"Error opening modal: {e}")
            raise

    async def open_task_revision_modal(
        self,
        trigger_id: str,
        task: TaskRequest,
        requester_slack_id: str,
        private_metadata: Dict[str, Any],
        rejection_reason: Optional[str] = None,
    ):
        """差し戻し後のタスク修正モーダルを開く"""
        try:
            loading_modal = {
                "type": "modal",
                "callback_id": "revise_task_modal_loading",
                "title": {"type": "plain_text", "text": f"タスク依頼を修正{self.app_name_suffix}"},
                "close": {"type": "plain_text", "text": "キャンセル"},
                "blocks": [
                    {"type": "section", "text": {"type": "mrkdwn", "text": "⏳ 初期化中…"}}
                ],
                "private_metadata": json.dumps({"task_id": task.id, **private_metadata}),
            }

            open_resp = self.client.views_open(trigger_id=trigger_id, view=loading_modal)
            view_id = open_resp["view"]["id"]

            assignee_options, assignee_initial, internal_count, limit_hit = self._get_user_select_options(
                selected_user_id=task.assignee_slack_id
            )

            print(f"✏️ 修正モーダル: 社内メンバー {internal_count}人（表示: {min(internal_count, 100)}人）")
            if limit_hit:
                print("⚠️ ユーザー数制限により100人のみ表示")

            task_type_options = self._task_type_options()
            task_type_initial = next(
                (option for option in task_type_options if option.get("value") == task.task_type),
                task_type_options[0] if task_type_options else None,
            )

            urgency_options = self._urgency_options()
            urgency_initial = next(
                (option for option in urgency_options if option.get("value") == task.urgency),
                urgency_options[0] if urgency_options else None,
            )

            description_initial = self._build_rich_text_initial(task.description)

            metadata_payload = json.dumps(
                {
                    "task_id": task.id,
                    "requester_slack_id": requester_slack_id,
                    **private_metadata,
                }
            )

            informational_blocks: List[Dict[str, Any]] = []
            if rejection_reason:
                informational_blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"⚠️ *差し戻し理由:*\n{rejection_reason}",
                        },
                    }
                )

            full_modal_blocks: List[Dict[str, Any]] = informational_blocks + [
                {
                    "type": "input",
                    "block_id": "assignee_block",
                    "element": {
                        "type": "static_select",
                        "placeholder": {"type": "plain_text", "text": "依頼先を選択"},
                        "options": assignee_options,
                        "action_id": "assignee_select",
                        **({"initial_option": assignee_initial} if assignee_initial else {}),
                    },
                    "label": {"type": "plain_text", "text": "依頼先"},
                },
                {
                    "type": "input",
                    "block_id": "title_block",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "title_input",
                        "initial_value": task.title,
                    },
                    "label": {"type": "plain_text", "text": "件名"},
                },
                {
                    "type": "input",
                    "block_id": "due_date_block",
                    "element": {
                        "type": "datetimepicker",
                        "action_id": "due_date_picker",
                        "initial_date_time": self._datetimepicker_initial(task.due_date),
                    },
                    "label": {"type": "plain_text", "text": "納期"},
                },
                {
                    "type": "input",
                    "block_id": "task_type_block",
                    "element": {
                        "type": "static_select",
                        "placeholder": {"type": "plain_text", "text": "タスク種類を選択"},
                        "options": task_type_options,
                        "action_id": "task_type_select",
                        **({"initial_option": task_type_initial} if task_type_initial else {}),
                    },
                    "label": {"type": "plain_text", "text": "タスク種類"},
                },
                {
                    "type": "input",
                    "block_id": "urgency_block",
                    "element": {
                        "type": "static_select",
                        "placeholder": {"type": "plain_text", "text": "緊急度を選択"},
                        "options": urgency_options,
                        "action_id": "urgency_select",
                        **({"initial_option": urgency_initial} if urgency_initial else {}),
                    },
                    "label": {"type": "plain_text", "text": "緊急度"},
                },
                {
                    "type": "section",
                    "block_id": "ai_helper_section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "🤖 *AI補完機能*\nタスク内容をAIに整形・改善してもらえます",
                    },
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
                        **({"initial_value": description_initial} if description_initial else {}),
                    },
                    "label": {"type": "plain_text", "text": "内容詳細"},
                    "optional": True,
                },
            ]

            full_modal = {
                "type": "modal",
                "callback_id": "revise_task_modal",
                "title": {"type": "plain_text", "text": f"タスク依頼を修正{self.app_name_suffix}"},
                "submit": {"type": "plain_text", "text": "再送信"},
                "close": {"type": "plain_text", "text": "キャンセル"},
                "blocks": full_modal_blocks,
                "private_metadata": metadata_payload,
            }

            self.client.views_update(view_id=view_id, view=full_modal)

        except SlackApiError as e:
            print(f"Error opening revision modal: {e}")
            raise

    async def open_rejection_modal(self, trigger_id: str, task_id: str):
        """差し戻し理由入力モーダルを開く"""
        try:
            modal = {
                "type": "modal",
                "callback_id": "reject_task_modal",
                "title": {
                    "type": "plain_text",
                    "text": "差し戻し理由",
                },
                "submit": {
                    "type": "plain_text",
                    "text": "差し戻す",
                },
                "close": {
                    "type": "plain_text",
                    "text": "キャンセル",
                },
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "reason_block",
                        "element": {
                            "type": "plain_text_input",
                            "multiline": True,
                            "action_id": "reason_input",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "差し戻し理由を入力してください",
                            },
                        },
                        "label": {
                            "type": "plain_text",
                            "text": "差し戻し理由",
                        },
                    },
                ],
                "private_metadata": json.dumps({"task_id": task_id}),
            }

            self.client.views_open(trigger_id=trigger_id, view=modal)

        except SlackApiError as e:
            print(f"Error opening rejection modal: {e}")
            raise
