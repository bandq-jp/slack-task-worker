from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    """ユーザーエンティティ"""
    slack_user_id: str
    slack_username: str
    email: str
    notion_user_id: Optional[str] = None

    def has_notion_account(self) -> bool:
        """Notionアカウントが紐付けられているか"""
        return self.notion_user_id is not None