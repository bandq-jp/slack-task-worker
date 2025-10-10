import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi.responses import JSONResponse
from zoneinfo import ZoneInfo

from src.domain.value_objects.email import Email
from src.infrastructure.notion.dynamic_notion_service import NotionTaskSnapshot
from src.presentation.api.slack.context import SlackDependencies

JST = ZoneInfo("Asia/Tokyo")


def _format_due(dt: Optional[datetime]) -> str:
    if not dt:
        return "未設定"
    if dt.tzinfo:
        localized = dt.astimezone(JST)
    else:
        localized = dt.replace(tzinfo=timezone.utc).astimezone(JST)
    return localized.strftime("%Y-%m-%d %H:%M")


def _replace_actions_with_context(blocks: Optional[list], text: str) -> Optional[list]:
    if not blocks:
        return None
    updated_blocks: list = []
    replaced = False
    for block in blocks:
        if not replaced and isinstance(block, dict) and block.get("type") == "actions":
            updated_blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": text}],
            })
            replaced = True
        else:
            updated_blocks.append(block)
    if not replaced:
        updated_blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": text}],
        })
    return updated_blocks


async def handle_extension_request_submission(
    payload: Dict[str, Any],
    dependencies: SlackDependencies,
    *,
    view_id: str,
    private_metadata: str,
    requested_due: datetime,
    reason: str,
    page_id: str,
    snapshot: NotionTaskSnapshot,
    assignee_slack_id: Optional[str],
    requester_slack_id: Optional[str],
) -> JSONResponse:
    settings = dependencies.settings
    slack_service = dependencies.slack_service
    notion_service = dependencies.notion_service
    task_concurrency = dependencies.task_concurrency

    loading_view = {
        "type": "modal",
        "callback_id": "extension_request_processing",
        "title": {"type": "plain_text", "text": f"延期申請{settings.app_name_suffix}"[:24]},
        "close": {"type": "plain_text", "text": "閉じる"},
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "⏳ 延期申請を送信しています。しばらくお待ちください。",
                },
            }
        ],
        "private_metadata": private_metadata,
    }

    async def run_extension_submission() -> None:
        try:
            async with task_concurrency.guard(page_id):
                await notion_service.set_extension_request(page_id, requested_due, reason)
                await notion_service.record_audit_log(
                    task_page_id=page_id,
                    event_type="延期申請",
                    detail=f"{_format_due(snapshot.due_date)} → {_format_due(requested_due)}\n理由: {reason}",
                    actor_email=snapshot.assignee_email,
                )

                target_requester_slack_id = requester_slack_id
                if not target_requester_slack_id and snapshot.requester_email:
                    try:
                        slack_user = await dependencies.slack_user_repository.find_by_email(
                            Email(snapshot.requester_email)
                        )
                        if slack_user:
                            target_requester_slack_id = str(slack_user.user_id)
                    except Exception as lookup_error:
                        print(f"⚠️ Failed to lookup requester Slack ID during extension submission: {lookup_error}")

                if target_requester_slack_id:
                    try:
                        await slack_service.send_extension_request_to_requester(
                            requester_slack_id=target_requester_slack_id,
                            assignee_slack_id=assignee_slack_id or "",
                            snapshot=snapshot,
                            requested_due=requested_due,
                            reason=reason,
                        )
                    except Exception as send_error:
                        print(f"⚠️ Failed to send extension approval request: {send_error}")
                else:
                    print("⚠️ Requester Slack ID not resolved. Extension approval request not delivered.")

                if assignee_slack_id:
                    await slack_service.notify_extension_request_submitted(
                        assignee_slack_id=assignee_slack_id,
                        requested_due=requested_due,
                        thread_channel=snapshot.assignee_thread_channel,
                        thread_ts=snapshot.assignee_thread_ts,
                    )

            success_message = (
                f"延期申請を送信しました。\n"
                f"希望納期: {_format_due(requested_due)}\n"
                f"理由: {reason}"
            )
            slack_service.update_modal_message(
                view_id=view_id,
                title=f"延期申請完了{settings.app_name_suffix}",
                message=success_message,
                emoji="✅",
                close_text="閉じる",
            )
        except Exception as error:
            print(f"⚠️ Extension request processing failed: {error}")
            slack_service.update_modal_message(
                view_id=view_id,
                title=f"延期申請エラー{settings.app_name_suffix}",
                message=f"エラーが発生しました: {str(error)}",
                emoji="⚠️",
                close_text="閉じる",
            )

    asyncio.create_task(run_extension_submission())
    return JSONResponse(content={"response_action": "update", "view": loading_view})


