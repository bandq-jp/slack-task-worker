from typing import Optional, List, Dict, Any
from datetime import datetime
from src.domain.entities.calendar_task import CalendarTask
from src.domain.repositories.calendar_task_repository import CalendarTaskRepository
from src.infrastructure.google.google_calendar_service import GoogleCalendarService


class GoogleCalendarTaskRepository(CalendarTaskRepository):
    """Google Tasks APIを使用したカレンダータスクリポジトリの実装"""

    def __init__(self, google_calendar_service: GoogleCalendarService):
        """
        Args:
            google_calendar_service: Google Calendar APIサービス
        """
        self.google_service = google_calendar_service
        # インメモリキャッシュ（タスク依頼IDとの関連を保持）
        self._task_mapping: Dict[str, List[str]] = {}

    async def create(self, task: CalendarTask) -> CalendarTask:
        """Google Tasks APIでタスクを作成"""
        try:
            # Google Tasks APIでタスクを作成
            created_task = self.google_service.create_task(
                user_email=task.user_email,
                title=task.title,
                notes=task.notes,
                due_date=task.due_date
            )

            # 作成されたタスクのIDを設定
            task.id = created_task.get('id')

            # タスク依頼IDとのマッピングを保存
            if task.task_request_id not in self._task_mapping:
                self._task_mapping[task.task_request_id] = []
            self._task_mapping[task.task_request_id].append(task.id)

            return task

        except Exception as e:
            print(f"Error creating calendar task: {e}")
            raise

    async def find_by_id(self, task_id: str, user_email: str) -> Optional[CalendarTask]:
        """IDでタスクを検索"""
        try:
            # ユーザーのタスクリストから検索
            tasks = self.google_service.get_user_tasks(user_email, max_results=100)

            for task_data in tasks:
                if task_data.get('id') == task_id:
                    return self._convert_to_entity(task_data, user_email)

            return None

        except Exception as e:
            print(f"Error finding calendar task: {e}")
            return None

    async def find_by_task_request_id(self, task_request_id: str) -> List[CalendarTask]:
        """タスク依頼IDで関連するタスクを検索"""
        # インメモリマッピングから検索
        task_ids = self._task_mapping.get(task_request_id, [])
        tasks = []

        # 実際のタスク情報は取得しない（パフォーマンスのため）
        # 必要に応じてfind_by_idで個別に取得
        for task_id in task_ids:
            # 簡易的なタスクオブジェクトを返す
            tasks.append(CalendarTask(
                id=task_id,
                title="",
                notes="",
                due_date=None,
                user_email="",
                task_request_id=task_request_id,
                created_at=datetime.now()
            ))

        return tasks

    async def update(self, task: CalendarTask) -> CalendarTask:
        """タスクを更新（現在は未実装）"""
        # Google Tasks APIには更新エンドポイントがあるが、今回は実装を省略
        # 必要に応じて実装を追加
        print(f"Task update not implemented: {task.id}")
        return task

    async def delete(self, task_id: str, user_email: str) -> bool:
        """タスクを削除（現在は未実装）"""
        # Google Tasks APIには削除エンドポイントがあるが、今回は実装を省略
        # 必要に応じて実装を追加
        print(f"Task deletion not implemented: {task_id}")
        return False

    def _convert_to_entity(self, task_data: Dict[str, Any], user_email: str) -> CalendarTask:
        """Google Tasks APIのレスポンスをエンティティに変換"""
        due_date = None
        if task_data.get('due'):
            due_date = datetime.fromisoformat(task_data['due'].replace('Z', '+00:00'))

        return CalendarTask(
            id=task_data.get('id'),
            title=task_data.get('title', ''),
            notes=task_data.get('notes', ''),
            due_date=due_date,
            user_email=user_email,
            task_request_id='',  # マッピングから取得する必要がある
            created_at=datetime.now(),  # 実際の作成日時は取得できない
            status=task_data.get('status', 'needsAction')
        )