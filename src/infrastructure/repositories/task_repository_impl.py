from typing import Optional, List, Dict
from src.domain.entities.task import TaskRequest
from src.domain.repositories.task_repository import TaskRepositoryInterface


class InMemoryTaskRepository(TaskRepositoryInterface):
    """インメモリタスクリポジトリ実装"""

    def __init__(self):
        self._tasks: Dict[str, TaskRequest] = {}

    async def save(self, task: TaskRequest) -> TaskRequest:
        """タスクを保存"""
        self._tasks[task.id] = task
        return task

    async def find_by_id(self, task_id: str) -> Optional[TaskRequest]:
        """IDでタスクを取得"""
        return self._tasks.get(task_id)

    async def find_by_assignee(self, assignee_slack_id: str) -> List[TaskRequest]:
        """担当者でタスクを検索"""
        return [
            task
            for task in self._tasks.values()
            if task.assignee_slack_id == assignee_slack_id
        ]

    async def update(self, task: TaskRequest) -> TaskRequest:
        """タスクを更新"""
        if task.id in self._tasks:
            self._tasks[task.id] = task
            return task
        raise ValueError(f"Task not found: {task.id}")