async def handle_approve_extension_action(
    payload: Dict[str, Any],
    dependencies: SlackDependencies,
    *,
    trigger_id: str,
    page_id: Optional[str],
    assignee_slack_id: Optional[str],
    requester_slack_id: Optional[str],
    channel_id: Optional[str],
    message_ts: Optional[str],
    message_blocks: Optional[list],
) -> JSONResponse:
    if not page_id:
        return JSONResponse(content={})

    slack_service = dependencies.slack_service
    notion_service = dependencies.notion_service
    task_concurrency = dependencies.task_concurrency
    task_metrics_service = dependencies.task_metrics_service
    settings = dependencies.settings

    modal_id = slack_service.open_processing_modal(
        trigger_id=trigger_id,
        title=f"延期承認処理{settings.app_name_suffix}",
        message="延期申請を承認しています。しばらくお待ちください。",
    )

    async def run_extension_approval() -> None:
        try:
            missing_request = False
            approved_due: Optional[datetime] = None
            snapshot: Optional[NotionTaskSnapshot] = None
            refreshed_snapshot: Optional[NotionTaskSnapshot] = None
            actor_slack_id = payload.get("user", {}).get("id")

            async with task_concurrency.guard(page_id):
                snapshot = await notion_service.get_task_snapshot(page_id)
                if not snapshot or not snapshot.extension_requested_due:
                    missing_request = True
                else:
                    approved_due = snapshot.extension_requested_due
                    previous_due = snapshot.due_date

                    await notion_service.approve_extension(page_id, approved_due)

                    actor_email = None
                    if actor_slack_id:
                        user_info = await slack_service.get_user_info(actor_slack_id)
                        actor_email = user_info.get("profile", {}).get("email") if user_info else None

                    detail = (
                        f"延期承認: {_format_due(previous_due)} → {_format_due(approved_due)}"
                        if previous_due
                        else f"延期承認: 新期日 {_format_due(approved_due)}"
                    )
                    await notion_service.record_audit_log(
                        task_page_id=page_id,
                        event_type="延期承認",
                        detail=detail,
                        actor_email=actor_email,
                    )

                    if task_metrics_service:
                        refreshed_snapshot = await notion_service.get_task_snapshot(page_id)
                        target_snapshot = refreshed_snapshot or snapshot
                        await task_metrics_service.sync_snapshot(
                            target_snapshot,
                            reminder_stage=target_snapshot.reminder_stage,
                        )
                        await task_metrics_service.refresh_assignee_summaries()

            if missing_request:
                slack_service.update_modal_message(
                    view_id=modal_id,
                    title=f"延期承認エラー{settings.app_name_suffix}",
                    message="延期申請が見つからないため、承認できませんでした。",
                    emoji="⚠️",
                    close_text="閉じる",
                )
                return

            display_snapshot = refreshed_snapshot or snapshot

            if channel_id and message_ts:
                updated_blocks = _replace_actions_with_context(
                    message_blocks,
                    f"✅ 延期を承認しました ({_format_due(datetime.now(JST))})",
                )
                if updated_blocks:
                    try:
                        slack_service.client.chat_update(
                            channel=channel_id,
                            ts=message_ts,
                            blocks=updated_blocks,
                            text="延期を承認しました",
                        )
                    except Exception as update_error:
                        print(f"⚠️ Failed to update approval message: {update_error}")

            if display_snapshot and approved_due:
                await slack_service.notify_extension_approved(
                    assignee_slack_id=assignee_slack_id or "",
                    requester_slack_id=requester_slack_id or "",
                    snapshot=display_snapshot,
                    new_due=approved_due,
                )

            slack_service.update_modal_message(
                view_id=modal_id,
                title=f"延期承認完了{settings.app_name_suffix}",
                message=f"延期申請を承認しました。\n新しい納期: {_format_due(approved_due)}",
                emoji="✅",
                close_text="閉じる",
            )
        except Exception as error:
            print(f"⚠️ Extension approval failed: {error}")
            slack_service.update_modal_message(
                view_id=modal_id,
                title=f"延期承認エラー{settings.app_name_suffix}",
                message=f"エラーが発生しました: {str(error)}",
                emoji="⚠️",
                close_text="閉じる",
            )

    asyncio.create_task(run_extension_approval())
    return JSONResponse(content={})


