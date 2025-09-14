from typing import Optional, Dict, Any
from notion_client import Client
from src.domain.entities.task import TaskRequest


class NotionService:
    """Notion APIサービス"""

    def __init__(self, notion_token: str, database_id: str):
        self.client = Client(auth=notion_token)
        self.database_id = database_id

    async def create_task(
        self,
        task: TaskRequest,
        requester_email: str,
        assignee_email: str,
    ) -> str:
        """Notionデータベースにタスクを作成"""
        try:
            # メールアドレスからNotionユーザーを検索
            requester_user = await self._find_user_by_email(requester_email)
            assignee_user = await self._find_user_by_email(assignee_email)

            # Notionページのプロパティを構築
            properties = {
                "タイトル": {
                    "title": [
                        {
                            "text": {
                                "content": task.title,
                            },
                        },
                    ],
                },
                "詳細": {
                    "rich_text": [
                        {
                            "text": {
                                "content": task.description,
                            },
                        },
                    ],
                },
                "納期": {
                    "date": {
                        "start": task.due_date.isoformat(),
                    },
                },
                "ステータス": {
                    "select": {
                        "name": self._get_status_name(task.status.value),
                    },
                },
            }

            # 依頼者プロパティ（Peopleタイプ）
            if requester_user:
                properties["依頼者"] = {
                    "people": [
                        {
                            "object": "user",
                            "id": requester_user["id"],
                        },
                    ],
                }

            # 依頼先プロパティ（Peopleタイプ）
            if assignee_user:
                properties["依頼先"] = {
                    "people": [
                        {
                            "object": "user",
                            "id": assignee_user["id"],
                        },
                    ],
                }

            # ページを作成
            response = self.client.pages.create(
                parent={"database_id": self.database_id},
                properties=properties,
                children=[
                    {
                        "object": "block",
                        "type": "heading_2",
                        "heading_2": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {
                                        "content": "タスク詳細",
                                    },
                                },
                            ],
                        },
                    },
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {
                                        "content": task.description,
                                    },
                                },
                            ],
                        },
                    },
                ],
            )

            return response["id"]

        except Exception as e:
            print(f"Error creating Notion task: {e}")
            raise

    async def _find_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """メールアドレスからNotionユーザーを検索"""
        if not email:
            return None

        try:
            # 全ユーザーを取得
            users = self.client.users.list()

            for user in users.get("results", []):
                # personタイプのユーザーのみチェック
                if user.get("type") == "person":
                    user_email = user.get("person", {}).get("email")
                    if user_email and user_email.lower() == email.lower():
                        return user

            return None

        except Exception as e:
            print(f"Error finding Notion user: {e}")
            return None

    def _get_status_name(self, status: str) -> str:
        """ステータスの表示名を取得"""
        status_map = {
            "pending": "承認待ち",
            "approved": "承認済み",
            "rejected": "差し戻し",
        }
        return status_map.get(status, "承認待ち")

    async def update_task_status(
        self,
        page_id: str,
        status: str,
        rejection_reason: Optional[str] = None,
    ):
        """タスクのステータスを更新"""
        try:
            properties = {
                "ステータス": {
                    "select": {
                        "name": self._get_status_name(status),
                    },
                },
            }

            # 差し戻し理由がある場合は追加
            if rejection_reason:
                properties["差し戻し理由"] = {
                    "rich_text": [
                        {
                            "text": {
                                "content": rejection_reason,
                            },
                        },
                    ],
                }

            self.client.pages.update(
                page_id=page_id,
                properties=properties,
            )

        except Exception as e:
            print(f"Error updating Notion task: {e}")
            raise