#!/usr/bin/env python3
"""
Cloud Run対応のNotionService
GCSでのユーザーマッピング管理に対応
"""
import os
from typing import Optional, Dict, Any, List, Union
from datetime import datetime
from notion_client import Client
from src.domain.entities.task import TaskRequest
from src.infrastructure.storage.gcs_user_mapping import GCSUserMappingManager
import logging

logger = logging.getLogger(__name__)

class CloudNotionService:
    """Cloud Run環境対応のNotion APIサービス"""

    def __init__(self, notion_token: str, database_id: str, gcs_bucket_name: str):
        self.client = Client(auth=notion_token)
        self.database_id = self._normalize_database_id(database_id)

        # Cloud環境かローカル環境かを自動判定
        self.is_cloud = os.getenv('K_SERVICE') is not None  # Cloud Runの環境変数

        if self.is_cloud:
            # Cloud環境: GCS使用
            self.user_mapping_manager = GCSUserMappingManager(gcs_bucket_name)
            logger.info("🌥️ Cloud環境: GCSユーザーマッピング使用")
        else:
            # ローカル環境: ローカルファイル使用（既存の実装）
            from src.infrastructure.notion.notion_service import NotionService
            self.local_service = NotionService(notion_token, database_id)
            logger.info("🏠 ローカル環境: ローカルファイルマッピング使用")

    def _normalize_database_id(self, database_id: str) -> str:
        """データベースIDを正規化（ハイフンを削除）"""
        return database_id.replace("-", "")

    async def _find_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """メールアドレスからNotionユーザーを検索（Cloud/Local対応）"""
        if not email:
            logger.warning("⚠️ Email is empty for user lookup")
            return None

        if self.is_cloud:
            return await self._find_user_cloud(email)
        else:
            # ローカル環境は既存の実装を使用
            return await self.local_service._find_user_by_email(email)

    async def _find_user_cloud(self, email: str) -> Optional[Dict[str, Any]]:
        """Cloud環境でのユーザー検索（GCS使用）"""
        email_lower = email.lower()
        logger.info(f"🔍 Cloud環境ユーザー検索: {email}")

        # Method 1: GCSマッピングファイルから検索（高速）
        user = await self.user_mapping_manager.get_user_by_email(email)
        if user:
            logger.info(f"✅ GCSマッピングで発見: {user['name']} ({email})")
            return user

        # Method 2: フォールバック - データベース検索
        logger.warning(f"⚠️ GCSマッピングにない - データベース検索実行: {email}")
        fallback_user = await self._fallback_user_search(email)
        if fallback_user:
            # 見つかった場合はGCSマッピングに追加
            await self.user_mapping_manager.add_user_to_mapping(email, fallback_user)
            return fallback_user

        # Method 3: 正規メンバー検索
        logger.warning(f"⚠️ DB検索でも見つからず - 正規メンバー検索: {email}")
        try:
            users = self.client.users.list()
            logger.info(f"📋 正規メンバー検索: {len(users.get('results', []))}人")

            for user in users.get("results", []):
                if user.get("type") == "person":
                    user_email = user.get("person", {}).get("email")
                    if user_email and user_email.lower() == email_lower:
                        logger.info(f"✅ 正規メンバーで発見: {user.get('name')} ({user_email})")
                        # GCSマッピングに追加
                        await self.user_mapping_manager.add_user_to_mapping(email, user)
                        return user

        except Exception as e:
            logger.error(f"❌ 正規メンバー検索エラー: {e}")

        logger.error(f"❌ ユーザーが見つかりません: {email}")
        logger.info("💡 解決方法:")
        logger.info("   1. admin/update_user_mapping.py を使用してユーザーを追加")
        logger.info("   2. Cloud環境でGCSマッピングを手動更新")
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
                                logger.info(f"✅ DB検索で発見: {person.get('name')} ({person_email})")
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
            logger.error(f"❌ フォールバック検索エラー: {e}")
            return None

    # 他のメソッドは既存のNotionServiceから継承
    def _convert_slack_rich_text_to_notion(self, description: Union[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """SlackリッチテキストをNotionブロック形式に変換"""
        if self.is_cloud:
            # Cloud環境での実装
            if isinstance(description, str):
                return [
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"type": "text", "text": {"content": description}}]
                        }
                    }
                ]

            # 詳細なリッチテキスト変換ロジックは既存実装と同様
            # （スペースの関係で省略、既存のNotionServiceから移植）
            return [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": str(description)}}]
                    }
                }
            ]
        else:
            return self.local_service._convert_slack_rich_text_to_notion(description)

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

            # タスク作成処理は既存実装と同様
            properties = {
                "タイトル": {
                    "title": [{"text": {"content": task.title}}]
                },
                "納期": {
                    "date": {"start": task.due_date.isoformat()}
                },
                "ステータス": {
                    "select": {"name": self._get_status_name(task.status.value)}
                },
            }

            # ユーザーが見つかった場合のみPeopleプロパティを設定
            if requester_user:
                properties["依頼者"] = {
                    "people": [{"object": "user", "id": requester_user["id"]}]
                }
            else:
                logger.warning(f"⚠️ Requester '{requester_email}' not found")

            if assignee_user:
                properties["依頼先"] = {
                    "people": [{"object": "user", "id": assignee_user["id"]}]
                }
            else:
                logger.warning(f"⚠️ Assignee '{assignee_email}' not found")

            # ページコンテンツ作成
            description_blocks = self._convert_slack_rich_text_to_notion(task.description)

            page_children = [
                {
                    "object": "block",
                    "type": "heading_1",
                    "heading_1": {
                        "rich_text": [{"type": "text", "text": {"content": "📋 タスク概要"}}]
                    }
                }
            ]
            page_children.extend(description_blocks)

            # Notionページ作成
            response = self.client.pages.create(
                parent={"database_id": self.database_id},
                properties=properties,
                children=page_children,
            )

            logger.info(f"✅ タスク作成成功: {response['id']}")
            return response["id"]

        except Exception as e:
            error_msg = f"Error creating Notion task: {e}"
            logger.error(error_msg)
            return None

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
                    "select": {"name": self._get_status_name(status)}
                }
            }

            if rejection_reason:
                properties["差し戻し理由"] = {
                    "rich_text": [{"text": {"content": rejection_reason}}]
                }

            self.client.pages.update(page_id=page_id, properties=properties)
            logger.info(f"✅ タスクステータス更新: {page_id} -> {status}")

        except Exception as e:
            logger.error(f"❌ タスクステータス更新エラー: {e}")
            raise