async def handle_reject_extension_action(
    payload: Dict[str, Any],
    dependencies: SlackDependencies,
    *,
    trigger_id: str,
    page_id: Optional[str],
    assignee_slack_id: Optional[str],
    requester_slack_id: Optional[str],
    channel_id: Optional[str],
    message_ts: Optional[str],
    message_blocks: Optional[list],
) -> JSONResponse:
    if not page_id:
        return JSONResponse(content={})

    slack_service = dependencies.slack_service
    notion_service = dependencies.notion_service
    task_concurrency = dependencies.task_concurrency
    task_metrics_service = dependencies.task_metrics_service
    settings = dependencies.settings

    modal_id = slack_service.open_processing_modal(
        trigger_id=trigger_id,
        title=f"延期却下処理{settings.app_name_suffix}",
        message="延期申請を却下しています。しばらくお待ちください。",
    )

    async def run_extension_rejection() -> None:
        try:
            snapshot: Optional[NotionTaskSnapshot] = None
            refreshed_snapshot: Optional[NotionTaskSnapshot] = None
            actor_slack_id = payload.get("user", {}).get("id")

            async with task_concurrency.guard(page_id):
                snapshot = await notion_service.get_task_snapshot(page_id)
                await notion_service.reject_extension(page_id)

                actor_email = None
                if actor_slack_id:
                    user_info = await slack_service.get_user_info(actor_slack_id)
                    actor_email = user_info.get("profile", {}).get("email") if user_info else None

                await notion_service.record_audit_log(
                    task_page_id=page_id,
                    event_type="延期却下",
                    detail="依頼者が延期申請を却下しました",
                    actor_email=actor_email,
                )

                if task_metrics_service:
                    refreshed_snapshot = await notion_service.get_task_snapshot(page_id)
                    target_snapshot = refreshed_snapshot or snapshot
                    await task_metrics_service.sync_snapshot(
                        target_snapshot,
                        reminder_stage=target_snapshot.reminder_stage,
                    )
                    await task_metrics_service.refresh_assignee_summaries()

            display_snapshot = refreshed_snapshot or snapshot

            if channel_id and message_ts:
                updated_blocks = _replace_actions_with_context(
                    message_blocks,
                    f"⚠️ 延期申請を却下しました ({_format_due(datetime.now(JST))})",
                )
                if updated_blocks:
                    try:
                        slack_service.client.chat_update(
                            channel=channel_id,
                            ts=message_ts,
                            blocks=updated_blocks,
                            text="延期申請を却下しました",
                        )
                    except Exception as update_error:
                        print(f"⚠️ Failed to update rejection message: {update_error}")

            if display_snapshot:
                await slack_service.notify_extension_rejected(
                    assignee_slack_id=assignee_slack_id or "",
                    requester_slack_id=requester_slack_id or "",
                    snapshot=display_snapshot,
                )

            slack_service.update_modal_message(
                view_id=modal_id,
                title=f"延期却下完了{settings.app_name_suffix}",
                message="延期申請を却下しました。",
                emoji="✅",
                close_text="閉じる",
            )
        except Exception as error:
            print(f"⚠️ Extension rejection failed: {error}")
            slack_service.update_modal_message(
                view_id=modal_id,
                title=f"延期却下エラー{settings.app_name_suffix}",
                message=f"エラーが発生しました: {str(error)}",
                emoji="⚠️",
                close_text="閉じる",
            )

    asyncio.create_task(run_extension_rejection())
    return JSONResponse(content={})
