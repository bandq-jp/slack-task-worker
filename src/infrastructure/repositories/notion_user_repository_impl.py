from typing import List, Optional, Set
from notion_client import Client
from src.domain.entities.notion_user import NotionUser
from src.domain.repositories.notion_user_repository import NotionUserRepositoryInterface
from src.domain.value_objects.email import Email
from src.domain.value_objects.notion_user_id import NotionUserId
import logging

logger = logging.getLogger(__name__)


class NotionUserRepositoryImpl(NotionUserRepositoryInterface):
    """Notion APIを使用したユーザーリポジトリ実装"""

    def __init__(self, notion_token: str, default_database_id: str, mapping_database_id: Optional[str] = None):
        self.client = Client(auth=notion_token)
        self.default_database_id = self._normalize_database_id(default_database_id)
        # ユーザーマッピング専用DB（指定があればこちらを優先）
        self.mapping_database_id = (
            self._normalize_database_id(mapping_database_id)
            if mapping_database_id
            else None
        )

    def _normalize_database_id(self, database_id: str) -> str:
        """データベースIDを正規化（ハイフンを削除）"""
        return database_id.replace("-", "")

    async def find_by_email(self, email: Email) -> Optional[NotionUser]:
        """メールアドレスでユーザーを検索（複数ソースから）"""
        logger.info(f"🔍 ユーザー検索開始: {email}")

        # 1. データベースから検索（ゲストユーザー含む）
        # mapping_database_id が指定されていればそちらを優先
        target_db = self.mapping_database_id or self.default_database_id
        database_users = await self.search_users_in_database(target_db, email)
        
        if database_users:
            logger.info(f"✅ データベースで発見: {database_users[0].name} ({email})")
            return database_users[0]

        # 2. 正規メンバーから検索
        workspace_users = await self.get_all_workspace_users()
        for user in workspace_users:
            if user.email.normalized() == email.normalized():
                logger.info(f"✅ 正規メンバーで発見: {user.name} ({email})")
                return user

        logger.warning(f"❌ ユーザーが見つかりません: {email}")
        return None

    async def find_by_id(self, user_id: NotionUserId) -> Optional[NotionUser]:
        """ユーザーIDでユーザーを取得"""
        try:
            response = self.client.users.retrieve(user_id=str(user_id))
            return NotionUser.from_notion_api_response(response)
        except Exception as e:
            logger.warning(f"❌ ユーザーID検索エラー {user_id}: {e}")
            return None

    async def search_users_in_database(
        self, 
        database_id: str,
        email: Optional[Email] = None
    ) -> List[NotionUser]:
        """データベース内のPeopleプロパティからユーザーを検索"""
        users = []
        try:
            logger.info(f"📊 データベース検索開始: {database_id}")
            
            # データベース内の全ページを取得
            has_more = True
            next_cursor = None
            pages_scanned = 0
            
            while has_more:
                query_params = {"database_id": database_id}
                if next_cursor:
                    query_params["start_cursor"] = next_cursor

                response = self.client.databases.query(**query_params)
                pages = response.get('results', [])
                pages_scanned += len(pages)

                for page in pages:
                    page_users = self._extract_users_from_page(page, email)
                    users.extend(page_users)

                has_more = response.get('has_more', False)
                next_cursor = response.get('next_cursor')

            logger.info(f"📋 データベーススキャン完了: {pages_scanned}ページ, {len(users)}ユーザー発見")
            
            # 重複除去（メールアドレスベース）
            unique_users = self._deduplicate_users(users)
            return unique_users

        except Exception as e:
            # Notionの結合データベース（multi-source）に対するAPI制約の明示化
            if "multiple data sources" in str(e).lower():
                logger.error(
                    "❌ データベース検索エラー: このデータベースは複数データソースに接続されています。"
                    " Notion APIではqueryがサポートされないため、'mapping_database_id' に単一ソースのDBを指定してください。"
                )
            else:
                logger.error(f"❌ データベース検索エラー: {e}")
            return []

    async def search_users_by_domain(self, domain: str) -> List[NotionUser]:
        """ドメイン名でユーザーを検索"""
        all_users = await self.get_users_from_database_properties(self.default_database_id)
        
        return [
            user for user in all_users
            if user.email.domain().lower() == domain.lower()
        ]

    async def get_all_workspace_users(self) -> List[NotionUser]:
        """ワークスペースの全正規ユーザーを取得（users.list()）"""
        users = []
        try:
            response = self.client.users.list()
            logger.info(f"👥 正規メンバー取得: {len(response.get('results', []))}人")
            
            for user_data in response.get("results", []):
                if user_data.get("type") == "person":
                    try:
                        user = NotionUser.from_notion_api_response(user_data)
                        users.append(user)
                    except Exception as e:
                        logger.warning(f"⚠️ ユーザー変換エラー: {e}")
                        continue
            
            return users
        
        except Exception as e:
            logger.error(f"❌ 正規メンバー取得エラー: {e}")
            return []

    async def get_users_from_database_properties(
        self, 
        database_id: str,
        property_names: Optional[List[str]] = None
    ) -> List[NotionUser]:
        """データベースのPeopleプロパティから全ユーザーを抽出"""
        return await self.search_users_in_database(database_id)

    def _extract_users_from_page(
        self, 
        page: dict, 
        target_email: Optional[Email] = None
    ) -> List[NotionUser]:
        """ページからユーザー情報を抽出"""
        users = []
        properties = page.get('properties', {})

        for prop_name, prop_data in properties.items():
            if prop_data.get('type') == 'people':
                people = prop_data.get('people', [])

                for person in people:
                    try:
                        person_email = person.get('person', {}).get('email')
                        if not person_email:
                            continue

                        # 特定のメールアドレスを検索中の場合、一致チェック
                        if target_email and Email(person_email).normalized() != target_email.normalized():
                            continue

                        user = NotionUser.from_notion_api_response(person)
                        users.append(user)
                        
                        # 特定のメール検索の場合、最初のマッチで終了
                        if target_email:
                            return users

                    except Exception as e:
                        logger.warning(f"⚠️ ユーザー抽出エラー: {e}")
                        continue

        return users

    def _deduplicate_users(self, users: List[NotionUser]) -> List[NotionUser]:
        """ユーザーリストから重複を削除（メールアドレスベース）"""
        seen_emails: Set[str] = set()
        unique_users = []

        for user in users:
            email_key = str(user.email.normalized())
            if email_key not in seen_emails:
                seen_emails.add(email_key)
                unique_users.append(user)

        if len(users) != len(unique_users):
            logger.info(f"🔄 重複ユーザー削除: {len(users)} → {len(unique_users)}")

        return unique_users
