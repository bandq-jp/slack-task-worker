from dataclasses import dataclass
from typing import Optional

from src.infrastructure.slack.slack_service import SlackService
from src.infrastructure.notion.dynamic_notion_service import DynamicNotionService
from src.infrastructure.notion.admin_metrics_service import AdminMetricsNotionService
from src.infrastructure.repositories.notion_user_repository_impl import NotionUserRepositoryImpl
from src.infrastructure.repositories.slack_user_repository_impl import SlackUserRepositoryImpl
from src.infrastructure.repositories.task_repository_impl import InMemoryTaskRepository
from src.infrastructure.repositories.user_repository_impl import InMemoryUserRepository
from src.infrastructure.google.google_calendar_service import GoogleCalendarService
from src.infrastructure.repositories.calendar_task_repository_impl import GoogleCalendarTaskRepository
from src.application.services.user_mapping_service import UserMappingApplicationService
from src.domain.services.user_mapping_domain_service import UserMappingDomainService
from src.application.services.task_service import TaskApplicationService
from src.application.services.task_event_notification_service import TaskEventNotificationService
from src.application.services.task_metrics_service import TaskMetricsApplicationService
from src.application.services.calendar_task_service import CalendarTaskApplicationService
from src.services.ai_service import TaskAIService
from src.utils.concurrency import ConcurrencyCoordinator
from .config import Settings


@dataclass
class SlackDependencies:
    settings: Settings
    slack_service: SlackService
    notion_service: DynamicNotionService
    task_repository: InMemoryTaskRepository
    user_repository: InMemoryUserRepository
    notion_user_repository: NotionUserRepositoryImpl
    slack_user_repository: SlackUserRepositoryImpl
    user_mapping_service: UserMappingApplicationService
    task_service: TaskApplicationService
    admin_metrics_service: AdminMetricsNotionService
    task_metrics_service: TaskMetricsApplicationService
    task_event_notification_service: Optional[TaskEventNotificationService]
    calendar_task_service: Optional[CalendarTaskApplicationService]
    ai_service: Optional[TaskAIService]
    task_concurrency: ConcurrencyCoordinator


def build_slack_dependencies() -> SlackDependencies:
    settings = Settings()

    task_repository = InMemoryTaskRepository()
    user_repository = InMemoryUserRepository()
    slack_service = SlackService(settings.slack_token, settings.slack_bot_token, settings.env)

    notion_user_repository = NotionUserRepositoryImpl(
        notion_token=settings.notion_token,
        default_database_id=settings.notion_database_id,
        mapping_database_id=settings.mapping_database_id or None,
    )
    slack_user_repository = SlackUserRepositoryImpl(slack_token=settings.slack_bot_token)
    mapping_domain_service = UserMappingDomainService()
    user_mapping_service = UserMappingApplicationService(
        notion_user_repository=notion_user_repository,
        slack_user_repository=slack_user_repository,
        mapping_domain_service=mapping_domain_service,
    )
    task_event_notification_service_instance = TaskEventNotificationService(
        slack_service=slack_service,
        slack_user_repository=slack_user_repository,
        notification_emails=settings.task_event_notification_emails or [],
    )
    task_event_notification_service = (
        task_event_notification_service_instance
        if task_event_notification_service_instance.enabled
        else None
    )

    notion_service = DynamicNotionService(
        notion_token=settings.notion_token,
        database_id=settings.notion_database_id,
        user_mapping_service=user_mapping_service,
        audit_database_id=settings.notion_audit_database_id,
    )

    admin_metrics_service = AdminMetricsNotionService(
        notion_token=settings.notion_token,
        metrics_database_id=settings.notion_metrics_database_id,
        summary_database_id=settings.notion_assignee_summary_database_id,
    )
    task_metrics_service = TaskMetricsApplicationService(
        admin_metrics_service=admin_metrics_service,
        enabled=settings.task_metrics_enabled,
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

    task_concurrency = ConcurrencyCoordinator(max_concurrency=6)

    task_service = TaskApplicationService(
        task_repository=task_repository,
        user_repository=user_repository,
        slack_service=slack_service,
        notion_service=notion_service,
        task_metrics_service=task_metrics_service,
        concurrency_coordinator=task_concurrency,
        task_event_notification_service=task_event_notification_service,
    )

    calendar_task_service: Optional[CalendarTaskApplicationService] = None
    if settings.service_account_json:
        try:
            google_calendar_service = GoogleCalendarService(
                service_account_json=settings.service_account_json,
                env=settings.env,
            )
            calendar_task_repository = GoogleCalendarTaskRepository(google_calendar_service)
            calendar_task_service = CalendarTaskApplicationService(
                calendar_task_repository=calendar_task_repository,
                user_mapping_service=user_mapping_service,
            )
        except Exception as calendar_error:
            print(f"⚠️ Google Calendar initialization failed: {calendar_error}")
            print("   Calendar integration will be disabled")

    return SlackDependencies(
        settings=settings,
        slack_service=slack_service,
        notion_service=notion_service,
        task_repository=task_repository,
        user_repository=user_repository,
        notion_user_repository=notion_user_repository,
        slack_user_repository=slack_user_repository,
        user_mapping_service=user_mapping_service,
        task_service=task_service,
        admin_metrics_service=admin_metrics_service,
        task_metrics_service=task_metrics_service,
        task_event_notification_service=task_event_notification_service,
        calendar_task_service=calendar_task_service,
        ai_service=ai_service,
        task_concurrency=task_concurrency,
    )
