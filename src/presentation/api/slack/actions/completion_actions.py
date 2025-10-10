import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi.responses import JSONResponse
from zoneinfo import ZoneInfo

from src.presentation.api.slack.context import SlackDependencies

JST = ZoneInfo("Asia/Tokyo")


def _format_datetime(dt: Optional[datetime]) -> str:
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
    updated: list = []
    replaced = False
    for block in blocks:
        if not replaced and isinstance(block, dict) and block.get("type") == "actions":
            updated.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": text}],
            })
            replaced = True
        else:
            updated.append(block)
    if not replaced:
        updated.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": text}],
        })
    return updated


def _to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if not dt:
        return None
    if dt.tzinfo:
        return dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=JST).astimezone(timezone.utc)


def _requested_on_time(requested_at: Optional[datetime], due: Optional[datetime]) -> bool:
    req_utc = _to_utc(requested_at)
    due_utc = _to_utc(due)
    if not req_utc or not due_utc:
        return False
    return req_utc <= due_utc


async def handle_completion_approval_action(
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
        title=f"完了承認処理{settings.app_name_suffix}",
        message="完了申請を承認しています。しばらくお待ちください。",
    )

    async def run_completion_approval() -> None:
        try:
            snapshot = None
            refreshed_snapshot = None
            approval_time = datetime.now(JST)
            actor_slack_id = payload.get("user", {}).get("id")

            async def _resolve_display_name(slack_id: Optional[str], fallback: str) -> str:
                if not slack_id:
                    return fallback
                try:
                    info = await slack_service.get_user_info(slack_id)
                except Exception:
                    return fallback
                return (
                    info.get("real_name")
                    or info.get("profile", {}).get("real_name")
                    or info.get("profile", {}).get("display_name")
                    or info.get("name")
                    or fallback
                )

            async with task_concurrency.guard(page_id):
                snapshot = await notion_service.get_task_snapshot(page_id)
                if not snapshot:
                    slack_service.update_modal_message(
                        view_id=modal_id,
                        title=f"完了承認エラー{settings.app_name_suffix}",
                        message="Notionのタスク情報を取得できませんでした。",
                        emoji="⚠️",
                        close_text="閉じる",
                    )
                    return

                requested_before_due = _requested_on_time(
                    snapshot.completion_requested_at,
                    snapshot.due_date,
                )
                eligible_for_overdue_points = getattr(snapshot, "status", None) == "承認済み"

                await notion_service.approve_completion(
                    page_id,
                    approval_time,
                    requested_before_due,
                )
                await notion_service.update_task_status(page_id, "completed")

                actor_email = None
                if actor_slack_id:
                    user_info = await slack_service.get_user_info(actor_slack_id)
                    actor_email = user_info.get("profile", {}).get("email") if user_info else None

                await notion_service.record_audit_log(
                    task_page_id=page_id,
                    event_type="完了承認",
                    detail=f"完了承認 {approval_time.strftime('%Y-%m-%d %H:%M')}",
                    actor_email=actor_email,
                )

                refreshed_snapshot = await notion_service.get_task_snapshot(page_id)
                snapshot_for_metrics = refreshed_snapshot or snapshot

                target_points = 1 if (eligible_for_overdue_points and not requested_before_due) else 0
                try:
                    now_utc = datetime.now(timezone.utc)
                    due_utc = snapshot_for_metrics.due_date.astimezone(timezone.utc) if snapshot_for_metrics.due_date else None
                    still_overdue = bool(due_utc and due_utc <= now_utc)
                    eligible_status = getattr(snapshot_for_metrics, "status", None) == "承認済み"
                    target_points = 1 if (still_overdue and eligible_status) else 0
                    metrics = await task_metrics_service.admin_metrics_service.get_metrics_by_task_id(page_id)
                    current_points = metrics.overdue_points if metrics else 0
                    if current_points != target_points:
                        await task_metrics_service.update_overdue_points(page_id, target_points)
                except Exception as pts_err:
                    print(f"⚠️ Failed to update overdue points after completion approval: {pts_err}")

                await task_metrics_service.sync_snapshot(
                    snapshot_for_metrics,
                    overdue_points=target_points,
                )
                await task_metrics_service.refresh_assignee_summaries()

            display_snapshot = refreshed_snapshot or snapshot

            if channel_id and message_ts:
                updated_blocks = _replace_actions_with_context(
                    message_blocks,
                    f"✅ 完了を承認しました ({_format_datetime(approval_time)})",
                )
                if updated_blocks:
                    try:
                        slack_service.client.chat_update(
                            channel=channel_id,
                            ts=message_ts,
                            blocks=updated_blocks,
                            text="完了を承認しました",
                        )
                    except Exception as update_error:
                        print(f"⚠️ Failed to update completion approval message: {update_error}")

            if display_snapshot:
                await slack_service.notify_completion_approved(
                    assignee_slack_id=assignee_slack_id or "",
                    requester_slack_id=requester_slack_id or "",
                    snapshot=display_snapshot,
                    approval_time=approval_time,
                )
                notification_service = dependencies.task_event_notification_service
                if notification_service:
                    requester_name = await _resolve_display_name(requester_slack_id, "依頼者")
                    assignee_name = await _resolve_display_name(assignee_slack_id, "担当者")
                    try:
                        await notification_service.notify_completion_approved(
                            notion_page_id=display_snapshot.page_id,
                            title=display_snapshot.title,
                            due_date=display_snapshot.due_date,
                            approval_time=approval_time,
                            requester_slack_id=requester_slack_id or "",
                            requester_name=requester_name,
                            assignee_slack_id=assignee_slack_id or "",
                            assignee_name=assignee_name,
                        )
                    except Exception as notify_error:
                        print(f"⚠️ Failed to broadcast completion approval notification: {notify_error}")

            slack_service.update_modal_message(
                view_id=modal_id,
                title=f"完了承認完了{settings.app_name_suffix}",
                message=f"完了申請を承認しました。承認日時: {_format_datetime(approval_time)}",
                emoji="✅",
                close_text="閉じる",
            )
        except Exception as error:
            print(f"⚠️ Completion approval failed: {error}")
            slack_service.update_modal_message(
                view_id=modal_id,
                title=f"完了承認エラー{settings.app_name_suffix}",
                message=f"エラーが発生しました: {str(error)}",
                emoji="⚠️",
                close_text="閉じる",
            )

    asyncio.create_task(run_completion_approval())
    return JSONResponse(content={})
