from typing import Optional, Dict
from src.domain.entities.user import User
from src.domain.repositories.user_repository import UserRepositoryInterface


class InMemoryUserRepository(UserRepositoryInterface):
    """インメモリユーザーリポジトリ実装"""

    def __init__(self):
        self._users_by_slack_id: Dict[str, User] = {}
        self._users_by_email: Dict[str, User] = {}

    async def find_by_slack_id(self, slack_user_id: str) -> Optional[User]:
        """SlackユーザーIDでユーザーを取得"""
        return self._users_by_slack_id.get(slack_user_id)

    async def find_by_email(self, email: str) -> Optional[User]:
        """メールアドレスでユーザーを取得"""
        return self._users_by_email.get(email.lower())

    async def save(self, user: User) -> User:
        """ユーザーを保存"""
        self._users_by_slack_id[user.slack_user_id] = user
        if user.email:
            self._users_by_email[user.email.lower()] = user
        return user