from typing import Optional, Dict, Any
from notion_client import Client
from src.domain.entities.task import TaskRequest


class NotionService:
    """Notion APIサービス"""

    def __init__(self, notion_token: str, database_id: str):
        self.client = Client(auth=notion_token)
        self.database_id = self._normalize_database_id(database_id)

    def _normalize_database_id(self, database_id: str) -> str:
        """データベースIDを正規化（ハイフンを削除）"""
        return database_id.replace("-", "")

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

            # Notionページのプロパティを構築（詳細はページ本文に記載）
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
                "納期": {
                    "date": {
                        "start": task.due_date.isoformat(),
                    },
                },
                "ステータス": {
                    "status": {
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

            # ページを作成（詳細はページ本文に記載）
            response = self.client.pages.create(
                parent={"database_id": self.database_id},
                properties=properties,
                children=[
                    {
                        "object": "block",
                        "type": "heading_1",
                        "heading_1": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {
                                        "content": "📋 タスク概要",
                                    },
                                },
                            ],
                        },
                    },
                    {
                        "object": "block",
                        "type": "callout",
                        "callout": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {
                                        "content": f"依頼者: {requester_email or 'Unknown'}\n"
                                                  f"依頼先: {assignee_email or 'Unknown'}\n"
                                                  f"納期: {task.due_date.strftime('%Y年%m月%d日 %H:%M')}",
                                    },
                                },
                            ],
                            "icon": {
                                "emoji": "ℹ️",
                            },
                            "color": "blue_background",
                        },
                    },
                    {
                        "object": "block",
                        "type": "divider",
                        "divider": {},
                    },
                    {
                        "object": "block",
                        "type": "heading_2",
                        "heading_2": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {
                                        "content": "📝 タスク内容",
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
                                        "content": task.description or "詳細な説明はありません。",
                                    },
                                },
                            ],
                        },
                    },
                    {
                        "object": "block",
                        "type": "divider",
                        "divider": {},
                    },
                    {
                        "object": "block",
                        "type": "heading_2",
                        "heading_2": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {
                                        "content": "✅ 進捗メモ",
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
                                        "content": "（ここに進捗や作業メモを記入してください）",
                                    },
                                },
                            ],
                        },
                    },
                ],
            )

            return response["id"]

        except Exception as e:
            error_msg = f"Error creating Notion task: {e}"
            print(error_msg)
            print(f"Database ID: {self.database_id}")
            print(f"Task details: title='{task.title}', description='{task.description[:100]}...'")

            # 権限エラーの場合の詳細メッセージ
            if "shared with your integration" in str(e):
                print("\n🔧 解決方法:")
                print("1. Notionでデータベースページを開く")
                print("2. 右上の「共有」ボタンをクリック")
                print("3. 「Task Request Bot」Integrationを招待")
                print("4. 「招待」をクリック")

            # データベースが見つからない場合
            elif "Could not find database" in str(e):
                print("\n🔧 データベースIDエラー:")
                print(f"指定されたID '{self.database_id}' のデータベースが見つかりません")
                print("1. NotionデータベースのURLを確認")
                print("2. 環境変数 NOTION_DATABASE_ID を正しく設定")

            # プロパティエラーの場合
            elif "property" in str(e).lower():
                print("\n🔧 プロパティエラー:")
                print("以下のプロパティが正しく設定されているか確認:")
                print("- タイトル (Title)")
                print("- 納期 (Date)")
                print("- ステータス (Select: 承認待ち, 承認済み, 差し戻し)")
                print("- 依頼者 (Person)")
                print("- 依頼先 (Person)")

            # エラーを再発生させず、None を返す
            return None

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
                    "status": {
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