from dataclasses import dataclass


@dataclass(frozen=True)
class SlackUserId:
    """SlackユーザーIDのバリューオブジェクト"""
    value: str

    def __post_init__(self):
        if not self._is_valid_slack_id(self.value):
            raise ValueError(f"Invalid Slack user ID format: {self.value}")

    def _is_valid_slack_id(self, slack_id: str) -> bool:
        """Slack IDの形式チェック"""
        if not slack_id:
            return False
        
        # SlackのユーザーIDは通常'U'で始まる11文字の文字列
        if slack_id.startswith('U') and len(slack_id) == 11:
            return all(c.isalnum() for c in slack_id[1:])
        
        return False

    def __str__(self) -> str:
        return self.value