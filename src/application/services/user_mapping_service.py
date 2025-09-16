from typing import Optional
from src.domain.entities.user_mapping import UserMapping
from src.domain.entities.slack_user import SlackUser
from src.domain.entities.notion_user import NotionUser
from src.domain.repositories.notion_user_repository import NotionUserRepositoryInterface
from src.domain.repositories.slack_user_repository import SlackUserRepositoryInterface
from src.domain.services.user_mapping_domain_service import UserMappingDomainService
from src.domain.value_objects.email import Email
from src.domain.value_objects.slack_user_id import SlackUserId
import logging

logger = logging.getLogger(__name__)


class UserMappingApplicationService:
    """ユーザーマッピングのアプリケーションサービス"""

    def __init__(
        self,
        notion_user_repository: NotionUserRepositoryInterface,
        slack_user_repository: SlackUserRepositoryInterface,
        mapping_domain_service: UserMappingDomainService
    ):
        self.notion_user_repository = notion_user_repository
        self.slack_user_repository = slack_user_repository
        self.mapping_domain_service = mapping_domain_service

    async def find_notion_user_by_email(self, email: str) -> Optional[NotionUser]:
        """メールアドレスからNotionユーザーを動的検索"""
        try:
            email_vo = Email(email)
            logger.info(f"🔍 Notion ユーザー検索: {email}")
            
            notion_user = await self.notion_user_repository.find_by_email(email_vo)
            
            if notion_user:
                logger.info(f"✅ Notion ユーザー発見: {notion_user.display_name()} ({email})")
                return notion_user
            else:
                logger.warning(f"❌ Notion ユーザー未発見: {email}")
                return None
                
        except ValueError as e:
            logger.error(f"❌ 無効なメールアドレス {email}: {e}")
            return None

    async def create_user_mapping(
        self, 
        slack_user_id: str,
        requester_email: str
    ) -> Optional[UserMapping]:
        """SlackユーザーIDとメールアドレスからマッピングを作成"""
        try:
            # Slackユーザー情報を取得
            slack_user = await self.slack_user_repository.get_user_info(slack_user_id)
            if not slack_user:
                logger.error(f"❌ Slack ユーザー未発見: {slack_user_id}")
                return None

            # Notionユーザー情報を検索
            notion_user = await self.find_notion_user_by_email(requester_email)
            if not notion_user:
                logger.error(f"❌ Notion ユーザー未発見: {requester_email}")
                return None

            # ドメインサービスでマッピング作成
            mapping = self.mapping_domain_service.find_best_mapping(
                slack_user, 
                [notion_user]
            )

            if mapping:
                logger.info(f"✅ マッピング作成成功: {mapping.to_dict()}")
                return mapping
            else:
                logger.warning(f"❌ マッピング作成失敗: confidence不足")
                return None

        except Exception as e:
            logger.error(f"❌ マッピング作成エラー: {e}")
            return None

    async def get_notion_user_for_task_creation(
        self,
        requester_email: str,
        assignee_email: str
    ) -> tuple[Optional[NotionUser], Optional[NotionUser]]:
        """タスク作成用にNotionユーザーを取得"""
        logger.info(f"📝 タスク作成用ユーザー検索: {requester_email}, {assignee_email}")

        # 依頼者のNotionユーザー検索
        requester = await self.find_notion_user_by_email(requester_email)
        
        # 依頼先のNotionユーザー検索
        assignee = await self.find_notion_user_by_email(assignee_email)

        if requester and assignee:
            logger.info(f"✅ 両ユーザー発見完了")
        elif requester:
            logger.warning(f"⚠️ 依頼先ユーザーが見つかりません: {assignee_email}")
        elif assignee:
            logger.warning(f"⚠️ 依頼者ユーザーが見つかりません: {requester_email}")
        else:
            logger.error(f"❌ 両ユーザーが見つかりません")

        return requester, assignee

    async def validate_user_mapping(self, mapping: UserMapping) -> bool:
        """ユーザーマッピングの妥当性検証"""
        return self.mapping_domain_service.validate_mapping(mapping)

    async def should_auto_approve_mapping(self, mapping: UserMapping) -> bool:
        """自動承認判定"""
        return self.mapping_domain_service.should_auto_approve_mapping(mapping)