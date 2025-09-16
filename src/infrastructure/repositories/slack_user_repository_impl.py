from typing import Optional
from slack_sdk import WebClient
from src.domain.entities.slack_user import SlackUser
from src.domain.repositories.slack_user_repository import SlackUserRepositoryInterface
from src.domain.value_objects.email import Email
from src.domain.value_objects.slack_user_id import SlackUserId
import logging

logger = logging.getLogger(__name__)


class SlackUserRepositoryImpl(SlackUserRepositoryInterface):
    """Slack APIを使用したユーザーリポジトリ実装"""

    def __init__(self, slack_token: str):
        self.client = WebClient(token=slack_token)

    async def find_by_id(self, user_id: SlackUserId) -> Optional[SlackUser]:
        """SlackユーザーIDでユーザーを取得"""
        try:
            response = self.client.users_info(user=str(user_id))
            
            if response["ok"] and response.get("user"):
                user_data = response["user"]
                return SlackUser.from_slack_api_response(user_data)
                
            return None
            
        except Exception as e:
            logger.error(f"❌ Slack ユーザー取得エラー {user_id}: {e}")
            return None

    async def find_by_email(self, email: Email) -> Optional[SlackUser]:
        """メールアドレスでユーザーを検索"""
        try:
            response = self.client.users_lookupByEmail(email=str(email))
            
            if response["ok"] and response.get("user"):
                user_data = response["user"]
                return SlackUser.from_slack_api_response(user_data)
                
            return None
            
        except Exception as e:
            logger.warning(f"⚠️ Slack メール検索エラー {email}: {e}")
            return None

    async def get_user_info(self, user_id: str) -> Optional[SlackUser]:
        """ユーザー情報を取得（文字列IDから）"""
        try:
            slack_user_id = SlackUserId(user_id)
            return await self.find_by_id(slack_user_id)
        except ValueError as e:
            logger.error(f"❌ 無効なSlack ユーザーID {user_id}: {e}")
            return None