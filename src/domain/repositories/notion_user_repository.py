from abc import ABC, abstractmethod
from typing import List, Optional
from src.domain.entities.notion_user import NotionUser
from src.domain.value_objects.email import Email
from src.domain.value_objects.notion_user_id import NotionUserId


class NotionUserRepositoryInterface(ABC):
    """Notionユーザーリポジトリのインターフェース"""

    @abstractmethod
    async def find_by_email(self, email: Email) -> Optional[NotionUser]:
        """メールアドレスでユーザーを検索"""
        pass

    @abstractmethod
    async def find_by_id(self, user_id: NotionUserId) -> Optional[NotionUser]:
        """ユーザーIDでユーザーを取得"""
        pass

    @abstractmethod
    async def search_users_in_database(
        self, 
        database_id: str,
        email: Optional[Email] = None
    ) -> List[NotionUser]:
        """データベース内のPeopleプロパティからユーザーを検索"""
        pass

    @abstractmethod
    async def search_users_by_domain(self, domain: str) -> List[NotionUser]:
        """ドメイン名でユーザーを検索"""
        pass

    @abstractmethod
    async def get_all_workspace_users(self) -> List[NotionUser]:
        """ワークスペースの全正規ユーザーを取得（users.list()）"""
        pass

    @abstractmethod
    async def get_users_from_database_properties(
        self, 
        database_id: str,
        property_names: Optional[List[str]] = None
    ) -> List[NotionUser]:
        """データベースのPeopleプロパティから全ユーザーを抽出"""
        pass