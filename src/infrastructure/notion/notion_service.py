import json
import os
from typing import Optional, Dict, Any, List, Union
from datetime import datetime
from notion_client import Client
from src.domain.entities.task import TaskRequest


class NotionService:
    """Notion APIサービス"""

    def __init__(self, notion_token: str, database_id: str):
        self.client = Client(auth=notion_token)
        self.database_id = self._normalize_database_id(database_id)
        self.user_mapping = self._load_user_mapping()
        self.mapping_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), '.user_mapping.json')

    def _normalize_database_id(self, database_id: str) -> str:
        """データベースIDを正規化（ハイフンを削除）"""
        return database_id.replace("-", "")

    def _load_user_mapping(self) -> Dict[str, Dict[str, Any]]:
        """ユーザーマッピングファイルを読み込み"""
        mapping_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), '.user_mapping.json')
        try:
            if os.path.exists(mapping_file):
                with open(mapping_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    email_mapping = data.get('email_to_notion_id', {})
                    print(f"✅ ユーザーマッピング読み込み: {len(email_mapping)}人")
                    return email_mapping
            else:
                print("⚠️ ユーザーマッピングファイルが見つかりません")
                return {}
        except Exception as e:
            print(f"❌ ユーザーマッピング読み込みエラー: {e}")
            return {}

    def _convert_slack_rich_text_to_notion(self, description: Union[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """SlackリッチテキストをNotionブロック形式に変換"""
        if isinstance(description, str):
            # プレーンテキストの場合
            return [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": description}}]
                    }
                }
            ]

        # Slackリッチテキスト形式の場合
        blocks = []

        try:
            if isinstance(description, dict) and "elements" in description:
                for element in description["elements"]:
                    if element.get("type") == "rich_text_section":
                        rich_text_items = []

                        for item in element.get("elements", []):
                            if item.get("type") == "text":
                                text_item = {
                                    "type": "text",
                                    "text": {"content": item.get("text", "")}
                                }

                                # スタイル適用
                                if "style" in item:
                                    annotations = {}
                                    style = item["style"]
                                    if style.get("bold"):
                                        annotations["bold"] = True
                                    if style.get("italic"):
                                        annotations["italic"] = True
                                    if style.get("strike"):
                                        annotations["strikethrough"] = True
                                    if style.get("code"):
                                        annotations["code"] = True

                                    if annotations:
                                        text_item["annotations"] = annotations

                                rich_text_items.append(text_item)

                            elif item.get("type") == "link":
                                rich_text_items.append({
                                    "type": "text",
                                    "text": {"content": item.get("text", item.get("url", ""))},
                                    "text": {"link": {"url": item.get("url", "")}}
                                })

                        if rich_text_items:
                            blocks.append({
                                "object": "block",
                                "type": "paragraph",
                                "paragraph": {"rich_text": rich_text_items}
                            })

                    elif element.get("type") == "rich_text_list":
                        # リストの処理
                        list_items = []
                        for list_item in element.get("elements", []):
                            if list_item.get("type") == "rich_text_section":
                                rich_text_items = []
                                for item in list_item.get("elements", []):
                                    if item.get("type") == "text":
                                        rich_text_items.append({
                                            "type": "text",
                                            "text": {"content": item.get("text", "")}
                                        })

                                if rich_text_items:
                                    list_items.append({
                                        "object": "block",
                                        "type": "bulleted_list_item",
                                        "bulleted_list_item": {"rich_text": rich_text_items}
                                    })

                        blocks.extend(list_items)

            if not blocks:
                # フォールバック: プレーンテキストとして処理
                blocks = [
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"type": "text", "text": {"content": str(description)}}]
                        }
                    }
                ]

        except Exception as e:
            print(f"Error converting rich text: {e}")
            # エラー時はプレーンテキストとして処理
            blocks = [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": str(description)}}]
                    }
                }
            ]

        return blocks

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
            else:
                print(f"⚠️ Requester '{requester_email}' not found in Notion users. Skipping people property.")

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
            else:
                print(f"⚠️ Assignee '{assignee_email}' not found in Notion users. Skipping people property.")

            # リッチテキストをNotionブロックに変換
            description_blocks = self._convert_slack_rich_text_to_notion(task.description)

            # ページを作成（詳細はページ本文に記載）
            page_children = [
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
            ]

            # リッチテキストブロックを追加
            page_children.extend(description_blocks)

            # 進捗メモセクションを追加
            page_children.extend([
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
            ])

            response = self.client.pages.create(
                parent={"database_id": self.database_id},
                properties=properties,
                children=page_children,
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
        """メールアドレスからNotionユーザーを検索（マッピングファイル使用）"""
        if not email:
            print(f"⚠️ Email is empty for user lookup")
            return None

        email_lower = email.lower()
        print(f"🔍 ユーザー検索: {email}")

        # Method 1: マッピングファイルから検索（高速）
        if email_lower in self.user_mapping:
            user_data = self.user_mapping[email_lower]
            print(f"✅ マッピングファイルで発見: {user_data['name']} ({email})")

            # Notionユーザーオブジェクト形式で返す
            return {
                'id': user_data['id'],
                'object': user_data.get('object', 'user'),
                'type': user_data.get('type', 'person'),
                'name': user_data['name'],
                'avatar_url': user_data.get('avatar_url'),
                'person': {'email': user_data['email']}
            }

        # Method 2: フォールバック - データベース検索
        print(f"⚠️ マッピングにない - データベース検索実行: {email}")
        fallback_user = await self._fallback_user_search(email)
        if fallback_user:
            # 見つかった場合はマッピングに追加
            await self._add_user_to_mapping(email, fallback_user)
            return fallback_user

        # Method 3: 従来のusers.list()検索（正規メンバー用）
        print(f"⚠️ DB検索でも見つからず - 正規メンバー検索: {email}")
        try:
            users = self.client.users.list()
            print(f"📋 正規メンバー検索: {len(users.get('results', []))}人")

            for user in users.get("results", []):
                if user.get("type") == "person":
                    user_email = user.get("person", {}).get("email")
                    if user_email and user_email.lower() == email_lower:
                        print(f"✅ 正規メンバーで発見: {user.get('name')} ({user_email})")
                        # マッピングに追加
                        await self._add_user_to_mapping(email, user)
                        return user

        except Exception as e:
            print(f"❌ 正規メンバー検索エラー: {e}")

        print(f"❌ ユーザーが見つかりません: {email}")
        print("💡 解決方法:")
        print(f"   1. update_user_mapping.py を使用してユーザーを追加")
        print(f"   2. setup_user_mapping.py を再実行してマッピングを更新")
        return None

    async def _fallback_user_search(self, email: str) -> Optional[Dict[str, Any]]:
        """フォールバック: データベース内のページからユーザーを検索"""
        try:
            pages = self.client.databases.query(database_id=self.database_id)

            for page in pages.get('results', []):
                properties = page.get('properties', {})

                for prop_name, prop_data in properties.items():
                    if prop_data.get('type') == 'people':
                        people = prop_data.get('people', [])

                        for person in people:
                            person_email = person.get('person', {}).get('email')
                            if person_email and person_email.lower() == email.lower():
                                print(f"✅ DB検索で発見: {person.get('name')} ({person_email})")
                                return {
                                    'id': person.get('id'),
                                    'object': person.get('object', 'user'),
                                    'type': person.get('type', 'person'),
                                    'name': person.get('name'),
                                    'avatar_url': person.get('avatar_url'),
                                    'person': {'email': person_email}
                                }

            return None

        except Exception as e:
            print(f"❌ フォールバック検索エラー: {e}")
            return None

    async def _add_user_to_mapping(self, email: str, user_data: Dict[str, Any]):
        """新しく発見したユーザーをマッピングファイルに追加"""
        try:
            email_lower = email.lower()

            # メモリ内マッピングを更新
            self.user_mapping[email_lower] = {
                'id': user_data['id'],
                'name': user_data['name'],
                'email': email,
                'type': user_data.get('type', 'person'),
                'object': user_data.get('object', 'user'),
                'avatar_url': user_data.get('avatar_url'),
                'last_updated': datetime.now().isoformat(),
                'auto_discovered': True
            }

            # ファイルを更新
            if os.path.exists(self.mapping_file):
                with open(self.mapping_file, 'r', encoding='utf-8') as f:
                    mapping_data = json.load(f)

                mapping_data['email_to_notion_id'][email_lower] = self.user_mapping[email_lower]
                mapping_data['last_updated'] = datetime.now().isoformat()

                with open(self.mapping_file, 'w', encoding='utf-8') as f:
                    json.dump(mapping_data, f, indent=2, ensure_ascii=False)

                print(f"✅ ユーザーマッピング自動追加: {user_data['name']} ({email})")

        except Exception as e:
            print(f"❌ マッピング追加エラー: {e}")

    def _get_status_name(self, status: str) -> str:
        """ステータスの表示名を取得"""
        status_map = {
            "pending": "承認待ち",
            "approved": "承認済み",
            "rejected": "差し戻し",
            "completed": "完了",
            "disabled": "無効",
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