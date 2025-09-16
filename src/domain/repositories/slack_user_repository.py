from abc import ABC, abstractmethod
from typing import Optional
from src.domain.entities.slack_user import SlackUser
from src.domain.value_objects.email import Email
from src.domain.value_objects.slack_user_id import SlackUserId


class SlackUserRepositoryInterface(ABC):
    """Slackユーザーリポジトリのインターフェース"""

    @abstractmethod
    async def find_by_id(self, user_id: SlackUserId) -> Optional[SlackUser]:
        """SlackユーザーIDでユーザーを取得"""
        pass

    @abstractmethod
    async def find_by_email(self, email: Email) -> Optional[SlackUser]:
        """メールアドレスでユーザーを検索"""
        pass

    @abstractmethod
    async def get_user_info(self, user_id: str) -> Optional[SlackUser]:
        """ユーザー情報を取得（文字列IDから）"""
        pass