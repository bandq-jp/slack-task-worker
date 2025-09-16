from dataclasses import dataclass
from typing import Optional
from datetime import datetime
from src.domain.value_objects.email import Email
from src.domain.value_objects.notion_user_id import NotionUserId


@dataclass
class NotionUser:
    """Notionユーザーエンティティ"""
    user_id: NotionUserId
    name: str
    email: Email
    user_type: str  # 'person' or 'bot'
    object_type: str  # 'user'
    avatar_url: Optional[str] = None
    discovered_at: datetime = datetime.now()

    def is_guest_user(self) -> bool:
        """ゲストユーザーかどうか判定"""
        # ゲストユーザーは通常、正規メンバーではないため
        # users.list()で取得できない。この情報は実装時に検証する
        return True  # デフォルトではゲストユーザーとして扱う

    def is_person(self) -> bool:
        """人間ユーザーかどうか判定"""
        return self.user_type == 'person'

    def display_name(self) -> str:
        """表示用名前"""
        return self.name if self.name else str(self.email)

    @classmethod
    def from_notion_api_response(cls, api_response: dict) -> 'NotionUser':
        """Notion APIレスポンスからエンティティを作成"""
        person_data = api_response.get('person', {})
        
        return cls(
            user_id=NotionUserId(api_response['id']),
            name=api_response.get('name', ''),
            email=Email(person_data.get('email', '')),
            user_type=api_response.get('type', 'person'),
            object_type=api_response.get('object', 'user'),
            avatar_url=api_response.get('avatar_url')
        )

    def to_dict(self) -> dict:
        """辞書形式で返す（API用）"""
        return {
            'id': str(self.user_id),
            'name': self.name,
            'email': str(self.email),
            'type': self.user_type,
            'object': self.object_type,
            'avatar_url': self.avatar_url,
            'person': {
                'email': str(self.email)
            }
        }