from typing import List, Optional
from src.domain.entities.slack_user import SlackUser
from src.domain.entities.notion_user import NotionUser
from src.domain.entities.user_mapping import UserMapping
from src.domain.value_objects.email import Email


class UserMappingDomainService:
    """ユーザーマッピングのドメインサービス"""

    def find_best_mapping(
        self,
        slack_user: SlackUser,
        notion_users: List[NotionUser]
    ) -> Optional[UserMapping]:
        """最適なユーザーマッピングを見つける"""
        if not notion_users:
            return None

        # 1. メールアドレス完全一致（最優先）
        exact_match = self._find_email_exact_match(slack_user, notion_users)
        if exact_match:
            return UserMapping.create_email_exact_mapping(slack_user, exact_match)

        # 2. メールドメイン一致
        domain_match = self._find_email_domain_match(slack_user, notion_users)
        if domain_match:
            return UserMapping.create_email_domain_mapping(slack_user, domain_match)

        # 3. 名前の類似性による一致（将来的に実装可能）
        # name_match = self._find_name_similarity_match(slack_user, notion_users)
        
        return None

    def _find_email_exact_match(
        self,
        slack_user: SlackUser,
        notion_users: List[NotionUser]
    ) -> Optional[NotionUser]:
        """メールアドレス完全一致検索"""
        slack_email_normalized = slack_user.email.normalized()
        
        for notion_user in notion_users:
            if notion_user.email.normalized() == slack_email_normalized:
                return notion_user
        
        return None

    def _find_email_domain_match(
        self,
        slack_user: SlackUser,
        notion_users: List[NotionUser]
    ) -> Optional[NotionUser]:
        """メールドメイン一致検索"""
        slack_domain = slack_user.email.domain()
        
        # 同一ドメインのNotionユーザーを検索
        domain_matches = [
            user for user in notion_users
            if user.email.domain() == slack_domain
        ]
        
        if len(domain_matches) == 1:
            # ドメイン内で唯一の場合のみマッチング
            return domain_matches[0]
        
        # 複数候補がある場合は手動確認が必要
        return None

    def calculate_mapping_confidence(
        self,
        slack_user: SlackUser,
        notion_user: NotionUser
    ) -> float:
        """マッピングの信頼度を計算"""
        confidence = 0.0
        
        # メール完全一致
        if slack_user.email.normalized() == notion_user.email.normalized():
            confidence += 0.6
        
        # ドメイン一致
        elif slack_user.email.domain() == notion_user.email.domain():
            confidence += 0.3
        
        # 名前の類似性（簡易版）
        slack_name = slack_user.effective_name().lower()
        notion_name = notion_user.name.lower()
        
        if slack_name == notion_name:
            confidence += 0.3
        elif slack_name in notion_name or notion_name in slack_name:
            confidence += 0.1
        
        return min(confidence, 1.0)

    def validate_mapping(self, mapping: UserMapping) -> bool:
        """マッピングの妥当性検証"""
        # 基本的な検証
        if not mapping.slack_user or not mapping.notion_user:
            return False
        
        # メールアドレスの検証
        try:
            slack_email = mapping.slack_user.email
            notion_email = mapping.notion_user.email
        except ValueError:
            # 無効なメールアドレス
            return False
        
        # 信頼度の検証
        if mapping.confidence < 0.0 or mapping.confidence > 1.0:
            return False
        
        # ソースタイプの検証
        valid_sources = ['email_exact', 'email_domain', 'manual', 'name_similarity']
        if mapping.mapping_source not in valid_sources:
            return False
        
        return True

    def should_auto_approve_mapping(self, mapping: UserMapping) -> bool:
        """自動承認すべきマッピングかどうか"""
        # 高信頼度かつメール完全一致の場合のみ自動承認
        return (
            mapping.is_high_confidence() and
            mapping.emails_match() and
            mapping.mapping_source == 'email_exact'
        )