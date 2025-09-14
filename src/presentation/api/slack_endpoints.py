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
from src.services.ai_service import TaskAIService, TaskInfo, AIAnalysisResult
from src.utils.text_converter import convert_rich_text_to_plain_text
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    slack_token: str = ""
    slack_bot_token: str = ""
    slack_signing_secret: str = ""
    notion_token: str = ""
    notion_database_id: str = ""
    mapping_database_id: str = ""
    gcs_bucket_name: str = ""
    google_application_credentials: str = ""
    gemini_api_key: str = ""

    class Config:
        env_file = ".env"


router = APIRouter(prefix="/slack", tags=["slack"])
settings = Settings()

# セッション情報を一時的に保存する辞書
modal_sessions = {}

# リポジトリとサービスのインスタンス化（簡易的なDI）
task_repository = InMemoryTaskRepository()
user_repository = InMemoryUserRepository()
slack_service = SlackService(settings.slack_token, settings.slack_bot_token)
notion_service = NotionService(settings.notion_token, settings.notion_database_id)
ai_service = TaskAIService(settings.gemini_api_key) if settings.gemini_api_key else None

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
        
        elif action_id == "ai_enhance_button":
            # AI補完ボタンの処理
            return await handle_ai_enhancement(payload, trigger_id)

    elif interaction_type == "view_submission":
        # モーダル送信の処理
        view = payload["view"]
        callback_id = view["callback_id"]

        if callback_id == "create_task_modal":
            try:
                # タスク作成モーダルの処理
                values = view["state"]["values"]
                private_metadata = json.loads(view.get("private_metadata", "{}"))
                
                # デバッグ: 受信したデータ構造を確認
                print(f"🔍 Modal values keys: {list(values.keys())}")
                for key, value in values.items():
                    print(f"  {key}: {list(value.keys())}")

                # 新しいフィールドを取得（存在しない場合はデフォルト値）
                task_type = "社内タスク"  # デフォルト値
                if "task_type_block" in values and "task_type_select" in values["task_type_block"]:
                    task_type_data = values["task_type_block"]["task_type_select"].get("selected_option")
                    if task_type_data:
                        task_type = task_type_data["value"]
                
                urgency = "1週間以内"  # デフォルト値
                if "urgency_block" in values and "urgency_select" in values["urgency_block"]:
                    urgency_data = values["urgency_block"]["urgency_select"].get("selected_option")
                    if urgency_data:
                        urgency = urgency_data["value"]
                
                print(f"🎯 取得したフィールド: task_type={task_type}, urgency={urgency}")
                
                # リッチテキストを取得（オプショナル）
                description_data = None
                if "description_block" in values and values["description_block"]["description_input"].get("rich_text_value"):
                    description_rich = values["description_block"]["description_input"]["rich_text_value"]
                    description_data = description_rich

                # 納期をdatetimeに変換
                due_date_unix = values["due_date_block"]["due_date_picker"]["selected_date_time"]
                due_date = datetime.fromtimestamp(due_date_unix)

                dto = CreateTaskRequestDto(
                    requester_slack_id=private_metadata["requester_id"],
                    assignee_slack_id=values["assignee_block"]["assignee_select"]["selected_option"]["value"],
                    title=values["title_block"]["title_input"]["value"],
                    description=description_data,  # リッチテキストデータを渡す（オプショナル）
                    due_date=due_date,
                    task_type=task_type,
                    urgency=urgency,
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
        
        elif callback_id == "ai_additional_info_modal":
            # 追加情報入力モーダルの処理
            return await handle_additional_info_submission(payload)
            
        elif callback_id == "ai_content_confirmation_modal":
            # 内容確認モーダルの処理
            return await handle_content_confirmation(payload)

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


async def handle_ai_enhancement(payload: dict, trigger_id: str) -> JSONResponse:
    """AI補完処理"""
    try:
        if not ai_service:
            return JSONResponse(
                content={
                    "response_action": "errors",
                    "errors": {
                        "ai_helper_section": "AI機能が利用できません。GEMINI_API_KEYを設定してください。"
                    }
                },
                status_code=200
            )
        
        # 現在のモーダルの値を取得
        view = payload.get("view", {})
        values = view.get("state", {}).get("values", {})
        
        # タイトルをチェック（必須条件）
        title = ""
        if "title_block" in values:
            title = values["title_block"].get("title_input", {}).get("value", "")
        
        if not title.strip():
            return JSONResponse(
                content={
                    "response_action": "errors", 
                    "errors": {
                        "title_block": "AI補完を使用するには、まずタイトルを入力してください。"
                    }
                },
                status_code=200
            )
        
        # 現在のタスク情報を収集
        task_info = TaskInfo(title=title.strip())
        
        # タスク種類
        if "task_type_block" in values:
            task_type_data = values["task_type_block"].get("task_type_select", {}).get("selected_option")
            if task_type_data:
                task_info.task_type = task_type_data["value"]
        
        # 緊急度
        if "urgency_block" in values:
            urgency_data = values["urgency_block"].get("urgency_select", {}).get("selected_option")
            if urgency_data:
                task_info.urgency = urgency_data["value"]
        
        # 納期
        if "due_date_block" in values:
            due_date_unix = values["due_date_block"].get("due_date_picker", {}).get("selected_date_time")
            if due_date_unix:
                due_date = datetime.fromtimestamp(due_date_unix)
                task_info.due_date = due_date.strftime('%Y年%m月%d日 %H:%M')
        
        # 現在の内容
        if "description_block" in values:
            current_desc = values["description_block"].get("description_input", {}).get("rich_text_value")
            if current_desc:
                task_info.current_description = convert_rich_text_to_plain_text(current_desc)
        
        # セッションID（ユーザーID + trigger_id の一部を使用）
        user_id = payload.get("user", {}).get("id", "unknown")
        session_id = f"{user_id}_{trigger_id[-8:]}"
        
        # セッション情報を保存（private_metadataサイズ制限対策）
        modal_sessions[session_id] = {
            "original_view": view,
            "user_id": user_id,
            "trigger_id": trigger_id,
            "task_info": task_info
        }
        
        # AI分析を実行
        result = ai_service.analyze_task_info(session_id, task_info)
        
        if result.status == "insufficient_info":
            # 情報不足の場合 - 追加情報入力モーダルを表示
            return await show_additional_info_modal(trigger_id, session_id, result, view)
            
        elif result.status == "ready_to_format":
            # 整形済みの場合 - セッションにコンテンツを保存してから確認モーダルを表示
            modal_sessions[session_id]["generated_content"] = result.formatted_content
            return await show_content_confirmation_modal(trigger_id, session_id, result, view)
            
        else:
            # エラーの場合
            return JSONResponse(
                content={
                    "response_action": "errors",
                    "errors": {
                        "ai_helper_section": f"AI処理でエラーが発生しました: {result.message}"
                    }
                },
                status_code=200
            )
            
    except Exception as e:
        error_msg = str(e)
        print(f"❌ AI enhancement error: {e}")
        
        # trigger_id期限切れや特定のSlack APIエラーの場合
        if any(keyword in error_msg.lower() for keyword in ["expired_trigger_id", "trigger_expired", "expired"]):
            return JSONResponse(
                content={
                    "response_action": "errors",
                    "errors": {
                        "ai_helper_section": "⏰ AI処理に時間がかかりすぎました。処理を高速化してもう一度お試しください。"
                    }
                },
                status_code=200
            )
        
        return JSONResponse(
            content={
                "response_action": "errors",
                "errors": {
                    "ai_helper_section": f"AI処理でエラーが発生しました: {error_msg[:100]}..."
                }
            },
            status_code=200
        )


async def show_additional_info_modal(trigger_id: str, session_id: str, result: AIAnalysisResult, original_view: dict) -> JSONResponse:
    """追加情報入力モーダルを表示"""
    suggestions_text = "\n".join(f"• {s}" for s in result.suggestions) if result.suggestions else ""
    
    additional_info_modal = {
        "type": "modal",
        "callback_id": "ai_additional_info_modal",
        "title": {
            "type": "plain_text",
            "text": "AI補完 - 追加情報"
        },
        "submit": {
            "type": "plain_text",
            "text": "分析実行"
        },
        "close": {
            "type": "plain_text", 
            "text": "キャンセル"
        },
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"🤖 *AI分析結果*\n{result.message}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*必要な追加情報:*\n{suggestions_text}"
                }
            },
            {
                "type": "input",
                "block_id": "additional_info_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "additional_info_input",
                    "multiline": True,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "上記の質問に対する回答を入力してください..."
                    }
                },
                "label": {
                    "type": "plain_text",
                    "text": "追加情報"
                }
            }
        ],
        "private_metadata": json.dumps({
            "session_id": session_id
        })
    }
    
    # views.push APIを使用してモーダルをプッシュ
    response = slack_service.client.views_push(
        trigger_id=trigger_id,
        view=additional_info_modal
    )
    
    return JSONResponse(content={}, status_code=200)


