from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from enum import Enum


class TaskStatusDto(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class CreateTaskRequestDto(BaseModel):
    """タスク作成リクエストDTO"""
    requester_slack_id: str = Field(..., description="依頼者のSlackユーザーID")
    assignee_slack_id: str = Field(..., description="依頼先のSlackユーザーID")
    title: str = Field(..., description="タスクタイトル")
    description: str = Field(..., description="タスク内容")
    due_date: datetime = Field(..., description="納期")


class TaskApprovalDto(BaseModel):
    """タスク承認/差し戻しDTO"""
    task_id: str = Field(..., description="タスクID")
    action: str = Field(..., description="承認(approve)または差し戻し(reject)")
    rejection_reason: Optional[str] = Field(None, description="差し戻し理由")


class TaskResponseDto(BaseModel):
    """タスクレスポンスDTO"""
    id: str
    requester_slack_id: str
    assignee_slack_id: str
    title: str
    description: str
    due_date: datetime
    status: TaskStatusDto
    rejection_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    notion_page_id: Optional[str] = None