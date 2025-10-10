import json
from typing import List, Optional, Union

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    slack_token: str = ""
    slack_bot_token: str = ""
    slack_signing_secret: str = ""
    notion_token: str = ""
    notion_database_id: str = ""
    notion_audit_database_id: str = ""
    mapping_database_id: str = ""
    notion_metrics_database_id: str = ""
    notion_assignee_summary_database_id: str = ""
    gcs_bucket_name: str = ""
    google_application_credentials: str = ""
    service_account_json: str = ""
    env: str = "local"
    task_event_notification_emails_raw: Optional[Union[str, List[str]]] = Field(
        default=None,
        alias="task_event_notification_emails",
    )
    gemini_api_key: str = ""
    gemini_timeout_seconds: float = 30.0
    gemini_model: str = "gemini-2.5-flash"
    gemini_history_path: str = ".ai_conversations.json"

    model_config = SettingsConfigDict(
        env_file=".env",
        populate_by_name=True,
    )

    @property
    def slack_command_name(self) -> str:
        """環境に応じてスラッシュコマンド名を返す"""
        if self.env == "production":
            return "/task-request"
        else:
            return "/task-request-dev"

    @property
    def app_name_suffix(self) -> str:
        """環境に応じてアプリ名の接尾辞を返す"""
        if self.env == "production":
            return ""
        else:
            return " (Dev)"

    @property
    def task_event_notification_emails(self) -> List[str]:
        """通知先メールアドレスを正規化して返す"""
        raw = self.task_event_notification_emails_raw

        if raw is None:
            return []

        if isinstance(raw, list):
            return [item.strip() for item in raw if isinstance(item, str) and item.strip()]

        if isinstance(raw, str):
            stripped = raw.strip()
            if not stripped:
                return []

            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return [
                        item.strip()
                        for item in parsed
                        if isinstance(item, str) and item.strip()
                    ]
            except json.JSONDecodeError:
                pass

            return [item.strip() for item in stripped.split(",") if item.strip()]

        return []
