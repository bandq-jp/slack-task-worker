from dataclasses import dataclass
from typing import Optional
from datetime import datetime


@dataclass
class CalendarTask:
    """カレンダータスクエンティティ

    Googleカレンダーのタスクを表現するドメインモデル
    """

    id: Optional[str]  # Google Tasks APIで生成されるID
    title: str
    notes: str
    due_date: Optional[datetime]
    user_email: str
    task_request_id: str  # 元となるタスク依頼のID
    created_at: datetime
    updated_at: Optional[datetime] = None
    status: str = "needsAction"  # needsAction or completed

    def mark_as_completed(self) -> None:
        """タスクを完了状態にする"""
        self.status = "completed"
        self.updated_at = datetime.now()

    def update_due_date(self, new_due_date: datetime) -> None:
        """期限を更新する"""
        self.due_date = new_due_date
        self.updated_at = datetime.now()

    def to_dict(self) -> dict:
        """辞書形式に変換"""
        return {
            "id": self.id,
            "title": self.title,
            "notes": self.notes,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "user_email": self.user_email,
            "task_request_id": self.task_request_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "status": self.status,
        }

    @classmethod
    def from_task_request(cls, task_request: dict, user_email: str) -> "CalendarTask":
        """タスク依頼からカレンダータスクを生成

        Args:
            task_request: タスク依頼の情報
            user_email: タスクを割り当てるユーザーのメールアドレス

        Returns:
            CalendarTaskインスタンス
        """
        return cls(
            id=None,  # Google Tasks APIで自動生成される
            title=task_request.get("title", ""),
            notes=task_request.get("content", ""),
            due_date=task_request.get("due_date"),
            user_email=user_email,
            task_request_id=task_request.get("id", ""),
            created_at=datetime.now(),
        )