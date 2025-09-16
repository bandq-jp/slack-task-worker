from dataclasses import dataclass
from typing import Optional
from src.domain.value_objects.email import Email
from src.domain.value_objects.slack_user_id import SlackUserId


@dataclass
class SlackUser:
    """Slackユーザーエンティティ"""
    user_id: SlackUserId
    username: str
    email: Email
    display_name: Optional[str] = None
    real_name: Optional[str] = None
    avatar_url: Optional[str] = None

    def effective_name(self) -> str:
        """有効な名前を返す（優先順位: real_name > display_name > username）"""
        return self.real_name or self.display_name or self.username

    @classmethod
    def from_slack_api_response(cls, api_response: dict) -> 'SlackUser':
        """Slack APIレスポンスからエンティティを作成"""
        profile = api_response.get('profile', {})
        
        return cls(
            user_id=SlackUserId(api_response['id']),
            username=api_response.get('name', ''),
            email=Email(profile.get('email', '')),
            display_name=profile.get('display_name'),
            real_name=profile.get('real_name'),
            avatar_url=profile.get('image_512')
        )