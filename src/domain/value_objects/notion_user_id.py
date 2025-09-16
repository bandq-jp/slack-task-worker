from dataclasses import dataclass
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import Self
else:
    try:
        from typing import Self
    except ImportError:
        from typing_extensions import Self


@dataclass(frozen=True)
class NotionUserId:
    """NotionユーザーIDのバリューオブジェクト"""
    value: str

    def __post_init__(self):
        if not self._is_valid_notion_id(self.value):
            raise ValueError(f"Invalid Notion user ID format: {self.value}")

    def _is_valid_notion_id(self, notion_id: str) -> bool:
        """Notion IDの形式チェック"""
        if not notion_id:
            return False
        
        # NotionのIDは通常32文字のハイフンなしUUID形式
        if len(notion_id) == 32 and all(c.isalnum() or c in '-' for c in notion_id):
            return True
            
        # または36文字のUUID形式
        try:
            uuid.UUID(notion_id)
            return True
        except ValueError:
            return False

    def normalized(self) -> Self:
        """ハイフンなしの正規化されたID"""
        return NotionUserId(self.value.replace('-', ''))

    def __str__(self) -> str:
        return self.value