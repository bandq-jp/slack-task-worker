import json
from datetime import datetime
from typing import Dict, Any, Optional, List
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from src.domain.entities.task import TaskRequest
from src.utils.text_converter import convert_rich_text_to_plain_text

REMINDER_STAGE_LABELS = {
    "期日前": "⏰ 期日前リマインド",
    "当日": "📅 本日が納期です",
    "超過": "⚠️ 納期超過",
    "既読": "✅ 既読済み",
    "未送信": "ℹ️ リマインド準備中",
}


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
        if value.tzinfo:
            value = value.astimezone()
        return value.strftime("%Y-%m-%d %H:%M")

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
            overdue_points = getattr(snapshot, "overdue_points", 0)

            info_lines = [f"*ステータス:* {getattr(snapshot, 'status', '未取得')}"]
            if extension_status and extension_status != "なし":
                info_lines.append(f"*延期ステータス:* {extension_status}")
            if overdue_points:
                info_lines.append(f"*納期超過ポイント:* {overdue_points}")

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
                datetimepicker_element["initial_date_time"] = int(snapshot.due_date.timestamp())

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
            users_response = self.client.users_list()
            users = users_response["members"]

            # ユーザー選択オプションを作成（社内メンバーのみ）
            user_options = []
            internal_users = [
                user for user in users
                if not user.get("is_bot")
                and not user.get("deleted")
                and not user.get("is_restricted")
                and not user.get("is_ultra_restricted")
            ]

            max_users = min(len(internal_users), 100)
            for i, user in enumerate(internal_users):
                if i >= max_users:
                    break
                user_options.append(
                    {
                        "text": {"type": "plain_text", "text": user.get("real_name", user.get("name", "Unknown"))},
                        "value": user["id"],
                    }
                )

            print(f"📊 社内メンバー: {len(internal_users)}人（表示: {min(len(internal_users), 100)}人）")
            if len(internal_users) > 100:
                print(f"⚠️ ユーザー数制限により100人のみ表示")

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
                ],
                "private_metadata": json.dumps({"requester_id": user_id}),
            }

            # ローディングビューから本ビューへ更新
            self.client.views_update(view_id=view_id, view=full_modal)

        except SlackApiError as e:
            print(f"Error opening modal: {e}")
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
