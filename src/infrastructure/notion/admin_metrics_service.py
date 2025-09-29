from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Any, Iterable, List, Optional

from notion_client import Client

from src.domain.entities.task_metrics import AssigneeMetricsSummary, TaskMetricsRecord


METRICS_PROP_TASK_ID = "タスクID"
METRICS_PROP_TASK_TITLE = "タスク名"
METRICS_PROP_ASSIGNEE = "担当者"
METRICS_PROP_ASSIGNEE_EMAIL = "担当者メール"
METRICS_PROP_DUE = "納期"
METRICS_PROP_STATUS = "ステータス"
METRICS_PROP_COMPLETION_STATUS = "完了ステータス"
METRICS_PROP_EXTENSION_STATUS = "延期ステータス"
METRICS_PROP_REMINDER_STAGE = "リマインドフェーズ"
METRICS_PROP_OVERDUE_POINTS = "納期超過ポイント"
METRICS_PROP_LAST_SYNCED = "最終更新"

SUMMARY_PROP_ASSIGNEE = "担当者"
SUMMARY_PROP_ASSIGNEE_EMAIL = "担当者メール"
SUMMARY_PROP_TOTAL_TASKS = "担当タスク数"
SUMMARY_PROP_OPEN_TASKS = "未完了タスク数"
SUMMARY_PROP_COMPLETED_TASKS = "完了タスク数"
SUMMARY_PROP_OVERDUE_TASKS = "期限超過タスク数"
SUMMARY_PROP_DUE_SOON_TASKS = "近日納期タスク数"
SUMMARY_PROP_NEXT_DUE = "最短納期"
SUMMARY_PROP_TOTAL_OVERDUE_POINTS = "納期超過ポイント累計"
SUMMARY_PROP_LAST_UPDATED = "最終更新"


