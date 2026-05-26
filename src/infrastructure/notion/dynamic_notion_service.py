import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional, Dict, Any, List, Union
from notion_client import Client
from src.domain.entities.task import TaskRequest
from src.domain.entities.notion_user import NotionUser
from src.application.services.user_mapping_service import UserMappingApplicationService
from src.utils.text_converter import convert_rich_text_to_plain_text


REMINDER_STAGE_NOT_SENT = "未送信"
REMINDER_STAGE_BEFORE = "期日前"
REMINDER_STAGE_DUE = "当日"
REMINDER_STAGE_OVERDUE = "超過"
REMINDER_STAGE_ACKED = "既読"
REMINDER_STAGE_PENDING_APPROVAL = "未承認"

EXTENSION_STATUS_NONE = "なし"
EXTENSION_STATUS_PENDING = "申請中"
EXTENSION_STATUS_APPROVED = "承認済"
EXTENSION_STATUS_REJECTED = "却下"

COMPLETION_STATUS_IN_PROGRESS = "進行中"
COMPLETION_STATUS_REQUESTED = "完了申請中"
COMPLETION_STATUS_APPROVED = "完了承認"
COMPLETION_STATUS_REJECTED = "完了却下"

TASK_STATUS_PENDING = "承認待ち"
TASK_STATUS_APPROVED = "承認済み"
TASK_STATUS_REJECTED = "差し戻し"
TASK_STATUS_COMPLETED = "完了"
TASK_STATUS_DISABLED = "無効"

EXCLUDED_STATUSES_FOR_REMINDER = {
    TASK_STATUS_REJECTED,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_DISABLED,
}

TASK_PROP_TITLE = "タイトル"
TASK_PROP_DUE = "納期"
TASK_PROP_STATUS = "ステータス"
TASK_PROP_REQUESTER = "依頼者"
TASK_PROP_ASSIGNEE = "依頼先"
TASK_PROP_REMINDER_STAGE = "リマインドフェーズ"
TASK_PROP_REMINDER_READ = "リマインド既読"
TASK_PROP_LAST_REMIND_AT = "最終リマインド日時"
TASK_PROP_LAST_READ_AT = "最終既読日時"
TASK_PROP_DUE_READ = "当日既読"
TASK_PROP_OVERDUE_READ = "超過既読"
TASK_PROP_EXTENSION_STATUS = "延期ステータス"
TASK_PROP_EXTENSION_DUE = "延期期日（申請中）"
TASK_PROP_EXTENSION_REASON = "延期理由（申請中）"

TASK_PROP_COMPLETION_STATUS = "完了ステータス"
TASK_PROP_COMPLETION_REQUESTED_AT = "完了申請日時"
TASK_PROP_COMPLETION_APPROVED_AT = "完了承認日時"
TASK_PROP_COMPLETION_NOTE = "完了報告メモ"
TASK_PROP_COMPLETION_REJECT_REASON = "完了却下理由"

TASK_PROP_APPROVAL_REMINDER_AT = "承認リマインド最終送信日時"
TASK_PROP_EXTENSION_REQUESTED_AT = "延期申請日時"
TASK_PROP_TASK_APPROVAL_REQUESTED_AT = "タスク承認開始日時"

# Slackスレッド管理用プロパティ
TASK_PROP_ASSIGNEE_THREAD_TS = "依頼先スレッドTS"
TASK_PROP_ASSIGNEE_THREAD_CHANNEL = "依頼先スレッドチャンネル"
TASK_PROP_REQUESTER_THREAD_TS = "依頼者スレッドTS"
TASK_PROP_REQUESTER_THREAD_CHANNEL = "依頼者スレッドチャンネル"

AUDIT_PROP_TITLE = "イベント"
AUDIT_PROP_EVENT_TYPE = "種別"
AUDIT_PROP_TASK_RELATION = "関連タスク"
AUDIT_PROP_DETAIL = "詳細"
AUDIT_PROP_ACTOR = "実施者"
AUDIT_PROP_OCCURRED_AT = "日時"


@dataclass
class NotionTaskSnapshot:
    page_id: str
    title: str
    due_date: Optional[datetime]
    status: Optional[str]
    requester_email: Optional[str]
    requester_notion_id: Optional[str]
    assignee_email: Optional[str]
    assignee_notion_id: Optional[str]
    reminder_stage: Optional[str]
    reminder_last_sent_at: Optional[datetime]
    reminder_read: bool
    reminder_read_at: Optional[datetime]
    due_stage_read: bool
    overdue_stage_read: bool
    has_due_read_prop: bool
    has_overdue_read_prop: bool
    extension_status: Optional[str]
    extension_requested_due: Optional[datetime]
    extension_reason: Optional[str]
    completion_status: Optional[str]
    completion_requested_at: Optional[datetime]
    completion_note: Optional[str]
    completion_approved_at: Optional[datetime]
    completion_reject_reason: Optional[str]
    created_time: Optional[datetime]
    approval_reminder_last_sent_at: Optional[datetime]
    extension_requested_at: Optional[datetime]
    task_approval_requested_at: Optional[datetime]
    # Slackスレッド管理用
    assignee_thread_ts: Optional[str]
    assignee_thread_channel: Optional[str]
    requester_thread_ts: Optional[str]
    requester_thread_channel: Optional[str]


