from abc import ABC, abstractmethod
from typing import Optional, List
from src.domain.entities.calendar_task import CalendarTask


class CalendarTaskRepository(ABC):
    """カレンダータスクリポジトリのインターフェース"""

    @abstractmethod
    async def create(self, task: CalendarTask) -> CalendarTask:
        """カレンダータスクを作成

        Args:
            task: 作成するタスク

        Returns:
            作成されたタスク（IDが設定される）
        """
        pass

    @abstractmethod
    async def find_by_id(self, task_id: str, user_email: str) -> Optional[CalendarTask]:
        """IDでタスクを検索

        Args:
            task_id: タスクID
            user_email: ユーザーのメールアドレス

        Returns:
            タスク（見つからない場合はNone）
        """
        pass

    @abstractmethod
    async def find_by_task_request_id(self, task_request_id: str) -> List[CalendarTask]:
        """タスク依頼IDで関連するタスクを検索

        Args:
            task_request_id: タスク依頼のID

        Returns:
            関連するタスクのリスト
        """
        pass

    @abstractmethod
    async def update(self, task: CalendarTask) -> CalendarTask:
        """タスクを更新

        Args:
            task: 更新するタスク

        Returns:
            更新されたタスク
        """
        pass

    @abstractmethod
    async def delete(self, task_id: str, user_email: str) -> bool:
        """タスクを削除

        Args:
            task_id: タスクID
            user_email: ユーザーのメールアドレス

        Returns:
            削除成功の場合True
        """
        pass