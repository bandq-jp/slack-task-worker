from dataclasses import dataclass
from typing import Optional
from datetime import datetime
from src.domain.entities.notion_user import NotionUser
from src.domain.entities.slack_user import SlackUser
from src.domain.value_objects.email import Email


@dataclass
class UserMapping:
    """SlackユーザーとNotionユーザーのマッピングエンティティ"""
    slack_user: SlackUser
    notion_user: NotionUser
    mapped_at: datetime
    confidence: float  # マッピングの信頼度（0.0-1.0）
    mapping_source: str  # 'email_exact', 'email_domain', 'manual', etc.

    def is_high_confidence(self) -> bool:
        """高信頼度のマッピングかどうか"""
        return self.confidence >= 0.9

    def is_email_based(self) -> bool:
        """メールアドレスベースのマッピングかどうか"""
        return self.mapping_source.startswith('email_')

    def emails_match(self) -> bool:
        """メールアドレスが完全に一致するかどうか"""
        return self.slack_user.email.normalized() == self.notion_user.email.normalized()

    @classmethod
    def create_email_exact_mapping(
        cls, 
        slack_user: SlackUser, 
        notion_user: NotionUser
    ) -> 'UserMapping':
        """メール完全一致による高信頼度マッピング作成"""
        return cls(
            slack_user=slack_user,
            notion_user=notion_user,
            mapped_at=datetime.now(),
            confidence=1.0,
            mapping_source='email_exact'
        )

    @classmethod
    def create_email_domain_mapping(
        cls,
        slack_user: SlackUser,
        notion_user: NotionUser,
        confidence: float = 0.7
    ) -> 'UserMapping':
        """メールドメイン一致による中信頼度マッピング作成"""
        return cls(
            slack_user=slack_user,
            notion_user=notion_user,
            mapped_at=datetime.now(),
            confidence=confidence,
            mapping_source='email_domain'
        )

    def to_dict(self) -> dict:
        """辞書形式で返す（ログ・デバッグ用）"""
        return {
            'slack_user': {
                'id': str(self.slack_user.user_id),
                'name': self.slack_user.effective_name(),
                'email': str(self.slack_user.email)
            },
            'notion_user': {
                'id': str(self.notion_user.user_id),
                'name': self.notion_user.name,
                'email': str(self.notion_user.email)
            },
            'confidence': self.confidence,
            'source': self.mapping_source,
            'mapped_at': self.mapped_at.isoformat()
        }