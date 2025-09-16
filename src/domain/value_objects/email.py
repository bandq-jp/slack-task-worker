from dataclasses import dataclass
import re
from typing import Self


@dataclass(frozen=True)
class Email:
    """メールアドレスのバリューオブジェクト"""
    value: str

    def __post_init__(self):
        if not self._is_valid_email(self.value):
            raise ValueError(f"Invalid email format: {self.value}")

    def _is_valid_email(self, email: str) -> bool:
        """メールアドレス形式の妥当性チェック"""
        if not email:
            return False
        
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))

    def domain(self) -> str:
        """メールアドレスのドメイン部分を取得"""
        return self.value.split('@')[1]

    def local_part(self) -> str:
        """メールアドレスのローカル部分を取得"""
        return self.value.split('@')[0]

    def normalized(self) -> Self:
        """正規化されたメールアドレス（小文字）"""
        return Email(self.value.lower())

    def __str__(self) -> str:
        return self.value