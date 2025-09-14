from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum
import uuid


class TaskStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class TaskRequest:
    """タスク依頼エンティティ"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    requester_slack_id: str = ""
    assignee_slack_id: str = ""
    title: str = ""
    description: str = ""
    due_date: datetime = field(default_factory=datetime.now)
    status: TaskStatus = TaskStatus.PENDING
    rejection_reason: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    notion_page_id: Optional[str] = None

    def approve(self) -> None:
        """タスクを承認"""
        self.status = TaskStatus.APPROVED
        self.updated_at = datetime.now()

    def reject(self, reason: str) -> None:
        """タスクを差し戻し"""
        self.status = TaskStatus.REJECTED
        self.rejection_reason = reason
        self.updated_at = datetime.now()

    def is_pending(self) -> bool:
        """承認待ち状態かどうか"""
        return self.status == TaskStatus.PENDING