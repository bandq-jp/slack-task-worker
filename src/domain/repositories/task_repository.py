from abc import ABC, abstractmethod
from typing import Optional, List
from src.domain.entities.task import TaskRequest


class TaskRepositoryInterface(ABC):
    """タスクリポジトリのインターフェース"""

    @abstractmethod
    async def save(self, task: TaskRequest) -> TaskRequest:
        """タスクを保存"""
        pass

    @abstractmethod
    async def find_by_id(self, task_id: str) -> Optional[TaskRequest]:
        """IDでタスクを取得"""
        pass

    @abstractmethod
    async def find_by_assignee(self, assignee_slack_id: str) -> List[TaskRequest]:
        """担当者でタスクを検索"""
        pass

    @abstractmethod
    async def update(self, task: TaskRequest) -> TaskRequest:
        """タスクを更新"""
        pass