async def show_content_confirmation_modal(trigger_id: str, session_id: str, result: AIAnalysisResult, original_view: dict) -> JSONResponse:
    """生成されたコンテンツの確認モーダルを表示"""
    confirmation_modal = {
        "type": "modal",
        "callback_id": "ai_content_confirmation_modal", 
        "title": {
            "type": "plain_text",
            "text": "AI補完 - 内容確認"
        },
        "submit": {
            "type": "plain_text",
            "text": "採用する"
        },
        "close": {
            "type": "plain_text",
            "text": "キャンセル"
        },
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn", 
                    "text": "🤖 *AI生成されたタスク内容*\n以下の内容でよろしければ「採用する」をクリックしてください。"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"```{result.formatted_content}```"
                }
            },
            {
                "type": "input",
                "block_id": "feedback_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "feedback_input",
                    "multiline": True,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "修正点があれば入力してください（任意）"
                    }
                },
                "label": {
                    "type": "plain_text", 
                    "text": "フィードバック（任意）"
                },
                "optional": True
            }
        ],
        "private_metadata": json.dumps({
            "session_id": session_id
        })
    }
    
    # views.push APIを使用
    response = slack_service.client.views_push(
        trigger_id=trigger_id,
        view=confirmation_modal
    )
    
    return JSONResponse(content={}, status_code=200)


