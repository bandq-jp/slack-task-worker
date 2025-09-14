from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Union, Dict, Any
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
    description: Optional[Union[str, Dict[str, Any]]] = None
    due_date: datetime = field(default_factory=datetime.now)
    task_type: str = ""
    urgency: str = ""
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