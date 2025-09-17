from typing import Optional, Dict, Any
from datetime import datetime
from src.domain.entities.calendar_task import CalendarTask
from src.domain.repositories.calendar_task_repository import CalendarTaskRepository
from src.application.services.user_mapping_service import UserMappingApplicationService


class CalendarTaskApplicationService:
    """カレンダータスクのアプリケーションサービス

    タスク承認時のGoogleカレンダー連携を管理
    """

    def __init__(self,
                 calendar_task_repository: CalendarTaskRepository,
                 user_mapping_service: UserMappingApplicationService):
        """
        Args:
            calendar_task_repository: カレンダータスクリポジトリ
            user_mapping_service: ユーザーマッピングサービス
        """
        self.calendar_task_repository = calendar_task_repository
        self.user_mapping_service = user_mapping_service

    async def create_task_on_approval(self,
                                     task_data: Dict[str, Any],
                                     approver_slack_user_id: str) -> Optional[CalendarTask]:
        """タスク承認時にGoogleカレンダーにタスクを作成

        Args:
            task_data: Notionから取得したタスクデータ
            approver_slack_user_id: 承認者のSlack ユーザーID

        Returns:
            作成されたカレンダータスク
        """
        try:
            # 承認者のメールアドレスを取得
            approver_email = await self._get_user_email(approver_slack_user_id)
            if not approver_email:
                print(f"Could not find email for user {approver_slack_user_id}")
                return None

            # タスクエンティティを作成
            calendar_task = CalendarTask(
                id=None,
                title=task_data.get('title', 'タスク'),
                notes=self._format_task_notes(task_data),
                due_date=self._parse_due_date(task_data.get('due_date')),
                user_email=approver_email,
                task_request_id=task_data.get('id', ''),
                created_at=datetime.now()
            )

            # Googleカレンダーにタスクを作成
            created_task = await self.calendar_task_repository.create(calendar_task)

            print(f"✅ Calendar task created for {approver_email}")
            return created_task

        except Exception as e:
            print(f"Error creating calendar task: {e}")
            return None

    async def _get_user_email(self, slack_user_id: str) -> Optional[str]:
        """Slack ユーザーIDからメールアドレスを取得

        Args:
            slack_user_id: SlackユーザーID

        Returns:
            ユーザーのメールアドレス
        """
        try:
            # ユーザーマッピングサービスを使用してSlackユーザー情報を取得
            slack_user = await self.user_mapping_service.slack_user_repository.find_by_id(slack_user_id)

            if slack_user and slack_user.email:
                return slack_user.email.value

            return None

        except Exception as e:
            print(f"Error getting user email: {e}")
            return None

    def _format_task_notes(self, task_data: Dict[str, Any]) -> str:
        """タスクの詳細情報をフォーマット

        Args:
            task_data: タスクデータ

        Returns:
            フォーマットされた詳細テキスト
        """
        notes_parts = []

        # 依頼者情報
        if task_data.get('requester_name'):
            notes_parts.append(f"依頼者: {task_data['requester_name']}")

        # タスクの内容
        if task_data.get('content'):
            notes_parts.append(f"\n内容:\n{task_data['content']}")

        # Notion URL
        if task_data.get('notion_url'):
            notes_parts.append(f"\nNotion: {task_data['notion_url']}")

        # 承認日時
        notes_parts.append(f"\n承認日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

        return "\n".join(notes_parts)

    def _parse_due_date(self, due_date_str: Optional[str]) -> Optional[datetime]:
        """納期文字列をdatetimeに変換

        Args:
            due_date_str: 納期文字列（ISO形式または日本語形式）

        Returns:
            datetime オブジェクト
        """
        if not due_date_str:
            return None

        try:
            # ISO形式を試す
            if 'T' in due_date_str:
                return datetime.fromisoformat(due_date_str.replace('Z', '+00:00'))

            # 日付のみの形式を試す
            return datetime.strptime(due_date_str, '%Y-%m-%d')

        except (ValueError, AttributeError):
            # パースに失敗した場合はNoneを返す
            print(f"Could not parse due date: {due_date_str}")
            return None

    async def get_tasks_for_request(self, task_request_id: str) -> list:
        """タスク依頼に関連するカレンダータスクを取得

        Args:
            task_request_id: タスク依頼のID

        Returns:
            関連するカレンダータスクのリスト
        """
        try:
            tasks = await self.calendar_task_repository.find_by_task_request_id(task_request_id)
            return tasks
        except Exception as e:
            print(f"Error getting tasks for request: {e}")
            return []