class DynamicNotionService:
    """動的ユーザー検索対応のNotion APIサービス（DDD版）"""

    def __init__(
        self,
        notion_token: str,
        database_id: str,
        user_mapping_service: UserMappingApplicationService,
        audit_database_id: Optional[str] = None,
    ):
        self.client = Client(auth=notion_token)
        self.database_id = self._normalize_database_id(database_id)
        self.user_mapping_service = user_mapping_service
        self.audit_database_id = (
            self._normalize_database_id(audit_database_id)
            if audit_database_id
            else None
        )

    def _normalize_database_id(self, database_id: str) -> str:
        """データベースIDを正規化（ハイフンを削除）"""
        return database_id.replace("-", "")

    def _is_in_trash(self, obj: Dict[str, Any]) -> bool:
        """Return whether a Notion object is trashed across old/new API fields."""
        if "in_trash" in obj:
            return bool(obj.get("in_trash"))
        return bool(obj.get("archived"))

    def _notion_object_name(self, obj: Dict[str, Any]) -> str:
        object_type = obj.get("object")

        if object_type == "database":
            return "".join(item.get("plain_text", "") for item in obj.get("title", []))

        if object_type == "page":
            for prop in obj.get("properties", {}).values():
                if prop.get("type") == "title":
                    return "".join(item.get("plain_text", "") for item in prop.get("title", []))

        if object_type == "block":
            block_type = obj.get("type")
            block_payload = obj.get(block_type, {}) if block_type else {}
            title = block_payload.get("title")
            if title:
                return title
            rich_text = block_payload.get("rich_text")
            if rich_text:
                return "".join(item.get("plain_text", "") for item in rich_text)
            return block_type or "block"

        return object_type or "unknown"

    def _assert_not_in_trash(self, obj: Dict[str, Any], context: str) -> None:
        if not self._is_in_trash(obj):
            return

        object_id = obj.get("id", "unknown")
        object_type = obj.get("object", "object")
        object_name = self._notion_object_name(obj) or "(no title)"
        raise ValueError(
            f"Notion {object_type} is in trash: {object_name} ({object_id}). "
            f"Restore it before {context}."
        )

    def _assert_parent_chain_not_in_trash(self, parent: Optional[Dict[str, Any]], context: str) -> None:
        seen: set[str] = set()

        while parent:
            parent_type = parent.get("type")
            object_id = (
                parent.get("database_id")
                or parent.get("page_id")
                or parent.get("block_id")
            )

            if not object_id or object_id in seen:
                return

            seen.add(object_id)

            try:
                if parent_type == "database_id":
                    obj = self.client.databases.retrieve(database_id=object_id)
                elif parent_type == "page_id":
                    obj = self.client.pages.retrieve(page_id=object_id)
                elif parent_type == "block_id":
                    obj = self.client.blocks.retrieve(block_id=object_id)
                else:
                    return
            except Exception as exc:
                print(f"⚠️ Failed to verify Notion ancestor {object_id}: {exc}")
                return

            self._assert_not_in_trash(obj, context)
            parent = obj.get("parent")

    def _ensure_database_editable(self) -> None:
        database = self.client.databases.retrieve(database_id=self.database_id)
        self._assert_not_in_trash(database, "creating tasks")
        self._assert_parent_chain_not_in_trash(database.get("parent"), "creating tasks")

    def _ensure_page_editable(self, page_id: str, context: str) -> None:
        page = self.client.pages.retrieve(page_id=page_id)
        self._assert_not_in_trash(page, context)
        self._assert_parent_chain_not_in_trash(page.get("parent"), context)

    def _parse_datetime(self, date_payload: Optional[Dict[str, Any]]) -> Optional[datetime]:
        if not date_payload:
            return None
        start = date_payload.get("start")
        if not start:
            return None
        try:
            normalized = start.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None

    def _parse_datetime_string(self, datetime_str: Optional[str]) -> Optional[datetime]:
        """文字列形式の日時をパースする（created_time等のシステムプロパティ用）"""
        if not datetime_str:
            return None
        try:
            normalized = datetime_str.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized)
        except (ValueError, AttributeError):
            return None

    def _format_datetime(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()

    def _extract_rich_text(self, prop: Optional[Dict[str, Any]]) -> Optional[str]:
        if not prop:
            return None
        rich_text_items = prop.get("rich_text", [])
        if not rich_text_items:
            return None
        texts: List[str] = []
        for item in rich_text_items:
            text = item.get("plain_text") or item.get("text", {}).get("content")
            if text:
                texts.append(text)
        return "".join(texts) if texts else None

    def _extract_people(self, prop: Optional[Dict[str, Any]]) -> tuple[Optional[str], Optional[str]]:
        """Return first person's (notion_user_id, email)"""
        if not prop:
            return None, None
        people = prop.get("people", [])
        if not people:
            return None, None
        first = people[0]
        notion_id = first.get("id")
        email = first.get("person", {}).get("email") or first.get("person", {}).get("email_address")
        return notion_id, email

    def _convert_slack_rich_text_to_notion(self, description: Union[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """SlackリッチテキストをNotionブロック形式に変換"""
        if isinstance(description, str):
            # プレーンテキストの場合、マークダウンパースを実行
            return self._parse_markdown_to_notion_blocks(description)

        # Slackリッチテキスト形式の場合
        blocks = []

        try:
            if isinstance(description, dict) and "elements" in description:
                # まず全テキストを抽出してマークダウンかどうか判定
                all_text = self._extract_text_from_slack_rich_text(description)

                # マークダウン形式の場合はマークダウンパーサーを使用
                if self._is_markdown_text(all_text):
                    return self._parse_markdown_to_notion_blocks(all_text)

                for element in description["elements"]:
                    if element.get("type") == "rich_text_section":
                        rich_text_items = []

                        for item in element.get("elements", []):
                            if item.get("type") == "text":
                                text_item = {
                                    "type": "text",
                                    "text": {"content": item.get("text", "")}
                                }

                                # スタイル適用
                                if "style" in item:
                                    annotations = {}
                                    style = item["style"]
                                    if style.get("bold"):
                                        annotations["bold"] = True
                                    if style.get("italic"):
                                        annotations["italic"] = True
                                    if style.get("strike"):
                                        annotations["strikethrough"] = True
                                    if style.get("code"):
                                        annotations["code"] = True

                                    if annotations:
                                        text_item["annotations"] = annotations

                                rich_text_items.append(text_item)

                            elif item.get("type") == "link":
                                rich_text_items.append({
                                    "type": "text",
                                    "text": {"content": item.get("text", item.get("url", ""))},
                                    "text": {"link": {"url": item.get("url", "")}}
                                })

                        if rich_text_items:
                            blocks.append({
                                "object": "block",
                                "type": "paragraph",
                                "paragraph": {"rich_text": rich_text_items}
                            })

                    elif element.get("type") == "rich_text_list":
                        # リストの処理
                        list_items = []
                        for list_item in element.get("elements", []):
                            if list_item.get("type") == "rich_text_section":
                                rich_text_items = []
                                for item in list_item.get("elements", []):
                                    if item.get("type") == "text":
                                        rich_text_items.append({
                                            "type": "text",
                                            "text": {"content": item.get("text", "")}
                                        })

                                if rich_text_items:
                                    list_items.append({
                                        "object": "block",
                                        "type": "bulleted_list_item",
                                        "bulleted_list_item": {"rich_text": rich_text_items}
                                    })

                        blocks.extend(list_items)

            if not blocks:
                # フォールバック: プレーンテキストとして処理
                blocks = [
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"type": "text", "text": {"content": str(description)}}]
                        }
                    }
                ]

        except Exception as e:
            print(f"Error converting rich text: {e}")
            # エラー時はプレーンテキストとして処理
            blocks = [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": str(description)}}]
                    }
                }
            ]

        return blocks

    def _parse_markdown_to_notion_blocks(self, markdown_text: str) -> List[Dict[str, Any]]:
        """マークダウンテキストをNotionブロック形式に変換"""
        blocks = []
        lines = markdown_text.split('\n')

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # 空行をスキップ
            if not line:
                i += 1
                continue

            # 見出し2の処理 (## で始まる)
            if line.startswith('## '):
                heading_text = line[3:].strip()
                blocks.append({
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [{"type": "text", "text": {"content": heading_text}}]
                    }
                })
                i += 1
                continue

            # 見出し1の処理 (# で始まる)
            elif line.startswith('# '):
                heading_text = line[2:].strip()
                blocks.append({
                    "object": "block",
                    "type": "heading_1",
                    "heading_1": {
                        "rich_text": [{"type": "text", "text": {"content": heading_text}}]
                    }
                })
                i += 1
                continue

            # 番号付きリストの処理 (数字. で始まる)
            elif line and len(line) > 2 and line[0].isdigit() and line[1:3].startswith('. '):
                list_text = line[line.find('. ') + 2:].strip()
                blocks.append({
                    "object": "block",
                    "type": "numbered_list_item",
                    "numbered_list_item": {
                        "rich_text": [{"type": "text", "text": {"content": list_text}}]
                    }
                })
                i += 1
                continue

            # 箇条書きリストの処理 (- で始まる)
            elif line.startswith('- '):
                list_text = line[2:].strip()
                blocks.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [{"type": "text", "text": {"content": list_text}}]
                    }
                })
                i += 1
                continue

            # 通常の段落の処理
            else:
                # 連続する段落行を収集
                paragraph_lines = [line]
                i += 1
                while i < len(lines) and lines[i].strip() and not self._is_markdown_special_line(lines[i].strip()):
                    paragraph_lines.append(lines[i].strip())
                    i += 1

                paragraph_text = ' '.join(paragraph_lines)
                if paragraph_text:
                    blocks.append({
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"type": "text", "text": {"content": paragraph_text}}]
                        }
                    })

        return blocks

    def _is_markdown_special_line(self, line: str) -> bool:
        """マークダウンの特殊行（見出し、リストなど）かどうかを判定"""
        if not line:
            return False

        # 見出し
        if line.startswith('# ') or line.startswith('## '):
            return True

        # 番号付きリスト
        if len(line) > 2 and line[0].isdigit() and line[1:3].startswith('. '):
            return True

        # 箇条書きリスト
        if line.startswith('- '):
            return True

        return False

    def _extract_text_from_slack_rich_text(self, slack_rich_text: Dict[str, Any]) -> str:
        """Slackリッチテキストからプレーンテキストを抽出"""
        text_parts = []

        try:
            if isinstance(slack_rich_text, dict) and "elements" in slack_rich_text:
                for element in slack_rich_text["elements"]:
                    if element.get("type") == "rich_text_section":
                        for item in element.get("elements", []):
                            if item.get("type") == "text":
                                text_parts.append(item.get("text", ""))
                            elif item.get("type") == "link":
                                text_parts.append(item.get("url", ""))
        except Exception:
            pass

        return "".join(text_parts)

    def _is_markdown_text(self, text: str) -> bool:
        """テキストがマークダウン形式かどうかを判定"""
        if not text:
            return False

        # マークダウンの特徴的なパターンをチェック
        lines = text.split('\n')
        markdown_patterns = 0

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 見出し
            if line.startswith('## ') or line.startswith('# '):
                markdown_patterns += 1

            # 番号付きリスト
            if len(line) > 2 and line[0].isdigit() and line[1:3].startswith('. '):
                markdown_patterns += 1

            # 箇条書きリスト
            if line.startswith('- '):
                markdown_patterns += 1

        # マークダウンパターンが2つ以上あればマークダウンテキストと判定
        return markdown_patterns >= 2

    async def create_task(
        self,
        task: TaskRequest,
        requester_email: str,
        assignee_email: str,
    ) -> str:
        """Notionデータベースにタスクを作成（動的ユーザー検索版）"""
        try:
            print(f"🏗️ Creating Notion task (Dynamic version):")
            print(f"   title: {task.title}")
            print(f"   task_type: '{task.task_type}'")
            print(f"   urgency: '{task.urgency}'")

            self._ensure_database_editable()

            # 新しいアプリケーションサービスでユーザー検索
            requester_user, assignee_user = await self.user_mapping_service.get_notion_user_for_task_creation(
                requester_email, 
                assignee_email
            )

            # 現在日時（タスク承認開始日時として使用）
            now = datetime.now(timezone.utc)

            # Notionページのプロパティを構築（詳細はページ本文に記載）
            properties = {
                TASK_PROP_TITLE: {
                    "title": [
                        {
                            "text": {
                                "content": task.title,
                            },
                        },
                    ],
                },
                TASK_PROP_DUE: {
                    "date": {
                        "start": task.due_date.isoformat(),
                    },
                },
                TASK_PROP_STATUS: {
                    "select": {
                        "name": self._get_status_name(task.status.value),
                    },
                },
                "タスク種類": {
                    "select": {
                        "name": task.task_type,
                    },
                },
                "緊急度": {
                    "select": {
                        "name": task.urgency,
                    },
                },
                TASK_PROP_REMINDER_STAGE: {
                    "select": {"name": REMINDER_STAGE_NOT_SENT},
                },
                TASK_PROP_REMINDER_READ: {
                    "checkbox": False,
                },
                TASK_PROP_EXTENSION_STATUS: {
                    "select": {"name": EXTENSION_STATUS_NONE},
                },
                TASK_PROP_COMPLETION_STATUS: {
                    "select": {"name": COMPLETION_STATUS_IN_PROGRESS},
                },
                TASK_PROP_COMPLETION_NOTE: {
                    "rich_text": [],
                },
                TASK_PROP_TASK_APPROVAL_REQUESTED_AT: {
                    "date": {
                        "start": now.isoformat(),
                    },
                },
                TASK_PROP_APPROVAL_REMINDER_AT: {
                    "date": None,
                },
            }

            # 依頼者プロパティ（Peopleタイプ）
            if requester_user:
                properties["依頼者"] = {
                    "people": [
                        {
                            "object": "user",
                            "id": str(requester_user.user_id),
                        },
                    ],
                }
                print(f"✅ 依頼者設定: {requester_user.display_name()} ({requester_email})")
            else:
                print(f"⚠️ Requester '{requester_email}' not found in Notion users. Skipping people property.")

            # 依頼先プロパティ（Peopleタイプ）
            if assignee_user:
                properties["依頼先"] = {
                    "people": [
                        {
                            "object": "user",
                            "id": str(assignee_user.user_id),
                        },
                    ],
                }
                print(f"✅ 依頼先設定: {assignee_user.display_name()} ({assignee_email})")
            else:
                print(f"⚠️ Assignee '{assignee_email}' not found in Notion users. Skipping people property.")

            # リッチテキストをNotionブロックに変換（descriptionがある場合のみ）
            description_blocks = []
            if task.description:
                description_blocks = self._convert_slack_rich_text_to_notion(task.description)

            # ページを作成（詳細はページ本文に記載）
            page_children = [
                {
                    "object": "block",
                    "type": "heading_1",
                    "heading_1": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": "📋 タスク概要",
                                },
                            },
                        ],
                    },
                },
                {
                    "object": "block",
                    "type": "callout",
                    "callout": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": f"依頼者: {requester_email or 'Unknown'}\n"
                                              f"依頼先: {assignee_email or 'Unknown'}\n"
                                              f"納期: {task.due_date.strftime('%Y年%m月%d日 %H:%M')}\n"
                                              f"タスク種類: {task.task_type}\n"
                                              f"緊急度: {task.urgency}",
                                },
                            },
                        ],
                        "icon": {
                            "emoji": "ℹ️",
                        },
                        "color": "blue_background",
                    },
                },
                {
                    "object": "block",
                    "type": "divider",
                    "divider": {},
                },
            ]

            # descriptionがある場合のみタスク内容セクションを追加
            if description_blocks:
                page_children.extend([
                    {
                        "object": "block",
                        "type": "heading_2",
                        "heading_2": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {
                                        "content": "📝 タスク内容",
                                    },
                                },
                            ],
                        },
                    },
                ])
                # リッチテキストブロックを追加
                page_children.extend(description_blocks)

            # 進捗メモセクションを追加
            page_children.extend([
                {
                    "object": "block",
                    "type": "divider",
                    "divider": {},
                },
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": "✅ 進捗メモ",
                                },
                            },
                        ],
                    },
                },
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": "（ここに進捗や作業メモを記入してください）",
                                },
                            },
                        ],
                    },
                },
            ])

            response = self.client.pages.create(
                parent={"database_id": self.database_id},
                properties=properties,
                children=page_children,
            )

            print("✅ Dynamic Notion task created successfully!")
            return response["id"]

        except Exception as e:
            error_msg = f"Error creating Notion task (dynamic): {e}"
            print(error_msg)
            print(f"Database ID: {self.database_id}")
            description_preview = convert_rich_text_to_plain_text(task.description)
            print(f"Task details: title='{task.title}', description='{description_preview[:100]}...'")

            if "is in trash" in str(e):
                raise

            # 権限エラーの場合の詳細メッセージ
            if "shared with your integration" in str(e):
                print("\n🔧 解決方法:")
                print("1. Notionでデータベースページを開く")
                print("2. 右上の「共有」ボタンをクリック")
                print("3. 「Task Request Bot」Integrationを招待")
                print("4. 「招待」をクリック")

            # 結合データベース（複数ソース）の場合
            elif "multiple data sources" in str(e).lower():
                print("\n🔧 データベース種別エラー:")
                print("指定された NOTION_DATABASE_ID は複数のデータソースを結合したデータベース（リンク/結合ビュー）です。")
                print("Notion APIではこの種別に対する query/create がサポートされません。")
                print("- 対応策: 元の単一ソースのタスクDBのIDを NOTION_DATABASE_ID に設定してください。")
                print("- 参考: データベースのURLから32桁のID（ハイフン除去）を設定します。")

            # データベースが見つからない場合
            elif "Could not find database" in str(e):
                print("\n🔧 データベースIDエラー:")
                print(f"指定されたID '{self.database_id}' のデータベースが見つかりません")
                print("1. NotionデータベースのURLを確認")
                print("2. 環境変数 NOTION_DATABASE_ID を正しく設定")

            # プロパティエラーの場合
            elif "property" in str(e).lower():
                print("\n🔧 プロパティエラー:")
                print("以下のプロパティが正しく設定されているか確認:")
                print("- タイトル (Title)")
                print("- 納期 (Date)")
                print("- ステータス (Select: 承認待ち, 承認済み, 差し戻し)")
                print("- 依頼者 (Person)")
                print("- 依頼先 (Person)")

            # エラーを再発生させず、None を返す
            return None

    def _get_status_name(self, status: str) -> str:
        """ステータスの表示名を取得"""
        status_map = {
            "pending": TASK_STATUS_PENDING,
            "approved": TASK_STATUS_APPROVED,
            "rejected": TASK_STATUS_REJECTED,
            "completed": TASK_STATUS_COMPLETED,
            "disabled": TASK_STATUS_DISABLED,
        }
        return status_map.get(status, TASK_STATUS_PENDING)

    async def get_task_by_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        """タスクIDでNotionページを取得

        Args:
            task_id: NotionページID

        Returns:
            タスク情報の辞書。以下の項目を含む:
            - id: ページID
            - title: タイトル
            - content: 内容
            - due_date: 納期
            - requester_name: 依頼者名
            - assignee_name: 依頼先名
            - notion_url: NotionページのURL
            - status: ステータス
        """
        try:
            # ページ情報を取得
            page = self.client.pages.retrieve(page_id=task_id)
            properties = page.get("properties", {})

            # プロパティから情報を抽出
            title = ""
            if "タイトル" in properties and properties["タイトル"]["title"]:
                title = properties["タイトル"]["title"][0]["text"]["content"]

            due_date = None
            if "納期" in properties and properties["納期"].get("date"):
                due_date = properties["納期"]["date"]["start"]

            requester_name = ""
            if "依頼者" in properties and properties["依頼者"].get("people"):
                people = properties["依頼者"]["people"]
                if people:
                    # ユーザー情報を取得
                    user_id = people[0]["id"]
                    try:
                        user = self.client.users.retrieve(user_id=user_id)
                        requester_name = user.get("name", "")
                    except Exception:
                        requester_name = "不明"

            assignee_name = ""
            if "依頼先" in properties and properties["依頼先"].get("people"):
                people = properties["依頼先"]["people"]
                if people:
                    # ユーザー情報を取得
                    user_id = people[0]["id"]
                    try:
                        user = self.client.users.retrieve(user_id=user_id)
                        assignee_name = user.get("name", "")
                    except Exception:
                        assignee_name = "不明"

            status = ""
            if "ステータス" in properties and properties["ステータス"].get("select"):
                status = properties["ステータス"]["select"]["name"]

            # ページコンテンツを取得
            content_blocks = self.client.blocks.children.list(block_id=task_id)
            content = ""
            for block in content_blocks.get("results", []):
                if block["type"] == "paragraph" and block.get("paragraph", {}).get("rich_text"):
                    for rich_text in block["paragraph"]["rich_text"]:
                        if rich_text["type"] == "text":
                            content += rich_text["text"]["content"] + "\n"

            # Notion URLを生成
            notion_url = page.get("url", f"https://www.notion.so/{task_id.replace('-', '')}")

            return {
                "id": task_id,
                "title": title,
                "content": content.strip(),
                "due_date": due_date,
                "requester_name": requester_name,
                "assignee_name": assignee_name,
                "notion_url": notion_url,
                "status": status,
            }

        except Exception as e:
            print(f"Error getting task from Notion: {e}")
            return None

    async def fetch_active_tasks(self) -> List[NotionTaskSnapshot]:
        """リマインド対象となり得るタスク一覧を取得"""
        results: List[NotionTaskSnapshot] = []
        has_more = True
        start_cursor = None

        filter_conditions: List[Dict[str, Any]] = [
            {
                "property": TASK_PROP_DUE,
                "date": {"is_not_empty": True},
            }
        ]

        for status in EXCLUDED_STATUSES_FOR_REMINDER:
            filter_conditions.append(
                {
                    "property": TASK_PROP_STATUS,
                    "select": {"does_not_equal": status},
                }
            )

        while has_more:
            query_payload: Dict[str, Any] = {
                "database_id": self.database_id,
                "page_size": 100,
                "filter": {"and": filter_conditions},
                "sorts": [
                    {
                        "property": TASK_PROP_DUE,
                        "direction": "ascending",
                    }
                ],
            }

            if start_cursor:
                query_payload["start_cursor"] = start_cursor
            try:
                response = self.client.databases.query(**query_payload)
            except Exception as e:
                if "multiple data sources" in str(e).lower():
                    print("❌ Notionデータベースは複数ソースの結合DBのため、APIでの検索ができません。")
                    print("   元の単一ソースDBのIDを NOTION_DATABASE_ID に設定してください。")
                else:
                    print(f"❌ Notionデータベース問い合わせエラー: {e}")
                # 致命的なので以降の処理は打ち切り
                break
            for page in response.get("results", []):
                try:
                    snapshot = self._to_snapshot(page)
                    if snapshot.due_date:
                        results.append(snapshot)
                except Exception as exc:
                    print(f"⚠️ Failed to parse Notion task snapshot: {exc}")

            has_more = response.get("has_more", False)
            start_cursor = response.get("next_cursor")

        return results

    async def fetch_pending_approval_tasks(self) -> List[NotionTaskSnapshot]:
        """承認待ち状態のタスク一覧を取得（タスク承認待ち、完了承認待ち、延期承認待ち）"""
        results: List[NotionTaskSnapshot] = []
        has_more = True
        start_cursor = None

        # 承認待ちタスクのフィルタ条件（OR条件）
        filter_conditions: Dict[str, Any] = {
            "or": [
                {
                    "property": TASK_PROP_STATUS,
                    "select": {"equals": TASK_STATUS_PENDING},
                },
                {
                    "property": TASK_PROP_COMPLETION_STATUS,
                    "select": {"equals": COMPLETION_STATUS_REQUESTED},
                },
                {
                    "property": TASK_PROP_EXTENSION_STATUS,
                    "select": {"equals": EXTENSION_STATUS_PENDING},
                },
            ]
        }

        print(f"🔍 承認待ちタスク取得開始:")
        print(f"  - フィルタ条件: {filter_conditions}")
        print(f"  - ステータス値: {TASK_STATUS_PENDING}, {COMPLETION_STATUS_REQUESTED}, {EXTENSION_STATUS_PENDING}")

        while has_more:
            query_payload: Dict[str, Any] = {
                "database_id": self.database_id,
                "page_size": 100,
                "filter": filter_conditions,
                "sorts": [
                    {
                        "timestamp": "created_time",
                        "direction": "ascending",
                    }
                ],
            }

            if start_cursor:
                query_payload["start_cursor"] = start_cursor

            try:
                response = self.client.databases.query(**query_payload)
                page_count = len(response.get("results", []))
                print(f"✅ Notionクエリ成功: {page_count}件のタスクを取得")
            except Exception as e:
                print(f"❌ 承認待ちタスク取得エラー: {e}")
                print(f"   クエリペイロード: {query_payload}")
                break

            for page in response.get("results", []):
                try:
                    snapshot = self._to_snapshot(page)
                    results.append(snapshot)
                    print(f"  ✓ タスク追加: {snapshot.title} (status={snapshot.status}, completion={snapshot.completion_status}, extension={snapshot.extension_status})")
                except Exception as exc:
                    print(f"⚠️ Failed to parse pending approval task snapshot: {exc}")

            has_more = response.get("has_more", False)
            start_cursor = response.get("next_cursor")

        print(f"📊 承認待ちタスク取得完了: 合計 {len(results)}件")
        return results

    async def get_task_snapshot(self, page_id: str) -> Optional[NotionTaskSnapshot]:
        try:
            page = self.client.pages.retrieve(page_id=page_id)
            return self._to_snapshot(page)
        except Exception as exc:
            print(f"⚠️ Failed to get Notion task snapshot: {exc}")
            return None

    async def record_audit_log(
        self,
        task_page_id: str,
        event_type: str,
        detail: str,
        actor_email: Optional[str] = None,
    ) -> Optional[str]:
        if not self.audit_database_id:
            print("⚠️ Audit database ID is not configured; skipping log entry.")
            return None

        properties: Dict[str, Any] = {
            AUDIT_PROP_TITLE: {
                "title": [
                    {
                        "text": {
                            "content": f"{event_type} - {datetime.now(JST).strftime('%Y/%m/%d %H:%M')}"
                        }
                    }
                ]
            },
            AUDIT_PROP_EVENT_TYPE: {
                "select": {"name": event_type}
            },
            AUDIT_PROP_TASK_RELATION: {
                "relation": [{"id": task_page_id}]
            },
            AUDIT_PROP_DETAIL: {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": detail[:2000]},
                    }
                ]
            },
            AUDIT_PROP_OCCURRED_AT: {
                "date": {
                    "start": self._format_datetime(datetime.now(JST))
                }
            },
        }

        if actor_email:
            notion_user = await self.user_mapping_service.find_notion_user_by_email(actor_email)
            if notion_user:
                properties[AUDIT_PROP_ACTOR] = {
                    "people": [
                        {
                            "object": "user",
                            "id": str(notion_user.user_id),
                        }
                    ]
                }

        try:
            response = self.client.pages.create(
                parent={"database_id": self.audit_database_id},
                properties=properties,
            )
            return response.get("id")
        except Exception as exc:
            print(f"⚠️ Failed to create audit log entry: {exc}")
            return None

    async def update_reminder_state(
        self,
        page_id: str,
        stage: str,
        reminder_time: datetime,
    ) -> None:
        properties = {
            TASK_PROP_REMINDER_STAGE: {"select": {"name": stage}},
            TASK_PROP_REMINDER_READ: {"checkbox": False},
            TASK_PROP_LAST_REMIND_AT: {"date": {"start": self._format_datetime(reminder_time)}},
        }

        try:
            self.client.pages.update(page_id=page_id, properties=properties)
        except Exception as exc:
            print(f"⚠️ Failed to update reminder state in Notion: {exc}")

    async def update_approval_reminder_time(
        self,
        page_id: str,
        reminder_time: datetime,
    ) -> None:
        """承認リマインド最終送信日時を更新"""
        properties = {
            TASK_PROP_APPROVAL_REMINDER_AT: {"date": {"start": self._format_datetime(reminder_time)}},
        }

        try:
            self.client.pages.update(page_id=page_id, properties=properties)
        except Exception as exc:
            print(f"⚠️ Failed to update approval reminder time in Notion: {exc}")

    async def disable_task(
        self,
        page_id: str,
    ) -> None:
        """タスクを無効化（論理削除）"""
        properties = {
            TASK_PROP_STATUS: {"select": {"name": TASK_STATUS_DISABLED}},
        }

        try:
            self.client.pages.update(page_id=page_id, properties=properties)
            print(f"✅ Task {page_id} has been disabled (logical delete)")
        except Exception as exc:
            print(f"⚠️ Failed to disable task in Notion: {exc}")
            raise

    async def save_thread_info(
        self,
        page_id: str,
        assignee_thread_ts: Optional[str] = None,
        assignee_thread_channel: Optional[str] = None,
        requester_thread_ts: Optional[str] = None,
        requester_thread_channel: Optional[str] = None,
    ) -> None:
        """Slackスレッド情報をNotionに保存"""
        properties: Dict[str, Any] = {}

        if assignee_thread_ts:
            properties[TASK_PROP_ASSIGNEE_THREAD_TS] = {
                "rich_text": [{"text": {"content": assignee_thread_ts}}]
            }

        if assignee_thread_channel:
            properties[TASK_PROP_ASSIGNEE_THREAD_CHANNEL] = {
                "rich_text": [{"text": {"content": assignee_thread_channel}}]
            }

        if requester_thread_ts:
            properties[TASK_PROP_REQUESTER_THREAD_TS] = {
                "rich_text": [{"text": {"content": requester_thread_ts}}]
            }

        if requester_thread_channel:
            properties[TASK_PROP_REQUESTER_THREAD_CHANNEL] = {
                "rich_text": [{"text": {"content": requester_thread_channel}}]
            }

        if not properties:
            return

        try:
            self.client.pages.update(page_id=page_id, properties=properties)
            print(f"✅ Saved thread info for task {page_id}")
        except Exception as exc:
            print(f"⚠️ Failed to save thread info to Notion: {exc}")
            # スレッド情報の保存失敗は致命的ではないので、エラーを投げない

    async def mark_reminder_read(
        self,
        page_id: str,
        read_time: datetime,
        stage: Optional[str] = None,
    ) -> None:
        properties: Dict[str, Any] = {
            TASK_PROP_LAST_READ_AT: {"date": {"start": self._format_datetime(read_time)}}
        }

        # ステージ別の既読フラグを優先的に使用（存在しない場合でもAPIは無視するため安全）
        if stage == REMINDER_STAGE_DUE:
            properties[TASK_PROP_DUE_READ] = {"checkbox": True}
        elif stage == REMINDER_STAGE_OVERDUE:
            properties[TASK_PROP_OVERDUE_READ] = {"checkbox": True}
        else:
            # 後方互換: ステージ不明時は従来の既読フラグを立てる
            properties[TASK_PROP_REMINDER_READ] = {"checkbox": True}

        try:
            self.client.pages.update(page_id=page_id, properties=properties)
        except Exception as exc:
            print(f"⚠️ Failed to mark reminder as read: {exc}")
            # フォールバック: ステージ別プロパティが存在しない場合は従来の既読フラグ/ステージを使用
            try:
                fallback_props: Dict[str, Any] = {
                    TASK_PROP_REMINDER_STAGE: {"select": {"name": REMINDER_STAGE_ACKED}},
                    TASK_PROP_REMINDER_READ: {"checkbox": True},
                    TASK_PROP_LAST_READ_AT: {"date": {"start": self._format_datetime(read_time)}},
                }
                self.client.pages.update(page_id=page_id, properties=fallback_props)
                print("🔁 Fallback: marked as read using legacy properties")
            except Exception as exc2:
                print(f"❌ Fallback failed to mark reminder as read: {exc2}")

    async def set_extension_request(
        self,
        page_id: str,
        requested_due: datetime,
        reason: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        properties = {
            TASK_PROP_EXTENSION_STATUS: {
                "select": {"name": EXTENSION_STATUS_PENDING},
            },
            TASK_PROP_EXTENSION_DUE: {
                "date": {"start": self._format_datetime(requested_due)},
            },
            TASK_PROP_EXTENSION_REASON: {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": reason[:2000]},
                    }
                ],
            },
            TASK_PROP_EXTENSION_REQUESTED_AT: {
                "date": {"start": self._format_datetime(now)},
            },
            TASK_PROP_APPROVAL_REMINDER_AT: {
                "date": None,
            },
        }

        try:
            self.client.pages.update(page_id=page_id, properties=properties)
        except Exception as exc:
            print(f"⚠️ Failed to register extension request: {exc}")

    async def approve_extension(
        self,
        page_id: str,
        approved_due: datetime,
    ) -> None:
        properties = {
            TASK_PROP_DUE: {
                "date": {"start": self._format_datetime(approved_due)},
            },
            TASK_PROP_EXTENSION_STATUS: {
                "select": {"name": EXTENSION_STATUS_APPROVED},
            },
            TASK_PROP_EXTENSION_DUE: {
                "date": None,
            },
            TASK_PROP_EXTENSION_REASON: {
                "rich_text": [],
            },
            TASK_PROP_REMINDER_STAGE: {
                "select": {"name": REMINDER_STAGE_NOT_SENT},
            },
            TASK_PROP_REMINDER_READ: {
                "checkbox": False,
            },
            TASK_PROP_LAST_REMIND_AT: {
                "date": None,
            },
            TASK_PROP_LAST_READ_AT: {
                "date": None,
            },
            TASK_PROP_COMPLETION_STATUS: {
                "select": {"name": COMPLETION_STATUS_IN_PROGRESS},
            },
            TASK_PROP_COMPLETION_REQUESTED_AT: {
                "date": None,
            },
            TASK_PROP_COMPLETION_NOTE: {
                "rich_text": [],
            },
        }

        try:
            self.client.pages.update(page_id=page_id, properties=properties)
        except Exception as exc:
            print(f"⚠️ Failed to approve extension: {exc}")

    async def reject_extension(self, page_id: str) -> None:
        properties = {
            TASK_PROP_EXTENSION_STATUS: {
                "select": {"name": EXTENSION_STATUS_REJECTED},
            },
            TASK_PROP_EXTENSION_DUE: {
                "date": None,
            },
        }

        try:
            self.client.pages.update(page_id=page_id, properties=properties)
        except Exception as exc:
            print(f"⚠️ Failed to reject extension: {exc}")

    async def request_completion(
        self,
        page_id: str,
        request_time: datetime,
        note: Optional[str],
        requested_before_due: bool,
    ) -> None:
        properties = {
            TASK_PROP_COMPLETION_STATUS: {
                "select": {"name": COMPLETION_STATUS_REQUESTED},
            },
            TASK_PROP_COMPLETION_REQUESTED_AT: {
                "date": {"start": self._format_datetime(request_time)},
            },
            TASK_PROP_COMPLETION_APPROVED_AT: {
                "date": None,
            },
            TASK_PROP_COMPLETION_REJECT_REASON: {
                "rich_text": [],
            },
            TASK_PROP_REMINDER_STAGE: {
                "select": {"name": REMINDER_STAGE_ACKED},
            },
            TASK_PROP_REMINDER_READ: {
                "checkbox": True,
            },
            TASK_PROP_LAST_READ_AT: {
                "date": {"start": self._format_datetime(request_time)},
            },
            TASK_PROP_APPROVAL_REMINDER_AT: {
                "date": None,
            },
        }

        if note:
            properties[TASK_PROP_COMPLETION_NOTE] = {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": note[:2000]},
                    }
                ]
            }
        else:
            properties[TASK_PROP_COMPLETION_NOTE] = {"rich_text": []}

        try:
            self.client.pages.update(page_id=page_id, properties=properties)
        except Exception as exc:
            print(f"⚠️ Failed to register completion request: {exc}")

    async def approve_completion(
        self,
        page_id: str,
        approval_time: datetime,
        requested_before_due: bool,
    ) -> None:
        properties = {
            TASK_PROP_COMPLETION_STATUS: {
                "select": {"name": COMPLETION_STATUS_APPROVED},
            },
            TASK_PROP_COMPLETION_APPROVED_AT: {
                "date": {"start": self._format_datetime(approval_time)},
            },
            TASK_PROP_REMINDER_STAGE: {
                "select": {"name": REMINDER_STAGE_ACKED},
            },
            TASK_PROP_REMINDER_READ: {
                "checkbox": True,
            },
        }

        try:
            self.client.pages.update(page_id=page_id, properties=properties)
        except Exception as exc:
            print(f"⚠️ Failed to approve completion: {exc}")

    async def reject_completion(
        self,
        page_id: str,
        new_due: datetime,
        reason: str,
    ) -> None:
        properties = {
            TASK_PROP_COMPLETION_STATUS: {
                "select": {"name": COMPLETION_STATUS_REJECTED},
            },
            TASK_PROP_COMPLETION_REQUESTED_AT: {
                "date": None,
            },
            TASK_PROP_COMPLETION_APPROVED_AT: {
                "date": None,
            },
            TASK_PROP_COMPLETION_REJECT_REASON: {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": reason[:2000]},
                    }
                ],
            },
            TASK_PROP_COMPLETION_NOTE: {
                "rich_text": [],
            },
            TASK_PROP_DUE: {
                "date": {"start": self._format_datetime(new_due)},
            },
            TASK_PROP_REMINDER_STAGE: {
                "select": {"name": REMINDER_STAGE_NOT_SENT},
            },
            TASK_PROP_REMINDER_READ: {
                "checkbox": False,
            },
            TASK_PROP_LAST_REMIND_AT: {
                "date": None,
            },
            TASK_PROP_LAST_READ_AT: {
                "date": None,
            },
        }

        try:
            self.client.pages.update(page_id=page_id, properties=properties)
        except Exception as exc:
            print(f"⚠️ Failed to reject completion request: {exc}")


    def _to_snapshot(self, page: Dict[str, Any]) -> NotionTaskSnapshot:
        properties = page.get("properties", {})

        title = ""
        title_prop = properties.get(TASK_PROP_TITLE)
        if title_prop and title_prop.get("title"):
            title = title_prop["title"][0]["plain_text"]

        due_prop = properties.get(TASK_PROP_DUE, {})
        due_date = self._parse_datetime(due_prop.get("date"))

        status_prop = properties.get(TASK_PROP_STATUS, {})
        status_name = None
        if status_prop.get("select"):
            status_name = status_prop["select"].get("name")

        requester_prop = properties.get(TASK_PROP_REQUESTER)
        requester_id, requester_email = self._extract_people(requester_prop)

        assignee_prop = properties.get(TASK_PROP_ASSIGNEE)
        assignee_id, assignee_email = self._extract_people(assignee_prop)

        reminder_stage_prop = properties.get(TASK_PROP_REMINDER_STAGE, {})
        reminder_stage = None
        if reminder_stage_prop.get("select"):
            reminder_stage = reminder_stage_prop["select"].get("name")

        last_remind_at_prop = properties.get(TASK_PROP_LAST_REMIND_AT, {})
        last_remind_at = self._parse_datetime(last_remind_at_prop.get("date"))

        reminder_read_prop = properties.get(TASK_PROP_REMINDER_READ, {})
        reminder_read = bool(reminder_read_prop.get("checkbox", False))

        last_read_at_prop = properties.get(TASK_PROP_LAST_READ_AT, {})
        reminder_read_at = self._parse_datetime(last_read_at_prop.get("date"))

        # ステージ別の既読フラグ（存在しなければ False とする）
        has_due_read_prop = TASK_PROP_DUE_READ in properties
        due_read_prop = properties.get(TASK_PROP_DUE_READ, {})
        due_stage_read = bool(due_read_prop.get("checkbox", False))
        has_overdue_read_prop = TASK_PROP_OVERDUE_READ in properties
        overdue_read_prop = properties.get(TASK_PROP_OVERDUE_READ, {})
        overdue_stage_read = bool(overdue_read_prop.get("checkbox", False))

        extension_status_prop = properties.get(TASK_PROP_EXTENSION_STATUS, {})
        extension_status = None
        if extension_status_prop.get("select"):
            extension_status = extension_status_prop["select"].get("name")

        extension_due_prop = properties.get(TASK_PROP_EXTENSION_DUE, {})
        extension_requested_due = self._parse_datetime(extension_due_prop.get("date"))

        extension_reason_prop = properties.get(TASK_PROP_EXTENSION_REASON)
        extension_reason = self._extract_rich_text(extension_reason_prop)

        completion_status_prop = properties.get(TASK_PROP_COMPLETION_STATUS, {})
        completion_status = None
        if completion_status_prop.get("select"):
            completion_status = completion_status_prop["select"].get("name")

        completion_requested_prop = properties.get(TASK_PROP_COMPLETION_REQUESTED_AT, {})
        completion_requested_at = self._parse_datetime(completion_requested_prop.get("date"))

        completion_note_prop = properties.get(TASK_PROP_COMPLETION_NOTE)
        completion_note = self._extract_rich_text(completion_note_prop)

        completion_approved_prop = properties.get(TASK_PROP_COMPLETION_APPROVED_AT, {})
        completion_approved_at = self._parse_datetime(completion_approved_prop.get("date"))

        completion_reject_reason_prop = properties.get(TASK_PROP_COMPLETION_REJECT_REASON)
        completion_reject_reason = self._extract_rich_text(completion_reject_reason_prop)

        created_time = self._parse_datetime_string(page.get("created_time"))

        approval_reminder_prop = properties.get(TASK_PROP_APPROVAL_REMINDER_AT, {})
        approval_reminder_last_sent_at = self._parse_datetime(approval_reminder_prop.get("date"))

        extension_requested_at_prop = properties.get(TASK_PROP_EXTENSION_REQUESTED_AT, {})
        extension_requested_at = self._parse_datetime(extension_requested_at_prop.get("date"))

        task_approval_requested_at_prop = properties.get(TASK_PROP_TASK_APPROVAL_REQUESTED_AT, {})
        task_approval_requested_at = self._parse_datetime(task_approval_requested_at_prop.get("date"))

        # Slackスレッド情報を取得
        assignee_thread_ts_prop = properties.get(TASK_PROP_ASSIGNEE_THREAD_TS)
        assignee_thread_ts = self._extract_rich_text(assignee_thread_ts_prop)

        assignee_thread_channel_prop = properties.get(TASK_PROP_ASSIGNEE_THREAD_CHANNEL)
        assignee_thread_channel = self._extract_rich_text(assignee_thread_channel_prop)

        requester_thread_ts_prop = properties.get(TASK_PROP_REQUESTER_THREAD_TS)
        requester_thread_ts = self._extract_rich_text(requester_thread_ts_prop)

        requester_thread_channel_prop = properties.get(TASK_PROP_REQUESTER_THREAD_CHANNEL)
        requester_thread_channel = self._extract_rich_text(requester_thread_channel_prop)

        return NotionTaskSnapshot(
            page_id=page.get("id"),
            title=title,
            due_date=due_date,
            status=status_name,
            requester_email=requester_email,
            requester_notion_id=requester_id,
            assignee_email=assignee_email,
            assignee_notion_id=assignee_id,
            reminder_stage=reminder_stage,
            reminder_last_sent_at=last_remind_at,
            reminder_read=reminder_read,
            reminder_read_at=reminder_read_at,
            due_stage_read=due_stage_read,
            overdue_stage_read=overdue_stage_read,
            extension_status=extension_status,
            extension_requested_due=extension_requested_due,
            extension_reason=extension_reason,
            completion_status=completion_status,
            completion_requested_at=completion_requested_at,
            completion_note=completion_note,
            completion_approved_at=completion_approved_at,
            completion_reject_reason=completion_reject_reason,
            has_due_read_prop=has_due_read_prop,
            has_overdue_read_prop=has_overdue_read_prop,
            created_time=created_time,
            approval_reminder_last_sent_at=approval_reminder_last_sent_at,
            extension_requested_at=extension_requested_at,
            task_approval_requested_at=task_approval_requested_at,
            assignee_thread_ts=assignee_thread_ts,
            assignee_thread_channel=assignee_thread_channel,
            requester_thread_ts=requester_thread_ts,
            requester_thread_channel=requester_thread_channel,
        )

    async def update_task_status(
        self,
        page_id: str,
        status: str,
        rejection_reason: Optional[str] = None,
    ):
        """タスクのステータスを更新"""
        try:
            self._ensure_page_editable(page_id, "updating task status")

            properties = {
                "ステータス": {
                    "select": {
                        "name": self._get_status_name(status),
                    },
                },
            }

            # 差し戻し理由がある場合は追加
            if rejection_reason:
                properties["差し戻し理由"] = {
                    "rich_text": [
                        {
                            "text": {
                                "content": rejection_reason,
                            },
                        },
                    ],
                }

            self.client.pages.update(
                page_id=page_id,
                properties=properties,
            )

        except Exception as e:
            print(f"Error updating Notion task: {e}")
            raise

    async def update_task_revision(
        self,
        task: TaskRequest,
        requester_email: Optional[str],
        assignee_email: Optional[str],
    ) -> None:
        """差し戻し後のタスク内容を更新"""
        if not task.notion_page_id:
            return

        requester_user: Optional[NotionUser] = None
        assignee_user: Optional[NotionUser] = None
        try:
            requester_user, assignee_user = await self.user_mapping_service.get_notion_user_for_task_creation(
                requester_email,
                assignee_email,
            )
        except Exception as mapping_error:
            print(f"⚠️ Failed to resolve Notion users during revision: {mapping_error}")

        properties: Dict[str, Any] = {
            TASK_PROP_TITLE: {
                "title": [
                    {
                        "text": {"content": task.title},
                    }
                ],
            },
            TASK_PROP_DUE: {
                "date": {"start": task.due_date.isoformat()},
            },
            TASK_PROP_STATUS: {
                "select": {"name": self._get_status_name(task.status.value)},
            },
            "タスク種類": {
                "select": {"name": task.task_type},
            },
            "緊急度": {
                "select": {"name": task.urgency},
            },
            TASK_PROP_REMINDER_STAGE: {
                "select": {"name": REMINDER_STAGE_NOT_SENT},
            },
            TASK_PROP_REMINDER_READ: {
                "checkbox": False,
            },
            TASK_PROP_LAST_REMIND_AT: {
                "date": None,
            },
            TASK_PROP_LAST_READ_AT: {
                "date": None,
            },
            TASK_PROP_EXTENSION_STATUS: {
                "select": {"name": EXTENSION_STATUS_NONE},
            },
            TASK_PROP_EXTENSION_DUE: {
                "date": None,
            },
            TASK_PROP_EXTENSION_REASON: {
                "rich_text": [],
            },
            TASK_PROP_COMPLETION_STATUS: {
                "select": {"name": COMPLETION_STATUS_IN_PROGRESS},
            },
            TASK_PROP_COMPLETION_REQUESTED_AT: {
                "date": None,
            },
            TASK_PROP_COMPLETION_APPROVED_AT: {
                "date": None,
            },
            TASK_PROP_COMPLETION_NOTE: {
                "rich_text": [],
            },
            TASK_PROP_COMPLETION_REJECT_REASON: {
                "rich_text": [],
            },
            TASK_PROP_APPROVAL_REMINDER_AT: {
                "date": None,
            },
        }

        if requester_user:
            properties[TASK_PROP_REQUESTER] = {
                "people": [
                    {
                        "object": "user",
                        "id": str(requester_user.user_id),
                    }
                ]
            }
        elif requester_email:
            properties[TASK_PROP_REQUESTER] = {"people": []}

        if assignee_user:
            properties[TASK_PROP_ASSIGNEE] = {
                "people": [
                    {
                        "object": "user",
                        "id": str(assignee_user.user_id),
                    }
                ]
            }
        elif assignee_email:
            properties[TASK_PROP_ASSIGNEE] = {"people": []}

        try:
            self.client.pages.update(page_id=task.notion_page_id, properties=properties)
        except Exception as update_error:
            print(f"⚠️ Failed to update Notion task properties on revision: {update_error}")
            return

        try:
            await self._refresh_revision_content(
                page_id=task.notion_page_id,
                task=task,
                requester_email=requester_email,
                assignee_email=assignee_email,
            )
        except Exception as content_error:
            print(f"⚠️ Failed to refresh Notion task content on revision: {content_error}")

    async def _refresh_revision_content(
        self,
        page_id: str,
        task: TaskRequest,
        requester_email: Optional[str],
        assignee_email: Optional[str],
    ) -> None:
        children = self._list_page_children(page_id)
        self._update_task_summary_callout(children, task, requester_email, assignee_email)
        self._update_description_section(page_id, children, task.description)

    def _list_page_children(self, page_id: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        start_cursor: Optional[str] = None

        while True:
            response = self.client.blocks.children.list(
                block_id=page_id,
                start_cursor=start_cursor,
                page_size=100,
            )
            results.extend(response.get("results", []))
            if not response.get("has_more"):
                break
            start_cursor = response.get("next_cursor")

        return results

    def _update_task_summary_callout(
        self,
        children: List[Dict[str, Any]],
        task: TaskRequest,
        requester_email: Optional[str],
        assignee_email: Optional[str],
    ) -> None:
        for block in children:
            if block.get("type") != "callout":
                continue

            callout_info = block.get("callout", {})
            icon = callout_info.get("icon") or {"emoji": "ℹ️"}
            color = callout_info.get("color", "blue_background")

            summary_text = (
                f"依頼者: {requester_email or 'Unknown'}\n"
                f"依頼先: {assignee_email or 'Unknown'}\n"
                f"納期: {task.due_date.astimezone(JST).strftime('%Y年%m月%d日 %H:%M')}\n"
                f"タスク種類: {task.task_type}\n"
                f"緊急度: {task.urgency}"
            )

            try:
                self.client.blocks.update(
                    block_id=block["id"],
                    callout={
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {"content": summary_text},
                            }
                        ],
                        "icon": icon,
                        "color": color,
                    },
                )
            except Exception as update_error:
                print(f"⚠️ Failed to update summary callout: {update_error}")
            finally:
                break

    def _update_description_section(
        self,
        page_id: str,
        children: List[Dict[str, Any]],
        description: Optional[Union[str, Dict[str, Any]]],
    ) -> None:
        description_blocks = (
            self._convert_slack_rich_text_to_notion(description)
            if description
            else []
        )

        description_heading_index: Optional[int] = None
        progress_heading_index: Optional[int] = None

        for idx, block in enumerate(children):
            if block.get("type") != "heading_2":
                continue

            heading_text = self._rich_text_to_plain(block["heading_2"].get("rich_text", []))
            if heading_text.startswith("📝 タスク内容"):
                description_heading_index = idx
            elif heading_text.startswith("✅ 進捗メモ"):
                progress_heading_index = idx
                break

        if description_blocks:
            if description_heading_index is None:
                divider_block = next((b for b in children if b.get("type") == "divider"), None)
                insert_after = divider_block["id"] if divider_block else (children[0]["id"] if children else None)

                heading_block = {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {"content": "📝 タスク内容"},
                            }
                        ],
                    },
                }

                try:
                    append_response = self.client.blocks.children.append(
                        block_id=page_id,
                        children=[heading_block],
                        **({"after": insert_after} if insert_after else {}),
                    )
                    results = append_response.get("results", [])
                    if not results or not results[0].get("id"):
                        print("⚠️ Failed to obtain heading id after insertion")
                        return
                    heading_id = results[0]["id"]
                except Exception as append_error:
                    print(f"⚠️ Failed to insert description heading: {append_error}")
                    return
            else:
                heading_id = children[description_heading_index]["id"]
                end_index = self._find_description_end(children, description_heading_index, progress_heading_index)
                for block in children[description_heading_index + 1 : end_index]:
                    try:
                        self.client.blocks.update(block_id=block["id"], archived=True)
                    except Exception as archive_error:
                        print(f"⚠️ Failed to archive old description block: {archive_error}")

            after_id = heading_id
            for block in description_blocks:
                try:
                    response = self.client.blocks.children.append(
                        block_id=page_id,
                        children=[block],
                        after=after_id,
                    )
                    results = response.get("results", [])
                    if results and results[0].get("id"):
                        after_id = results[0]["id"]
                except Exception as append_error:
                    print(f"⚠️ Failed to append description block: {append_error}")
                    try:
                        fallback_response = self.client.blocks.children.append(block_id=page_id, children=[block])
                        results = fallback_response.get("results", [])
                        if results and results[0].get("id"):
                            after_id = results[0]["id"]
                    except Exception as fallback_error:
                        print(f"⚠️ Failed to append description block (fallback): {fallback_error}")
                        break
        else:
            if description_heading_index is not None:
                end_index = self._find_description_end(children, description_heading_index, progress_heading_index)
                for block in children[description_heading_index + 1 : end_index]:
                    try:
                        self.client.blocks.update(block_id=block["id"], archived=True)
                    except Exception as archive_error:
                        print(f"⚠️ Failed to archive description block: {archive_error}")
                try:
                    self.client.blocks.update(block_id=children[description_heading_index]["id"], archived=True)
                except Exception as archive_error:
                    print(f"⚠️ Failed to archive description heading: {archive_error}")

    def _find_description_end(
        self,
        children: List[Dict[str, Any]],
        heading_index: int,
        progress_heading_index: Optional[int],
    ) -> int:
        for idx in range(heading_index + 1, len(children)):
            block = children[idx]
            if block.get("type") == "divider" or block.get("type") == "heading_2":
                return idx
        return progress_heading_index or len(children)

    def _rich_text_to_plain(self, rich_text: List[Dict[str, Any]]) -> str:
        parts: List[str] = []
        for item in rich_text:
            if item.get("type") == "text":
                parts.append(item.get("text", {}).get("content", ""))
        return "".join(parts)
JST = ZoneInfo("Asia/Tokyo")
