import json
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Form, Depends
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional
from src.application.services.task_service import TaskApplicationService
from src.application.dto.task_dto import CreateTaskRequestDto, TaskApprovalDto
from src.infrastructure.slack.slack_service import SlackService
from src.infrastructure.notion.notion_service import NotionService
from src.infrastructure.repositories.task_repository_impl import InMemoryTaskRepository
from src.infrastructure.repositories.user_repository_impl import InMemoryUserRepository
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    slack_token: str = ""
    slack_bot_token: str = ""
    slack_signing_secret: str = ""
    notion_token: str = ""
    notion_database_id: str = ""

    class Config:
        env_file = ".env"


router = APIRouter(prefix="/slack", tags=["slack"])
settings = Settings()

# リポジトリとサービスのインスタンス化（簡易的なDI）
task_repository = InMemoryTaskRepository()
user_repository = InMemoryUserRepository()
slack_service = SlackService(settings.slack_token, settings.slack_bot_token)
notion_service = NotionService(settings.notion_token, settings.notion_database_id)

task_service = TaskApplicationService(
    task_repository=task_repository,
    user_repository=user_repository,
    slack_service=slack_service,
    notion_service=notion_service,
)


@router.post("/commands")
async def handle_slash_command(request: Request):
    """スラッシュコマンドのハンドラー"""
    form = await request.form()
    command = form.get("command")
    trigger_id = form.get("trigger_id")
    user_id = form.get("user_id")

    if command == "/task-request":
        # タスク作成モーダルを開く
        await slack_service.open_task_modal(trigger_id, user_id)
        return JSONResponse(content={"response_type": "ephemeral", "text": ""})

    return JSONResponse(
        content={"response_type": "ephemeral", "text": "Unknown command"}
    )


@router.post("/interactive")
async def handle_interactive(request: Request):
    """インタラクティブコンポーネント（ボタン、モーダル）のハンドラー"""
    form = await request.form()
    payload = json.loads(form.get("payload", "{}"))

    interaction_type = payload.get("type")

    if interaction_type == "block_actions":
        # ボタンアクションの処理
        action = payload["actions"][0]
        action_id = action["action_id"]
        task_id = action["value"]
        trigger_id = payload["trigger_id"]

        if action_id == "approve_task":
            try:
                # タスクを承認
                dto = TaskApprovalDto(
                    task_id=task_id,
                    action="approve",
                    rejection_reason=None,
                )
                await task_service.handle_task_approval(dto)

                # メッセージを更新
                return JSONResponse(
                    content={
                        "response_action": "update",
                        "text": "✅ タスクを承認しました",
                        "blocks": [
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": "✅ このタスクは承認され、Notionに登録されました",
                                },
                            }
                        ],
                    }
                )
            except ValueError as e:
                # エラーメッセージを表示
                return JSONResponse(
                    content={
                        "response_action": "update",
                        "text": "❌ 承認処理でエラーが発生しました",
                        "blocks": [
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": f"❌ エラー: {str(e)}",
                                },
                            }
                        ],
                    }
                )

        elif action_id == "reject_task":
            # 差し戻しモーダルを開く
            await slack_service.open_rejection_modal(trigger_id, task_id)
            return JSONResponse(content={})

    elif interaction_type == "view_submission":
        # モーダル送信の処理
        view = payload["view"]
        callback_id = view["callback_id"]

        if callback_id == "create_task_modal":
            try:
                # タスク作成モーダルの処理
                values = view["state"]["values"]
                private_metadata = json.loads(view.get("private_metadata", "{}"))

                # リッチテキストを取得（変換しない）
                description_rich = values["description_block"]["description_input"]["rich_text_value"]
                # リッチテキストオブジェクトをそのまま渡す
                description_data = description_rich

                # 納期をdatetimeに変換
                due_date_unix = values["due_date_block"]["due_date_picker"]["selected_date_time"]
                due_date = datetime.fromtimestamp(due_date_unix)

                dto = CreateTaskRequestDto(
                    requester_slack_id=private_metadata["requester_id"],
                    assignee_slack_id=values["assignee_block"]["assignee_select"]["selected_option"]["value"],
                    title=values["title_block"]["title_input"]["value"],
                    description=description_data,  # リッチテキストデータを渡す
                    due_date=due_date,
                )

                await task_service.create_task_request(dto)

                return JSONResponse(
                    content={
                        "response_action": "clear",
                    }
                )
            except ValueError as e:
                # タスク作成エラーの場合
                return JSONResponse(
                    content={
                        "response_action": "errors",
                        "errors": {
                            "title_block": f"エラー: {str(e)}"
                        }
                    }
                )

        elif callback_id == "reject_task_modal":
            try:
                # 差し戻しモーダルの処理
                values = view["state"]["values"]
                private_metadata = json.loads(view.get("private_metadata", "{}"))
                task_id = private_metadata["task_id"]
                reason = values["reason_block"]["reason_input"]["value"]

                dto = TaskApprovalDto(
                    task_id=task_id,
                    action="reject",
                    rejection_reason=reason,
                )
                await task_service.handle_task_approval(dto)

                return JSONResponse(
                    content={
                        "response_action": "clear",
                    }
                )
            except ValueError as e:
                # エラーレスポンスを返す
                return JSONResponse(
                    content={
                        "response_action": "errors",
                        "errors": {
                            "reason_block": f"エラー: {str(e)}"
                        }
                    }
                )

    return JSONResponse(content={})


def _extract_plain_text_from_rich_text(rich_text: Dict[str, Any]) -> str:
    """リッチテキストからプレーンテキストを抽出"""
    text_parts = []

    for element in rich_text.get("elements", []):
        for item in element.get("elements", []):
            if item.get("type") == "text":
                text_parts.append(item.get("text", ""))
            elif item.get("type") == "link":
                text_parts.append(item.get("url", ""))

    return "".join(text_parts)