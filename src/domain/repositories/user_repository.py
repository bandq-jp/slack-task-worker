from abc import ABC, abstractmethod
from typing import Optional
from src.domain.entities.user import User


class UserRepositoryInterface(ABC):
    """ユーザーリポジトリのインターフェース"""

    @abstractmethod
    async def find_by_slack_id(self, slack_user_id: str) -> Optional[User]:
        """SlackユーザーIDでユーザーを取得"""
        pass

    @abstractmethod
    async def find_by_email(self, email: str) -> Optional[User]:
        """メールアドレスでユーザーを取得"""
        pass

    @abstractmethod
    async def save(self, user: User) -> User:
        """ユーザーを保存"""
        pass