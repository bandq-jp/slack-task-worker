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
TASK_PROP_EXTENSION_STATUS = "延期ステータス"
TASK_PROP_EXTENSION_DUE = "延期期日（申請中）"
TASK_PROP_EXTENSION_REASON = "延期理由（申請中）"

TASK_PROP_COMPLETION_STATUS = "完了ステータス"
TASK_PROP_COMPLETION_REQUESTED_AT = "完了申請日時"
TASK_PROP_COMPLETION_APPROVED_AT = "完了承認日時"
TASK_PROP_COMPLETION_NOTE = "完了報告メモ"
TASK_PROP_COMPLETION_REJECT_REASON = "完了却下理由"

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
    extension_status: Optional[str]
    extension_requested_due: Optional[datetime]
    extension_reason: Optional[str]
    completion_status: Optional[str]
    completion_requested_at: Optional[datetime]
    completion_note: Optional[str]
    completion_approved_at: Optional[datetime]
    completion_reject_reason: Optional[str]


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

            # 新しいアプリケーションサービスでユーザー検索
            requester_user, assignee_user = await self.user_mapping_service.get_notion_user_for_task_creation(
                requester_email, 
                assignee_email
            )

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
            TASK_PROP_REMINDER_STAGE: {
                "select": {"name": stage},
            },
            TASK_PROP_REMINDER_READ: {
                "checkbox": False,
            },
            TASK_PROP_LAST_REMIND_AT: {
                "date": {"start": self._format_datetime(reminder_time)},
            },
            TASK_PROP_LAST_READ_AT: {
                "date": None,
            },
        }

        try:
            self.client.pages.update(page_id=page_id, properties=properties)
        except Exception as exc:
            print(f"⚠️ Failed to update reminder state in Notion: {exc}")

    async def mark_reminder_read(
        self,
        page_id: str,
        read_time: datetime,
        stage: Optional[str] = None,
    ) -> None:
        selected_stage = stage or REMINDER_STAGE_ACKED
        properties = {
            TASK_PROP_REMINDER_STAGE: {
                "select": {"name": selected_stage},
            },
            TASK_PROP_REMINDER_READ: {
                "checkbox": True,
            },
            TASK_PROP_LAST_READ_AT: {
                "date": {"start": self._format_datetime(read_time)},
            },
        }

        try:
            self.client.pages.update(page_id=page_id, properties=properties)
        except Exception as exc:
            print(f"⚠️ Failed to mark reminder as read: {exc}")

    async def set_extension_request(
        self,
        page_id: str,
        requested_due: datetime,
        reason: str,
    ) -> None:
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
            extension_status=extension_status,
            extension_requested_due=extension_requested_due,
            extension_reason=extension_reason,
            completion_status=completion_status,
            completion_requested_at=completion_requested_at,
            completion_note=completion_note,
            completion_approved_at=completion_approved_at,
            completion_reject_reason=completion_reject_reason,
        )

    async def update_task_status(
        self,
        page_id: str,
        status: str,
        rejection_reason: Optional[str] = None,
    ):
        """タスクのステータスを更新"""
        try:
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
