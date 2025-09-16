import json
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Form, Depends
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional
from src.application.services.task_service import TaskApplicationService
from src.application.dto.task_dto import CreateTaskRequestDto, TaskApprovalDto
from src.infrastructure.slack.slack_service import SlackService
from src.infrastructure.notion.dynamic_notion_service import DynamicNotionService
from src.infrastructure.repositories.notion_user_repository_impl import NotionUserRepositoryImpl
from src.infrastructure.repositories.slack_user_repository_impl import SlackUserRepositoryImpl
from src.application.services.user_mapping_service import UserMappingApplicationService
from src.domain.services.user_mapping_domain_service import UserMappingDomainService
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
    gemini_timeout_seconds: float = 30.0
    gemini_model: str = "gemini-2.5-flash"
    gemini_history_path: str = ".ai_conversations.json"

    class Config:
        env_file = ".env"


router = APIRouter(prefix="/slack", tags=["slack"])
settings = Settings()

# セッション情報を一時的に保存する辞書
modal_sessions = {}

print("🚀 Dynamic User Mapping System initialized!")
print(f"📊 Notion Database: {settings.notion_database_id}")
print("🔄 Using dynamic user search (no mapping files)")

# リポジトリとサービスのインスタンス化（DDD版DI）
task_repository = InMemoryTaskRepository()
user_repository = InMemoryUserRepository()
slack_service = SlackService(settings.slack_token, settings.slack_bot_token)

# 新しいDDD実装のサービス初期化
notion_user_repository = NotionUserRepositoryImpl(
    notion_token=settings.notion_token,
    default_database_id=settings.notion_database_id
)
slack_user_repository = SlackUserRepositoryImpl(slack_token=settings.slack_bot_token)
mapping_domain_service = UserMappingDomainService()
user_mapping_service = UserMappingApplicationService(
    notion_user_repository=notion_user_repository,
    slack_user_repository=slack_user_repository,
    mapping_domain_service=mapping_domain_service
)