class AdminMetricsNotionService:
    """管理者向けのタスクメトリクスデータベースを扱うサービス"""

    def __init__(
        self,
        notion_token: str,
        metrics_database_id: Optional[str],
        summary_database_id: Optional[str] = None,
    ) -> None:
        self.client = Client(auth=notion_token)
        self.metrics_database_id = (
            self._normalize_database_id(metrics_database_id)
            if metrics_database_id
            else None
        )
        self.summary_database_id = (
            self._normalize_database_id(summary_database_id)
            if summary_database_id
            else None
        )
        self._summary_title_prop_name: Optional[str] = None

    @staticmethod
    def _normalize_database_id(database_id: str) -> str:
        return database_id.replace("-", "")

    async def fetch_all_metrics(self) -> List[TaskMetricsRecord]:
        if not self.metrics_database_id:
            print("⚠️ Metrics database ID is not configured; skipping fetch.")
            return []

        results: List[TaskMetricsRecord] = []
        has_more = True
        start_cursor: Optional[str] = None

        while has_more:
            payload: Dict[str, Any] = {
                "database_id": self.metrics_database_id,
                "page_size": 100,
            }
            if start_cursor:
                payload["start_cursor"] = start_cursor

            response = self.client.databases.query(**payload)
            for page in response.get("results", []):
                record = self._to_metrics_record(page)
                if record:
                    results.append(record)

            has_more = response.get("has_more", False)
            start_cursor = response.get("next_cursor")

        print(f"📊 Metrics loaded from Notion: {len(results)} 件")
        return results

    async def get_metrics_by_task_id(self, task_page_id: str) -> Optional[TaskMetricsRecord]:
        if not self.metrics_database_id:
            return None

        response = self.client.databases.query(
            database_id=self.metrics_database_id,
            page_size=1,
            filter={
                "property": METRICS_PROP_TASK_ID,
                "rich_text": {"equals": task_page_id},
            },
        )
        results = response.get("results", [])
        if not results:
            return None
        return self._to_metrics_record(results[0])

    async def upsert_task_metrics(self, record: TaskMetricsRecord) -> TaskMetricsRecord:
        if not self.metrics_database_id:
            return record

        existing = await self.get_metrics_by_task_id(record.task_page_id)
        properties = self._build_task_metrics_properties(record)

        if existing and existing.metrics_page_id:
            self.client.pages.update(page_id=existing.metrics_page_id, properties=properties)
            record.metrics_page_id = existing.metrics_page_id
        else:
            created = self.client.pages.create(
                parent={"database_id": self.metrics_database_id},
                properties=properties,
            )
            record.metrics_page_id = created.get("id")

        return record

    async def update_overdue_points(self, task_page_id: str, points: int) -> Optional[TaskMetricsRecord]:
        if not self.metrics_database_id:
            return None

        record = await self.get_metrics_by_task_id(task_page_id)
        if not record or not record.metrics_page_id:
            return None

        points_value = max(points, 0)
        self.client.pages.update(
            page_id=record.metrics_page_id,
            properties={
                METRICS_PROP_OVERDUE_POINTS: {"number": points_value},
                METRICS_PROP_LAST_SYNCED: {
                    "date": {"start": self._format_datetime(datetime.now(timezone.utc))}
                },
            },
        )
        record.overdue_points = points_value
        record.last_synced_at = datetime.now(timezone.utc)
        return record

    async def update_reminder_stage(
        self,
        task_page_id: str,
        stage: Optional[str],
        synced_at: datetime,
    ) -> Optional[TaskMetricsRecord]:
        if not self.metrics_database_id:
            return None

        record = await self.get_metrics_by_task_id(task_page_id)
        if not record or not record.metrics_page_id:
            return None

        properties: Dict[str, Any] = {
            METRICS_PROP_LAST_SYNCED: {
                "date": {"start": self._format_datetime(synced_at)},
            }
        }
        if stage is not None:
            properties[METRICS_PROP_REMINDER_STAGE] = {"select": {"name": stage}}

        self.client.pages.update(page_id=record.metrics_page_id, properties=properties)
        record.reminder_stage = stage
        record.last_synced_at = synced_at
        return record

    async def upsert_assignee_summaries(
        self,
        summaries: Iterable[AssigneeMetricsSummary],
    ) -> None:
        summary_items = list(summaries)

        if not self.summary_database_id:
            if summary_items:
                print("⚠️ Summary database ID is not configured; skipping summary sync.")
            return

        print(f"🧮 Building assignee summaries: {len(summary_items)} 件")
        for summary in summary_items:
            existing = self._find_summary_by_email(summary.assignee_email)
            if not existing and summary.assignee_notion_id:
                existing = self._find_summary_by_person(summary.assignee_notion_id)
            properties = self._build_summary_properties(summary)

            if existing and existing.get("id"):
                try:
                    page_id = existing["id"]
                    self.client.pages.update(page_id=page_id, properties=properties)
                    print(
                        f"🔁 Updated summary for: {summary.assignee_email or summary.assignee_notion_id or '(unassigned)'}"
                        f" | page_id: {page_id}"
                    )
                except Exception as e:
                    print(f"❌ Failed to update summary: {e}")
            else:
                try:
                    created = self.client.pages.create(
                        parent={"database_id": self.summary_database_id},
                        properties=properties,
                    )
                    page_id = created.get("id")
                    print(
                        f"✅ Created summary for: {summary.assignee_email or summary.assignee_notion_id or '(unassigned)'}"
                        f" | page_id: {page_id}"
                    )
                except Exception as e:
                    print(f"❌ Failed to create summary: {e}")
                    # タイトル未設定等の可能性があるため、タイトルプロパティ名を推定して再試行
                    try:
                        title_prop = self._get_summary_title_prop_name()
                        if title_prop and title_prop not in properties:
                            title_content = (
                                summary.assignee_name
                                or summary.assignee_email
                                or "(unassigned)"
                            )
                            properties[title_prop] = {
                                "title": [
                                    {
                                        "type": "text",
                                        "text": {"content": title_content[:1000]},
                                    }
                                ]
                            }
                            created2 = self.client.pages.create(
                                parent={"database_id": self.summary_database_id},
                                properties=properties,
                            )
                            print(
                                f"✅ Retried and created summary with title for: {summary.assignee_email or summary.assignee_notion_id or '(unassigned)'}"
                                f" | page_id: {created2.get('id')}"
                            )
                    except Exception as retry_error:
                        print(f"❌ Retry failed to create summary: {retry_error}")

    def _find_summary_by_email(self, assignee_email: Optional[str]) -> Optional[Dict[str, Any]]:
        if not self.summary_database_id or not assignee_email:
            return None

        response = self.client.databases.query(
            database_id=self.summary_database_id,
            page_size=1,
            filter={
                "property": SUMMARY_PROP_ASSIGNEE_EMAIL,
                "rich_text": {"equals": assignee_email},
            },
        )
        results = response.get("results", [])
        return results[0] if results else None

    def _find_summary_by_person(self, notion_user_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not self.summary_database_id or not notion_user_id:
            return None
        try:
            response = self.client.databases.query(
                database_id=self.summary_database_id,
                page_size=1,
                filter={
                    "property": SUMMARY_PROP_ASSIGNEE,
                    "people": {"contains": notion_user_id},
                },
            )
            results = response.get("results", [])
            return results[0] if results else None
        except Exception as e:
            print(f"⚠️ Failed to find summary by person: {e}")
            return None

    def _build_task_metrics_properties(self, record: TaskMetricsRecord) -> Dict[str, Any]:
        title_content = record.task_title or "(untitled)"

        properties: Dict[str, Any] = {
            METRICS_PROP_TASK_TITLE: {
                "title": [
                    {
                        "type": "text",
                        "text": {"content": title_content[:1000]},
                    }
                ]
            },
            METRICS_PROP_TASK_ID: {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": record.task_page_id},
                    }
                ]
            },
            METRICS_PROP_OVERDUE_POINTS: {"number": max(record.overdue_points, 0)},
            METRICS_PROP_LAST_SYNCED: {
                "date": {"start": self._format_datetime(record.last_synced_at)},
            },
        }

        if record.assignee_notion_id:
            properties[METRICS_PROP_ASSIGNEE] = {
                "people": [{"object": "user", "id": record.assignee_notion_id}]
            }
        elif record.assignee_email:
            # Fallback: store as text if People プロパティに設定できない場合
            properties[METRICS_PROP_ASSIGNEE] = {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": record.assignee_email},
                    }
                ]
            }

        if record.assignee_email:
            properties[METRICS_PROP_ASSIGNEE_EMAIL] = {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": record.assignee_email},
                    }
                ]
            }

        if record.due_date:
            properties[METRICS_PROP_DUE] = {
                "date": {"start": self._format_datetime(record.due_date)}
            }
        else:
            properties[METRICS_PROP_DUE] = {"date": None}

        if record.status:
            properties[METRICS_PROP_STATUS] = {"select": {"name": record.status}}
        if record.completion_status:
            properties[METRICS_PROP_COMPLETION_STATUS] = {
                "select": {"name": record.completion_status}
            }
        if record.extension_status:
            properties[METRICS_PROP_EXTENSION_STATUS] = {
                "select": {"name": record.extension_status}
            }
        if record.reminder_stage:
            properties[METRICS_PROP_REMINDER_STAGE] = {
                "select": {"name": record.reminder_stage}
            }

        return properties

    def _build_summary_properties(self, summary: AssigneeMetricsSummary) -> Dict[str, Any]:
        properties: Dict[str, Any] = {
            SUMMARY_PROP_TOTAL_TASKS: {"number": summary.total_tasks},
            SUMMARY_PROP_OPEN_TASKS: {"number": summary.open_tasks},
            SUMMARY_PROP_COMPLETED_TASKS: {"number": summary.completed_tasks},
            SUMMARY_PROP_OVERDUE_TASKS: {"number": summary.overdue_tasks},
            SUMMARY_PROP_DUE_SOON_TASKS: {"number": summary.due_within_three_days},
            SUMMARY_PROP_TOTAL_OVERDUE_POINTS: {
                "number": max(summary.total_overdue_points, 0)
            },
            SUMMARY_PROP_LAST_UPDATED: {
                "date": {"start": self._format_datetime(summary.last_calculated_at)}
            },
        }

        # タイトルプロパティ（存在すれば設定）
        title_prop = self._get_summary_title_prop_name()
        if title_prop:
            title_content = summary.assignee_name or summary.assignee_email or "(unassigned)"
            properties[title_prop] = {
                "title": [
                    {"type": "text", "text": {"content": title_content[:1000]}}
                ]
            }

        if summary.assignee_notion_id:
            properties[SUMMARY_PROP_ASSIGNEE] = {
                "people": [{"object": "user", "id": summary.assignee_notion_id}]
            }
        elif summary.assignee_name:
            properties[SUMMARY_PROP_ASSIGNEE] = {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": summary.assignee_name},
                    }
                ]
            }

        if summary.assignee_email:
            properties[SUMMARY_PROP_ASSIGNEE_EMAIL] = {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": summary.assignee_email},
                    }
                ]
            }

        if summary.next_due_date:
            properties[SUMMARY_PROP_NEXT_DUE] = {
                "date": {"start": self._format_datetime(summary.next_due_date)}
            }
        else:
            properties[SUMMARY_PROP_NEXT_DUE] = {"date": None}

        return properties

    def _get_summary_title_prop_name(self) -> Optional[str]:
        """Summary DBのタイトルプロパティ名を取得（キャッシュ）"""
        if not self.summary_database_id:
            return None
        if self._summary_title_prop_name is not None:
            return self._summary_title_prop_name
        try:
            db = self.client.databases.retrieve(database_id=self.summary_database_id)
            props = db.get("properties", {})
            for name, meta in props.items():
                if meta.get("type") == "title":
                    self._summary_title_prop_name = name
                    return name
        except Exception as e:
            print(f"⚠️ Could not retrieve summary DB schema: {e}")
        # キャッシュにNoneを記録して以後スキップ
        self._summary_title_prop_name = None
        return None

    def _to_metrics_record(self, page: Dict[str, Any]) -> Optional[TaskMetricsRecord]:
        properties = page.get("properties", {})

        task_title = self._extract_title(properties.get(METRICS_PROP_TASK_TITLE))
        task_page_id = self._extract_text(properties.get(METRICS_PROP_TASK_ID))
        if not task_page_id:
            return None

        assignee_id, assignee_email, assignee_name = self._extract_people(properties.get(METRICS_PROP_ASSIGNEE))
        if not assignee_email:
            alt_email = self._extract_text(properties.get(METRICS_PROP_ASSIGNEE_EMAIL))
            assignee_email = alt_email or assignee_email

        due_date = self._parse_datetime(properties.get(METRICS_PROP_DUE, {}).get("date"))
        status = self._extract_select(properties.get(METRICS_PROP_STATUS))
        completion_status = self._extract_select(properties.get(METRICS_PROP_COMPLETION_STATUS))
        extension_status = self._extract_select(properties.get(METRICS_PROP_EXTENSION_STATUS))
        reminder_stage = self._extract_select(properties.get(METRICS_PROP_REMINDER_STAGE))
        overdue_points = self._extract_number(properties.get(METRICS_PROP_OVERDUE_POINTS))
        last_synced_at = self._parse_datetime(properties.get(METRICS_PROP_LAST_SYNCED, {}).get("date"))

        record = TaskMetricsRecord(
            task_page_id=task_page_id,
            task_title=task_title or "",
            assignee_email=assignee_email,
            assignee_notion_id=assignee_id,
            assignee_name=assignee_name,
            due_date=due_date,
            status=status,
            reminder_stage=reminder_stage,
            overdue_points=overdue_points,
            completion_status=completion_status,
            extension_status=extension_status,
            metrics_page_id=page.get("id"),
        )
        if last_synced_at:
            record.last_synced_at = last_synced_at
        return record

    @staticmethod
    def _extract_title(prop: Optional[Dict[str, Any]]) -> Optional[str]:
        if not prop:
            return None
        title_items = prop.get("title", [])
        for item in title_items:
            text = item.get("plain_text") or item.get("text", {}).get("content")
            if text:
                return text
        return None

    @staticmethod
    def _extract_text(prop: Optional[Dict[str, Any]]) -> Optional[str]:
        if not prop:
            return None
        rich_text = prop.get("rich_text", [])
        for item in rich_text:
            text = item.get("plain_text") or item.get("text", {}).get("content")
            if text:
                return text
        return None

    @staticmethod
    def _extract_number(prop: Optional[Dict[str, Any]]) -> int:
        if not prop:
            return 0
        value = prop.get("number")
        return int(value) if value is not None else 0

    @staticmethod
    def _extract_select(prop: Optional[Dict[str, Any]]) -> Optional[str]:
        if not prop:
            return None
        select = prop.get("select")
        if not select:
            return None
        return select.get("name")

    @staticmethod
    def _extract_people(prop: Optional[Dict[str, Any]]) -> tuple[Optional[str], Optional[str], Optional[str]]:
        if not prop:
            return None, None, None

        people = prop.get("people")
        if isinstance(people, list) and people:
            person = people[0]
            notion_id = person.get("id")
            name = person.get("name") or person.get("plain_text")
            email = person.get("person", {}).get("email") or person.get("person", {}).get("email_address")
            return notion_id, email, name

        return None, None, None

    @staticmethod
    def _parse_datetime(date_payload: Optional[Dict[str, Any]]) -> Optional[datetime]:
        if not date_payload:
            return None
        start = date_payload.get("start")
        if not start:
            return None
        try:
            normalized = start.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None

    @staticmethod
    def _format_datetime(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
