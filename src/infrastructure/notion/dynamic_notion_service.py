import json
import os
from typing import Optional, Dict, Any, List, Union
from datetime import datetime
from notion_client import Client
from src.domain.entities.task import TaskRequest
from src.domain.entities.notion_user import NotionUser
from src.application.services.user_mapping_service import UserMappingApplicationService
from src.utils.text_converter import convert_rich_text_to_plain_text


class DynamicNotionService:
    """動的ユーザー検索対応のNotion APIサービス（DDD版）"""

    def __init__(
        self, 
        notion_token: str, 
        database_id: str,
        user_mapping_service: UserMappingApplicationService
    ):
        self.client = Client(auth=notion_token)
        self.database_id = self._normalize_database_id(database_id)
        self.user_mapping_service = user_mapping_service

    def _normalize_database_id(self, database_id: str) -> str:
        """データベースIDを正規化（ハイフンを削除）"""
        return database_id.replace("-", "")

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
                "タイトル": {
                    "title": [
                        {
                            "text": {
                                "content": task.title,
                            },
                        },
                    ],
                },
                "納期": {
                    "date": {
                        "start": task.due_date.isoformat(),
                    },
                },
                "ステータス": {
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
            "pending": "承認待ち",
            "approved": "承認済み",
            "rejected": "差し戻し",
            "completed": "完了",
            "disabled": "無効",
        }
        return status_map.get(status, "承認待ち")

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