import json
from typing import Dict, Any, Optional
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from src.domain.entities.task import TaskRequest


class SlackService:
    """Slack APIサービス"""

    def __init__(self, slack_token: str, slack_bot_token: str):
        self.client = WebClient(token=slack_bot_token)
        self.user_client = WebClient(token=slack_token)

    async def get_user_info(self, user_id: str) -> Dict[str, Any]:
        """ユーザー情報を取得"""
        try:
            response = self.client.users_info(user=user_id)
            return response["user"]
        except SlackApiError as e:
            print(f"Error getting user info: {e}")
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
                    ],
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*内容:*\n{task.description}",
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

    async def open_task_modal(self, trigger_id: str, user_id: str):
        """タスク作成モーダルを開く"""
        try:
            # ワークスペースのユーザーリストを取得
            users_response = self.client.users_list()
            users = users_response["members"]

            # ユーザー選択オプションを作成
            user_options = []
            for user in users:
                if not user.get("is_bot") and not user.get("deleted"):
                    user_options.append(
                        {
                            "text": {
                                "type": "plain_text",
                                "text": user.get("real_name", user.get("name", "Unknown")),
                            },
                            "value": user["id"],
                        }
                    )

            modal = {
                "type": "modal",
                "callback_id": "create_task_modal",
                "title": {
                    "type": "plain_text",
                    "text": "タスク依頼作成",
                },
                "submit": {
                    "type": "plain_text",
                    "text": "作成",
                },
                "close": {
                    "type": "plain_text",
                    "text": "キャンセル",
                },
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "assignee_block",
                        "element": {
                            "type": "static_select",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "依頼先を選択",
                            },
                            "options": user_options,
                            "action_id": "assignee_select",
                        },
                        "label": {
                            "type": "plain_text",
                            "text": "依頼先",
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "title_block",
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "title_input",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "タスクの件名を入力",
                            },
                        },
                        "label": {
                            "type": "plain_text",
                            "text": "件名",
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "due_date_block",
                        "element": {
                            "type": "datetimepicker",
                            "action_id": "due_date_picker",
                        },
                        "label": {
                            "type": "plain_text",
                            "text": "納期",
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "description_block",
                        "element": {
                            "type": "rich_text_input",
                            "action_id": "description_input",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "タスクの詳細を入力",
                            },
                        },
                        "label": {
                            "type": "plain_text",
                            "text": "内容",
                        },
                    },
                ],
                "private_metadata": json.dumps({"requester_id": user_id}),
            }

            self.client.views_open(trigger_id=trigger_id, view=modal)

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