async def handle_additional_info_submission(payload: dict) -> JSONResponse:
    """追加情報入力モーダルの送信処理"""
    try:
        if not ai_service:
            return JSONResponse(
                content={
                    "response_action": "errors",
                    "errors": {
                        "additional_info_block": "AI機能が利用できません。"
                    }
                },
                status_code=200
            )
        
        values = payload["view"]["state"]["values"]
        private_metadata = json.loads(payload["view"].get("private_metadata", "{}"))
        
        session_id = private_metadata.get("session_id")
        additional_info = values["additional_info_block"]["additional_info_input"]["value"]
        
        if not additional_info.strip():
            return JSONResponse(
                content={
                    "response_action": "errors",
                    "errors": {
                        "additional_info_block": "追加情報を入力してください。"
                    }
                },
                status_code=200
            )
        
        # AI改良を実行
        result = ai_service.refine_content(session_id, additional_info)
        
        if result.status == "insufficient_info":
            # まだ情報不足の場合
            return JSONResponse(
                content={
                    "response_action": "update",
                    "view": create_additional_info_modal_view(session_id, result)
                },
                status_code=200
            )
        elif result.status == "ready_to_format":
            # 整形完了の場合 - セッションにコンテンツを保存してから確認モーダルに移行
            modal_sessions[session_id]["generated_content"] = result.formatted_content
            return JSONResponse(
                content={
                    "response_action": "update",
                    "view": create_content_confirmation_modal_view(session_id, result)
                },
                status_code=200
            )
        else:
            # エラーの場合
            return JSONResponse(
                content={
                    "response_action": "errors",
                    "errors": {
                        "additional_info_block": f"AI処理エラー: {result.message}"
                    }
                },
                status_code=200
            )
            
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Additional info submission error: {e}")
        
        # APIエラーに対する適切なメッセージ
        if any(keyword in error_msg.lower() for keyword in ["timeout", "expired", "overloaded"]):
            error_text = "⏰ AI処理に時間がかかりました。もう一度お試しください。"
        else:
            error_text = f"処理エラー: {error_msg[:100]}..."
            
        return JSONResponse(
            content={
                "response_action": "errors",
                "errors": {
                    "additional_info_block": error_text
                }
            },
            status_code=200
        )


