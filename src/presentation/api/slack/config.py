from pydantic_settings import BaseSettings


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
    gemini_api_key: str = ""
    gemini_timeout_seconds: float = 30.0
    gemini_model: str = "gemini-2.5-flash"
    gemini_history_path: str = ".ai_conversations.json"

    class Config:
        env_file = ".env"

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
