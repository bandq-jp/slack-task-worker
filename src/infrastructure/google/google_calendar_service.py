import os
import json
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


class GoogleCalendarService:
    """Google Calendar API統合サービス

    環境変数に基づいて認証方法を切り替え：
    - 本番環境（ENV=production）: SERVICE_ACCOUNT_JSONに直接JSON文字列を設定
    - ローカル環境: SERVICE_ACCOUNT_JSONにJSONファイルパスを設定
    """

    SCOPES = [
        'https://www.googleapis.com/auth/calendar',
        'https://www.googleapis.com/auth/tasks'
    ]

    def __init__(self, service_account_json: str, env: str = "local"):
        """
        Args:
            service_account_json: サービスアカウントのJSON文字列またはファイルパス
            env: 環境（production/local）
        """
        self.env = env
        self.credentials = self._get_credentials(service_account_json)
        self.calendar_service = build('calendar', 'v3', credentials=self.credentials)
        self.tasks_service = build('tasks', 'v1', credentials=self.credentials)

    def _get_credentials(self, service_account_json: str) -> service_account.Credentials:
        """環境に応じて認証情報を取得"""
        if self.env == "production":
            # 本番環境：環境変数から直接JSON文字列を読み込み
            try:
                service_account_info = json.loads(service_account_json)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid service account JSON: {e}")
        else:
            # ローカル環境：ファイルパスからJSONを読み込み
            if not os.path.exists(service_account_json):
                raise FileNotFoundError(f"Service account file not found: {service_account_json}")

            with open(service_account_json, 'r') as f:
                service_account_info = json.load(f)

        return service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=self.SCOPES
        )

    def create_task(self,
                   user_email: str,
                   title: str,
                   notes: str,
                   due_date: Optional[datetime] = None) -> Dict[str, Any]:
        """ユーザーのタスクリストにタスクを作成

        Args:
            user_email: タスクを追加するユーザーのメールアドレス
            title: タスクのタイトル
            notes: タスクの詳細説明
            due_date: 期限（オプション）

        Returns:
            作成されたタスクの情報
        """
        try:
            print(f"📅 Creating Google Calendar task for: {user_email}")
            print(f"   Title: {title}")
            print(f"   Due date: {due_date}")

            # ユーザーにタスクリストへのアクセス権を委譲
            delegated_credentials = self.credentials.with_subject(user_email)
            tasks_service = build('tasks', 'v1', credentials=delegated_credentials)

            # デフォルトタスクリストのIDを取得
            tasklist_id = '@default'

            # タスクのボディを構築
            task_body = {
                'title': title,
                'notes': notes,
            }

            if due_date:
                # RFC 3339形式に変換
                task_body['due'] = due_date.isoformat() + 'Z'

            print(f"📝 Task body: {task_body}")

            # タスクを作成
            task = tasks_service.tasks().insert(
                tasklist=tasklist_id,
                body=task_body
            ).execute()

            print(f"✅ Google Calendar task created successfully for {user_email}: {task.get('id')}")
            return task

        except HttpError as error:
            error_details = error.resp if hasattr(error, 'resp') else str(error)
            print(f"❌ Google Calendar API Error for {user_email}:")
            print(f"   Status: {error.resp.status if hasattr(error, 'resp') else 'Unknown'}")
            print(f"   Reason: {error.resp.reason if hasattr(error, 'resp') else 'Unknown'}")
            print(f"   Details: {error_details}")

            if hasattr(error, 'resp') and error.resp.status == 403:
                print("🔒 Permission denied. Please check:")
                print("   1. Domain-wide delegation is properly configured")
                print("   2. Service account has the correct scopes")
                print("   3. User email exists in Google Workspace")
                print("   4. User has Google Tasks enabled")

            raise Exception(f"Google Calendar API error: {error}")
        except Exception as error:
            print(f"❌ Unexpected error creating Google Calendar task for {user_email}: {error}")
            raise

    def create_calendar_event(self,
                            user_email: str,
                            summary: str,
                            description: str,
                            start_date: datetime,
                            end_date: Optional[datetime] = None,
                            attendees: Optional[List[str]] = None) -> Dict[str, Any]:
        """ユーザーのカレンダーにイベントを作成

        Args:
            user_email: イベントを作成するユーザーのメールアドレス
            summary: イベントのタイトル
            description: イベントの説明
            start_date: 開始日時
            end_date: 終了日時（指定なしの場合は開始から1時間後）
            attendees: 参加者のメールアドレスリスト

        Returns:
            作成されたイベントの情報
        """
        try:
            # ユーザーにカレンダーへのアクセス権を委譲
            delegated_credentials = self.credentials.with_subject(user_email)
            calendar_service = build('calendar', 'v3', credentials=delegated_credentials)

            # 終了日時が指定されていない場合は開始から1時間後に設定
            if not end_date:
                end_date = start_date + timedelta(hours=1)

            # イベントのボディを構築
            event = {
                'summary': summary,
                'description': description,
                'start': {
                    'dateTime': start_date.isoformat(),
                    'timeZone': 'Asia/Tokyo',
                },
                'end': {
                    'dateTime': end_date.isoformat(),
                    'timeZone': 'Asia/Tokyo',
                },
            }

            # 参加者を追加
            if attendees:
                event['attendees'] = [{'email': email} for email in attendees]

            # イベントを作成
            created_event = calendar_service.events().insert(
                calendarId='primary',
                body=event
            ).execute()

            print(f"✅ Calendar event created for {user_email}: {created_event.get('htmlLink')}")
            return created_event

        except HttpError as error:
            print(f"❌ Error creating calendar event for {user_email}: {error}")
            raise

    def get_user_tasks(self, user_email: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """ユーザーのタスクリストを取得

        Args:
            user_email: タスクを取得するユーザーのメールアドレス
            max_results: 取得する最大タスク数

        Returns:
            タスクのリスト
        """
        try:
            delegated_credentials = self.credentials.with_subject(user_email)
            tasks_service = build('tasks', 'v1', credentials=delegated_credentials)

            results = tasks_service.tasks().list(
                tasklist='@default',
                maxResults=max_results
            ).execute()

            tasks = results.get('items', [])
            return tasks

        except HttpError as error:
            print(f"❌ Error fetching tasks for {user_email}: {error}")
            return []