async def handle_content_confirmation(payload: dict) -> JSONResponse:
    """内容確認モーダルの処理"""
    try:
        values = payload["view"]["state"]["values"]
        private_metadata = json.loads(payload["view"].get("private_metadata", "{}"))
        
        session_id = private_metadata.get("session_id")
        session_data = modal_sessions.get(session_id, {})
        generated_content = session_data.get("generated_content")
        
        # フィードバックがあるかチェック
        feedback = ""
        if "feedback_block" in values:
            feedback = values["feedback_block"]["feedback_input"].get("value", "").strip()
        
        if feedback:
            # フィードバックがある場合は改良を実行
            if not ai_service:
                return JSONResponse(
                    content={
                        "response_action": "errors",
                        "errors": {
                            "feedback_block": "AI機能が利用できません。"
                        }
                    },
                    status_code=200
                )
            
            result = ai_service.refine_content(session_id, feedback)
            
            # セッションに新しいコンテンツを保存
            modal_sessions[session_id]["generated_content"] = result.formatted_content
            
            # 新しい確認モーダルを表示
            return JSONResponse(
                content={
                    "response_action": "update",
                    "view": create_content_confirmation_modal_view(session_id, result)
                },
                status_code=200
            )
        else:
            # フィードバックなし - 元のモーダルに戻って内容を反映
            original_view = session_data.get("original_view")
            if original_view and generated_content:
                # 元のモーダルの説明欄にAI生成内容を設定
                if "blocks" in original_view:
                    for block in original_view["blocks"]:
                        if block.get("block_id") == "description_block":
                            block["element"]["initial_value"] = {
                                "type": "rich_text",
                                "elements": [
                                    {
                                        "type": "rich_text_section",
                                        "elements": [
                                            {
                                                "type": "text",
                                                "text": generated_content
                                            }
                                        ]
                                    }
                                ]
                            }
                            break
                
                return JSONResponse(
                    content={
                        "response_action": "update",
                        "view": original_view
                    },
                    status_code=200
                )
            else:
                return JSONResponse(
                    content={
                        "response_action": "clear"
                    },
                    status_code=200
                )
            
    except Exception as e:
        print(f"❌ Content confirmation error: {e}")
        return JSONResponse(
            content={
                "response_action": "errors",
                "errors": {
                    "feedback_block": f"処理エラー: {str(e)}"
                }
            },
            status_code=200
        )


def create_additional_info_modal_view(session_id: str, result: AIAnalysisResult) -> dict:
    """追加情報モーダルビューを作成"""
    suggestions_text = "\n".join(f"• {s}" for s in result.suggestions) if result.suggestions else ""
    
    return {
        "type": "modal",
        "callback_id": "ai_additional_info_modal",
        "title": {
            "type": "plain_text",
            "text": "AI補完 - 追加情報"
        },
        "submit": {
            "type": "plain_text",
            "text": "分析実行"
        },
        "close": {
            "type": "plain_text",
            "text": "キャンセル"
        },
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"🤖 *AI分析結果*\n{result.message}"
                }
            },
            {
                "type": "section", 
                "text": {
                    "type": "mrkdwn",
                    "text": f"*必要な追加情報:*\n{suggestions_text}"
                }
            },
            {
                "type": "input",
                "block_id": "additional_info_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "additional_info_input",
                    "multiline": True,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "上記の質問に対する回答を入力してください..."
                    }
                },
                "label": {
                    "type": "plain_text",
                    "text": "追加情報"
                }
            }
        ],
        "private_metadata": json.dumps({
            "session_id": session_id
        })
    }


def create_content_confirmation_modal_view(session_id: str, result: AIAnalysisResult) -> dict:
    """内容確認モーダルビューを作成"""
    return {
        "type": "modal",
        "callback_id": "ai_content_confirmation_modal",
        "title": {
            "type": "plain_text", 
            "text": "AI補完 - 内容確認"
        },
        "submit": {
            "type": "plain_text",
            "text": "採用する"
        },
        "close": {
            "type": "plain_text",
            "text": "キャンセル"
        },
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "🤖 *AI生成されたタスク内容*\n以下の内容でよろしければ「採用する」をクリックしてください。"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"```{result.formatted_content}```"
                }
            },
            {
                "type": "input",
                "block_id": "feedback_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "feedback_input",
                    "multiline": True,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "修正点があれば入力してください（任意）"
                    }
                },
                "label": {
                    "type": "plain_text",
                    "text": "フィードバック（任意）"
                },
                "optional": True
            }
        ],
        "private_metadata": json.dumps({
            "session_id": session_id
        })
    }