import json
from typing import Dict, Any, Optional
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from src.domain.entities.task import TaskRequest
from src.utils.text_converter import convert_rich_text_to_plain_text


class SlackService:
    """Slack APIサービス"""

    def __init__(self, slack_token: str, slack_bot_token: str):
        self.client = WebClient(token=slack_bot_token)
        self.user_client = WebClient(token=slack_token)

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

    async def open_task_modal(self, trigger_id: str, user_id: str):
        """タスク作成モーダルを開く"""
        try:
            # ワークスペースのユーザーリストを取得
            users_response = self.client.users_list()
            users = users_response["members"]

            # ユーザー選択オプションを作成（社内メンバーのみ）
            user_options = []
            # 社内メンバーの条件: ボットでない、削除されていない、ゲストでない
            internal_users = [
                user for user in users 
                if not user.get("is_bot") 
                and not user.get("deleted") 
                and not user.get("is_restricted")  # ゲストユーザーを除外
                and not user.get("is_ultra_restricted")  # シングルチャンネルゲストを除外
            ]
            
            # 最大100ユーザーに制限（Slack API制限）
            max_users = min(len(internal_users), 100)
            for i, user in enumerate(internal_users):
                if i >= max_users:
                    break
                user_options.append(
                    {
                        "text": {
                            "type": "plain_text",
                            "text": user.get("real_name", user.get("name", "Unknown")),
                        },
                        "value": user["id"],
                    }
                )
            
            print(f"📊 社内メンバー: {len(internal_users)}人（表示: {min(len(internal_users), 100)}人）")
            if len(internal_users) > 100:
                print(f"⚠️ ユーザー数制限により100人のみ表示")

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
                        "block_id": "task_type_block",
                        "element": {
                            "type": "static_select",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "タスク種類を選択",
                            },
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
                        "label": {
                            "type": "plain_text",
                            "text": "タスク種類",
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "urgency_block",
                        "element": {
                            "type": "static_select",
                            "placeholder": {
                                "type": "plain_text",
                                "text": "緊急度を選択",
                            },
                            "options": [
                                {"text": {"type": "plain_text", "text": "ノンコア社内タスク"}, "value": "ノンコア社内タスク"},
                                {"text": {"type": "plain_text", "text": "1週間以内"}, "value": "1週間以内"},
                                {"text": {"type": "plain_text", "text": "最重要"}, "value": "最重要"},
                            ],
                            "action_id": "urgency_select",
                        },
                        "label": {
                            "type": "plain_text",
                            "text": "緊急度",
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
                                "text": "タスクの詳細を入力（任意）",
                            },
                        },
                        "label": {
                            "type": "plain_text",
                            "text": "内容詳細",
                        },
                        "optional": True
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