# 動的Notionサービス（DDD ベース）
notion_service = DynamicNotionService(
    notion_token=settings.notion_token,
    database_id=settings.notion_database_id,
    user_mapping_service=user_mapping_service
)
ai_service = (
    TaskAIService(
        settings.gemini_api_key,
        timeout_seconds=settings.gemini_timeout_seconds,
        model_name=settings.gemini_model,
        history_storage_path=settings.gemini_history_path,
    )
    if settings.gemini_api_key
    else None
)

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
        # タスク作成モーダルを開く（即時ACK + バックグラウンドで続行）
        import asyncio
        asyncio.create_task(slack_service.open_task_modal(trigger_id, user_id))
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
    print(f"🔍 Interactive payload received: type={interaction_type}")

    if interaction_type == "block_actions":
        # ボタンアクションの処理
        action = payload["actions"][0]
        action_id = action["action_id"]
        task_id = action.get("value", "")
        trigger_id = payload["trigger_id"]
        view = payload.get("view", {})
        view_id = view.get("id")
        user_id = payload.get("user", {}).get("id", "unknown")
        
        print(f"🎯 Block action received: action_id={action_id}, user_id={user_id}")
        print(f"🔍 Available actions: {[a.get('action_id') for a in payload.get('actions', [])]}")

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
            # AI補完ボタンの処理: まず即時ACKし、その後非同期で更新
            print(f"🤖 AI補完ボタン押下: user_id={user_id}, action_id={action_id}")
            return await handle_ai_enhancement_async(payload, trigger_id, view_id, user_id)
        
        else:
            print(f"⚠️ Unknown action_id: {action_id}")
            return JSONResponse(content={"response_action": "errors", "errors": {"general": f"不明なアクション: {action_id}"}})

    elif interaction_type == "view_submission":
        # モーダル送信の処理
        view = payload["view"]
        callback_id = view["callback_id"]

        if callback_id == "create_task_modal":
            try:
                # タスク作成モーダルの処理（非同期化）
                values = view["state"]["values"]
                private_metadata = json.loads(view.get("private_metadata", "{}"))
                view_id = view.get("id")
                
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

                # 1) 即座にローディング画面を返す（3秒制限回避）
                loading_view = {
                    "type": "modal",
                    "callback_id": "task_creating_loading",
                    "title": {"type": "plain_text", "text": "タスク依頼作成中"},
                    "close": {"type": "plain_text", "text": "キャンセル"},
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": "⏳ *タスク依頼を作成しています...*\n\nしばらくお待ちください。"
                            }
                        }
                    ]
                }

                # 2) バックグラウンドでタスク作成処理を実行
                import asyncio
                
                async def run_task_creation():
                    try:
                        print("🔄 バックグラウンドタスク作成開始...")
                        await task_service.create_task_request(dto)
                        print("✅ タスク作成成功")
                        
                        # 成功時: 成功メッセージを表示
                        if view_id:
                            try:
                                success_view = {
                                    "type": "modal",
                                    "callback_id": "task_created_success",
                                    "title": {"type": "plain_text", "text": "タスク依頼完了"},
                                    "close": {"type": "plain_text", "text": "閉じる"},
                                    "blocks": [
                                        {
                                            "type": "section",
                                            "text": {
                                                "type": "mrkdwn",
                                                "text": f"✅ *タスク依頼が正常に送信されました*\n\n*件名:* {dto.title}\n*依頼先:* <@{dto.assignee_slack_id}>\n\n承認待ちです。結果はDMでお知らせします。"
                                            }
                                        }
                                    ]
                                }
                                slack_service.client.views_update(view_id=view_id, view=success_view)
                            except Exception as e:
                                print(f"⚠️ 成功メッセージ表示エラー: {e}")
                                
                    except Exception as e:
                        print(f"❌ タスク作成エラー: {e}")
                        
                        # 失敗時: 元のフォームに戻る（値を保持）
                        if view_id:
                            try:
                                # 元のフォーム構造を再構築
                                error_view = {
                                    "type": "modal",
                                    "callback_id": "create_task_modal",
                                    "title": {"type": "plain_text", "text": "タスク依頼作成"},
                                    "submit": {"type": "plain_text", "text": "作成"},
                                    "close": {"type": "plain_text", "text": "キャンセル"},
                                    "blocks": [
                                        {
                                            "type": "section",
                                            "text": {
                                                "type": "mrkdwn",
                                                "text": f"❌ *エラーが発生しました*\n{str(e)}\n\n下記のフォームで再度お試しください："
                                            }
                                        },
                                        # 元のフォームブロックを再構築（値を保持）
                                        *_rebuild_task_form_blocks_with_values(values, task_type, urgency)
                                    ],
                                    "private_metadata": json.dumps(private_metadata)
                                }
                                slack_service.client.views_update(view_id=view_id, view=error_view)
                            except Exception as update_error:
                                print(f"⚠️ エラーメッセージ表示失敗: {update_error}")

                # 非同期タスクを開始
                asyncio.create_task(run_task_creation())

                # 即座にローディング画面を返す
                return JSONResponse(
                    content={
                        "response_action": "update",
                        "view": loading_view
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
        
        else:
            print(f"⚠️ Unknown callback_id: {callback_id}")

    print(f"⚠️ Unhandled interaction_type: {interaction_type}")
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
    """[Deprecated] 互換用: 同期処理版（未使用）"""
    return JSONResponse(content={"response_action": "errors", "errors": {"ai_helper_section": "Deprecated handler"}}, status_code=200)


async def handle_ai_enhancement_async(payload: dict, trigger_id: str, view_id: Optional[str], user_id: str) -> JSONResponse:
    """AI補完処理（非同期化）: 3秒以内にACKして処理中表示 → 後でviews.update"""
    print(f"🚀 handle_ai_enhancement_async 開始: user_id={user_id}, view_id={view_id}")
    try:
        print(f"🔍 AI service check: ai_service={ai_service is not None}")
        if not ai_service:
            print("❌ AI service is None - GEMINI_API_KEY not configured")
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
        print("🔍 モーダル値取得中...")
        view = payload.get("view", {})
        values = view.get("state", {}).get("values", {})
        print(f"🔍 Values keys: {list(values.keys())}")
        
        # タイトルをチェック（必須条件）
        title = ""
        print("🔍 タイトル取得中...")
        if "title_block" in values:
            title = values["title_block"].get("title_input", {}).get("value", "")
        print(f"🔍 取得したタイトル: '{title}'")

        # titleがNoneの場合の処理
        if title is None:
            title = ""

        if not title.strip():
            print("❌ タイトルが空のためエラーを返します")
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
        print("🔍 TaskInfo作成中...")
        task_info = TaskInfo(title=title.strip())
        print(f"🔍 TaskInfo作成完了: {task_info.title}")
        
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
        
        # セッションIDの生成と管理
        pm_raw = view.get("private_metadata")
        pm = {}
        try:
            pm = json.loads(pm_raw) if pm_raw else {}
        except Exception:
            pm = {}

        # AI補完用の一意なセッションIDを生成（フォーム入力中のみ有効）
        # タイムスタンプを含めて一意性を確保
        import time
        session_id = f"ai_session_{user_id}_{int(time.time() * 1000)}"
        print(f"🔍 AI補完セッション開始: {session_id}")
        
        # 現在のフォーム値を全て保存
        current_values = {
            "assignee": None,
            "title": title,
            "due_date": None,
            "task_type": None,
            "urgency": None,
            "description": None
        }

        # 依頼先
        if "assignee_block" in values:
            assignee_data = values["assignee_block"].get("assignee_select", {}).get("selected_option")
            if assignee_data:
                current_values["assignee"] = assignee_data

        # 納期（Unix timestamp）
        if "due_date_block" in values:
            due_date_unix = values["due_date_block"].get("due_date_picker", {}).get("selected_date_time")
            if due_date_unix:
                current_values["due_date"] = due_date_unix

        # タスク種類
        if "task_type_block" in values:
            task_type_data = values["task_type_block"].get("task_type_select", {}).get("selected_option")
            if task_type_data:
                current_values["task_type"] = task_type_data

        # 緊急度
        if "urgency_block" in values:
            urgency_data = values["urgency_block"].get("urgency_select", {}).get("selected_option")
            if urgency_data:
                current_values["urgency"] = urgency_data

        # 内容（リッチテキスト）
        if "description_block" in values:
            current_desc = values["description_block"].get("description_input", {}).get("rich_text_value")
            if current_desc:
                current_values["description"] = current_desc

        # セッション情報を保存（private_metadataサイズ制限対策）
        requester_id = pm.get("requester_id")
        modal_sessions[session_id] = {
            "original_view": view,
            "current_values": current_values,
            "user_id": user_id,
            "trigger_id": trigger_id,
            "task_info": task_info,
            "view_id": view_id,
            "requester_id": requester_id,
        }

        # 1) まず即時ACK（処理中ビューに置換）
        print("🔍 処理中ビュー作成中...")
        processing_view = create_processing_view(session_id, title="AI補完 - 実行中", description="AIが内容を整理中です… しばらくお待ちください。")
        print("✅ 処理中ビュー作成完了")

        # 非同期でGemini処理 → 結果に応じてviews.update
        import asyncio
        print("🔍 非同期AI処理開始準備中...")

        async def run_analysis_and_update():
            try:
                print(f"🤖 AI分析処理開始: session_id={session_id}")
                # 新しいAI補完セッションを開始（古い会話履歴をクリア）
                print("🔍 AI履歴セッション開始中...")
                ai_service.history.start_new_session(session_id)
                print("🔍 AI分析実行中...")
                result = await ai_service.analyze_task_info(session_id, task_info)
                print(f"✅ AI分析完了: status={result.status}")
                if not view_id:
                    return
                if result.status == "insufficient_info":
                    new_view = create_additional_info_modal_view(session_id, result, requester_id)
                elif result.status == "ready_to_format":
                    modal_sessions[session_id]["generated_content"] = result.formatted_content
                    new_view = create_content_confirmation_modal_view(session_id, result, requester_id)
                else:
                    new_view = create_error_view(session_id, f"AI処理でエラーが発生しました: {result.message}")

                # private_metadata をマージして付与（requester_id維持 + session_id追加）
                base_pm = {}
                try:
                    base_pm = json.loads(view.get("private_metadata", "{}"))
                except Exception:
                    base_pm = {}
                base_pm["session_id"] = session_id
                new_view["private_metadata"] = json.dumps(base_pm)
                slack_service.client.views_update(view_id=view_id, view=new_view)
            except Exception as e:
                err_view = create_error_view(session_id, f"AI処理エラー: {str(e)}")
                try:
                    if view_id:
                        slack_service.client.views_update(view_id=view_id, view=err_view)
                except Exception:
                    pass

        print("🔍 非同期タスク作成中...")
        asyncio.create_task(run_analysis_and_update())
        print("✅ 非同期タスク作成完了")

        print("🔍 処理中ビューを返却中...")
        return JSONResponse(content={"response_action": "update", "view": processing_view}, status_code=200)
            
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
    """[Deprecated] 非同期化により未使用。views.update を使用してください。"""
    return JSONResponse(content={}, status_code=200)


async def show_content_confirmation_modal(trigger_id: str, session_id: str, result: AIAnalysisResult, original_view: dict) -> JSONResponse:
    """[Deprecated] 非同期化により未使用。views.update を使用してください。"""
    return JSONResponse(content={}, status_code=200)


async def handle_additional_info_submission(payload: dict) -> JSONResponse:
    """追加情報入力モーダルの送信処理（非同期化: 即時ACK→views.update）"""
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
        
        view = payload.get("view", {})
        values = view.get("state", {}).get("values", {})
        view_id = view.get("id")
        private_metadata = json.loads(view.get("private_metadata", "{}"))
        session_id = private_metadata.get("session_id")
        session_data = modal_sessions.get(session_id, {})
        requester_id = session_data.get("requester_id")
        additional_info = values["additional_info_block"]["additional_info_input"].get("value", "")

        print(f"🔍 追加情報入力セッション: {session_id}, 履歴数: {len(ai_service.history.get_conversation(session_id))}")

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

        # 即時ACK: 処理中ビュー
        processing_view = create_processing_view(session_id, title="AI補完 - 再分析中", description="いただいた情報で再分析しています…")

        # 背景でAI改良→views.update
        import asyncio

        async def run_refine_and_update():
            try:
                result = await ai_service.refine_content(session_id, additional_info)
                if result.status == "insufficient_info":
                    new_view = create_additional_info_modal_view(session_id, result, requester_id)
                elif result.status == "ready_to_format":
                    modal_sessions[session_id]["generated_content"] = result.formatted_content
                    new_view = create_content_confirmation_modal_view(session_id, result, requester_id)
                else:
                    new_view = create_error_view(session_id, f"AI処理エラー: {result.message}")
                # private_metadata をマージ（requester_id維持）
                pm = {"session_id": session_id}
                if requester_id:
                    pm["requester_id"] = requester_id
                new_view["private_metadata"] = json.dumps(pm)
                if view_id:
                    slack_service.client.views_update(view_id=view_id, view=new_view)
            except Exception as e:
                err_view = create_error_view(session_id, f"AI処理エラー: {str(e)}")
                try:
                    if view_id:
                        slack_service.client.views_update(view_id=view_id, view=err_view)
                except Exception:
                    pass

        asyncio.create_task(run_refine_and_update())

        return JSONResponse(content={"response_action": "update", "view": processing_view}, status_code=200)
            
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
    """内容確認モーダルの処理（非同期化）"""
    try:
        view = payload.get("view", {})
        view_id = view.get("id")
        values = view.get("state", {}).get("values", {})
        private_metadata = json.loads(view.get("private_metadata", "{}"))
        
        session_id = private_metadata.get("session_id")
        session_data = modal_sessions.get(session_id, {})
        generated_content = session_data.get("generated_content")
        requester_id = session_data.get("requester_id")

        print(f"🔍 内容確認セッション: {session_id}, 履歴数: {len(ai_service.history.get_conversation(session_id)) if ai_service else 0}")
        
        # フィードバックがあるかチェック
        feedback = ""
        fb_block = values.get("feedback_block")
        if fb_block and "feedback_input" in fb_block:
            raw = fb_block["feedback_input"].get("value")
            feedback = (raw or "").strip()
        
        # 即時ACK: 処理中ビュー
        processing_view = create_processing_view(session_id, title="AI補完 - 反映中", description="内容を反映しています…")

        import asyncio

        async def run_feedback_apply():
            try:
                if feedback:
                    if not ai_service:
                        new_view = create_error_view(session_id, "AI機能が利用できません。")
                    else:
                        result = await ai_service.refine_content(session_id, feedback)
                        if result.status == "insufficient_info":
                            # 追加質問に戻す
                            new_view = create_additional_info_modal_view(session_id, result, requester_id)
                        elif result.status == "ready_to_format":
                            modal_sessions.setdefault(session_id, {})
                            modal_sessions[session_id]["generated_content"] = result.formatted_content
                            new_view = create_content_confirmation_modal_view(session_id, result, requester_id)
                        else:
                            new_view = create_error_view(session_id, f"AI処理エラー: {result.message}")
                else:
                    # フィードバックなし - 元のモーダルに戻って内容を反映
                    original_view = session_data.get("original_view")
                    current_values = session_data.get("current_values", {})

                    if original_view and generated_content:
                        # views.updateに必要なプロパティのみを抽出
                        clean_view = {
                            "type": original_view.get("type", "modal"),
                            "callback_id": original_view.get("callback_id", "create_task_modal"),
                            "title": original_view.get("title"),
                            "submit": original_view.get("submit"),
                            "close": original_view.get("close"),
                            "blocks": original_view.get("blocks", [])
                        }

                        # 保存した値を各ブロックに復元
                        if "blocks" in clean_view:
                            for block in clean_view["blocks"]:
                                block_id = block.get("block_id")

                                # 依頼先
                                if block_id == "assignee_block" and current_values.get("assignee"):
                                    if "element" in block:
                                        block["element"]["initial_option"] = current_values["assignee"]

                                # タイトル
                                elif block_id == "title_block" and current_values.get("title"):
                                    if "element" in block:
                                        block["element"]["initial_value"] = current_values["title"]

                                # 納期
                                elif block_id == "due_date_block" and current_values.get("due_date"):
                                    if "element" in block:
                                        block["element"]["initial_date_time"] = current_values["due_date"]

                                # タスク種類
                                elif block_id == "task_type_block" and current_values.get("task_type"):
                                    if "element" in block:
                                        block["element"]["initial_option"] = current_values["task_type"]

                                # 緊急度
                                elif block_id == "urgency_block" and current_values.get("urgency"):
                                    if "element" in block:
                                        block["element"]["initial_option"] = current_values["urgency"]

                                # 内容詳細（AI生成内容を設定）
                                elif block_id == "description_block":
                                    if "element" in block:
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
                        new_view = clean_view
                    else:
                        new_view = create_error_view(session_id, "AI生成内容が見つかりませんでした。最初からやり直してください。")

                # private_metadata をマージ（requester_id維持）
                pm = {"session_id": session_id}
                if requester_id:
                    pm["requester_id"] = requester_id
                new_view["private_metadata"] = json.dumps(pm)
                if view_id:
                    slack_service.client.views_update(view_id=view_id, view=new_view)
            except Exception as e:
                try:
                    if view_id:
                        slack_service.client.views_update(view_id=view_id, view=create_error_view(session_id, f"処理エラー: {str(e)}"))
                except Exception:
                    pass

        asyncio.create_task(run_feedback_apply())

        return JSONResponse(content={"response_action": "update", "view": processing_view}, status_code=200)
            
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


def create_additional_info_modal_view(session_id: str, result: AIAnalysisResult, requester_id: str = None) -> dict:
    """追加情報モーダルビューを作成"""
    suggestions_text = "\n".join(f"• {s}" for s in result.suggestions) if result.suggestions else ""

    # private_metadataを構築
    pm = {"session_id": session_id}
    if requester_id:
        pm["requester_id"] = requester_id

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
        "private_metadata": json.dumps(pm)
    }


def create_content_confirmation_modal_view(session_id: str, result: AIAnalysisResult, requester_id: str = None) -> dict:
    """内容確認モーダルビューを作成"""
    content_text = (result.formatted_content or result.message or "").strip()

    # private_metadataを構築
    pm = {"session_id": session_id}
    if requester_id:
        pm["requester_id"] = requester_id

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
                    "text": f"```{content_text}```"
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
        "private_metadata": json.dumps(pm)
    }


def create_processing_view(session_id: str, title: str, description: str) -> dict:
    """処理中プレースホルダービュー（即時ACK用）"""
    return {
        "type": "modal",
        "callback_id": "ai_processing_modal",
        "title": {"type": "plain_text", "text": title[:24] or "処理中"},
        "close": {"type": "plain_text", "text": "キャンセル"},
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"⏳ {description}"}}
        ],
        "private_metadata": json.dumps({"session_id": session_id})
    }


def create_error_view(session_id: str, message: str) -> dict:
    """エラービュー"""
    return {
        "type": "modal",
        "callback_id": "ai_error_modal",
        "title": {"type": "plain_text", "text": "エラー"},
        "close": {"type": "plain_text", "text": "閉じる"},
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"❌ {message}"}}
        ],
        "private_metadata": json.dumps({"session_id": session_id})
    }


def _rebuild_task_form_blocks_with_values(values: dict, task_type: str, urgency: str) -> list:
    """エラー時に値を保持したタスクフォームブロックを再構築"""
    
    # 依頼先は再選択が必要（ユーザーリスト再取得が複雑なため）
    assignee_initial_option = None
    
    # タイトルの初期値
    title_initial_value = ""
    if "title_block" in values and "title_input" in values["title_block"]:
        title_initial_value = values["title_block"]["title_input"].get("value", "")
    
    # 納期の初期値
    due_date_initial = None
    if "due_date_block" in values and "due_date_picker" in values["due_date_block"]:
        due_date_initial = values["due_date_block"]["due_date_picker"].get("selected_date_time")
    
    # 内容詳細の初期値
    description_initial = None
    if "description_block" in values and "description_input" in values["description_block"]:
        description_rich = values["description_block"]["description_input"].get("rich_text_value")
        if description_rich:
            description_initial = description_rich

    blocks = [
        {
            "type": "input",
            "block_id": "assignee_block",
            "element": {
                "type": "static_select",
                "placeholder": {"type": "plain_text", "text": "依頼先を再選択してください"},
                "options": [{"text": {"type": "plain_text", "text": "ユーザーリストを読み込み中..."}, "value": "loading"}],
                "action_id": "assignee_select",
            },
            "label": {"type": "plain_text", "text": "依頼先"},
        },
        {
            "type": "input",
            "block_id": "title_block",
            "element": {
                "type": "plain_text_input",
                "action_id": "title_input",
                "placeholder": {"type": "plain_text", "text": "タスクの件名を入力"},
            },
            "label": {"type": "plain_text", "text": "件名"},
        },
        {
            "type": "input",
            "block_id": "due_date_block",
            "element": {
                "type": "datetimepicker",
                "action_id": "due_date_picker"
            },
            "label": {"type": "plain_text", "text": "納期"},
        },
        {
            "type": "input",
            "block_id": "task_type_block",
            "element": {
                "type": "static_select",
                "placeholder": {"type": "plain_text", "text": "タスク種類を選択"},
                "options": [
                    {"text": {"type": "plain_text", "text": "フリーランス関係"}, "value": "フリーランス関係"},
                    {"text": {"type": "plain_text", "text": "モノテック関連"}, "value": "モノテック関連"},
                    {"text": {"type": "plain_text", "text": "社内タスク"}, "value": "社内タスク"},
                    {"text": {"type": "plain_text", "text": "HH関連"}, "value": "HH関連"},
                    {"text": {"type": "plain_text", "text": "Sales関連"}, "value": "Sales関連"},
                    {"text": {"type": "plain_text", "text": "PL関連"}, "value": "PL関連"},
                ],
                "action_id": "task_type_select",
            },
            "label": {"type": "plain_text", "text": "タスク種類"},
        },
        {
            "type": "input",
            "block_id": "urgency_block",
            "element": {
                "type": "static_select",
                "placeholder": {"type": "plain_text", "text": "緊急度を選択"},
                "options": [
                    {"text": {"type": "plain_text", "text": "ノンコア社内タスク"}, "value": "ノンコア社内タスク"},
                    {"text": {"type": "plain_text", "text": "1週間以内"}, "value": "1週間以内"},
                    {"text": {"type": "plain_text", "text": "最重要"}, "value": "最重要"},
                ],
                "action_id": "urgency_select",
            },
            "label": {"type": "plain_text", "text": "緊急度"},
        },
        {
            "type": "section",
            "block_id": "ai_helper_section",
            "text": {"type": "mrkdwn", "text": "🤖 *AI補完機能*\nタスクの詳細内容をAIに生成・改良してもらえます"},
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "AI補完", "emoji": True},
                "value": "ai_enhance",
                "action_id": "ai_enhance_button",
            },
        },
        {
            "type": "input",
            "block_id": "description_block",
            "element": {
                "type": "rich_text_input",
                "action_id": "description_input",
                "placeholder": {"type": "plain_text", "text": "タスクの詳細を入力（任意）"},
            },
            "label": {"type": "plain_text", "text": "内容詳細"},
            "optional": True,
        },
    ]
    
    # 初期値を設定
    if assignee_initial_option:
        blocks[0]["element"]["initial_option"] = assignee_initial_option
    if title_initial_value:
        blocks[1]["element"]["initial_value"] = title_initial_value
    if due_date_initial:
        blocks[2]["element"]["initial_date_time"] = due_date_initial
    if task_type:
        blocks[3]["element"]["initial_option"] = {"text": {"type": "plain_text", "text": task_type}, "value": task_type}
    if urgency:
        blocks[4]["element"]["initial_option"] = {"text": {"type": "plain_text", "text": urgency}, "value": urgency}
    if description_initial:
        blocks[7]["element"]["initial_value"] = description_initial
    
    return blocks
