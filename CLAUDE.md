# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Slack-Notion Task Management System that uses Domain-Driven Design (DDD) and Clean Architecture patterns. It's a Python FastAPI application that integrates Slack commands with Notion databases for task management workflow.

## Environment Configuration

This system supports environment separation between production and local development:

| Setting | Production | Development |
|---------|------------|-------------|
| **Environment Variable** | `ENV=production` | `ENV=local` |
| **Slash Command** | `/task-request` | `/task-request-dev` |
| **App Name** | Task Request Bot | Task Request Bot (Dev) |
| **Modal Title** | タスク依頼作成 | タスク依頼作成 (Dev) |

**Important**: Use separate Slack Apps for production and development environments to avoid conflicts.

## Key Commands

### Development
```bash
# Install dependencies using uv
uv sync

# Set environment for local development
echo "ENV=local" >> .env

# Run the application locally
uv run main.py
# OR use the script
scripts/run_local.sh

# Run ngrok for local development (in separate terminal)
ngrok http 8000

# Run tests
python tests/test_complete_workflow.py
```

### Docker & Deployment
```bash
# Build Docker image
docker build -t slack-notion-task .

# Deploy to Cloud Run
gcloud run deploy slack-notion-task \
  --image slack-notion-task \
  --platform managed \
  --region asia-northeast1 \
  --allow-unauthenticated
```

## Architecture Overview

The project follows DDD/Clean Architecture with clear layer separation:

### Layer Structure
- **Domain Layer** (`src/domain/`): Core business logic, entities, value objects, and repository interfaces
- **Application Layer** (`src/application/`): Use cases, application services, DTOs
- **Infrastructure Layer** (`src/infrastructure/`): External integrations (Slack, Notion), repository implementations
- **Presentation Layer** (`src/presentation/`): FastAPI endpoints, request/response handling

### Key Architectural Decisions

1. **Dynamic User Mapping System**:
   - Implements 3-stage search: mapping file → DB search → regular member search
   - Handles guest users efficiently without pre-loading all users
   - Located in `src/application/services/user_mapping_service.py`

2. **Repository Pattern**:
   - All data access goes through repository interfaces defined in domain layer
   - Implementations in infrastructure layer allow swapping data sources

3. **Service Organization**:
   - Domain Services: Business logic that doesn't fit in entities
   - Application Services: Orchestrate domain objects and infrastructure
   - Infrastructure Services: Direct integration with external systems

## Core Services & Components

### Main Entry Points
- `main.py`: FastAPI application setup and configuration
- `src/presentation/api/slack_endpoints.py`: All Slack interaction endpoints

### Critical Services
- `SlackService`: Handles all Slack API interactions (modals, messages, user lookups)
- `DynamicNotionService`: Manages Notion database operations with dynamic user mapping
- `TaskApplicationService`: Orchestrates task creation and approval workflow
- `UserMappingApplicationService`: Handles user mapping between Slack and Notion
- `TaskAIService`: Optional AI analysis and improvement of task descriptions

### Data Flow
1. Slack slash command `/task-request` → FastAPI endpoint
2. Opens modal form → User fills task details
3. Creates task in Notion immediately upon submission
4. Sends approval buttons to assignee via DM
5. Updates Notion status on approval/rejection

## Environment Configuration

Required environment variables (see `.env.example`):
- `SLACK_BOT_TOKEN`: Bot user OAuth token
- `SLACK_SIGNING_SECRET`: For request verification
- `NOTION_TOKEN`: Integration token
- `NOTION_DATABASE_ID`: Target database for tasks
- `GEMINI_API_KEY`: (Optional) For AI task enhancement

## Key Features & Implementation Notes

### Rich Text Handling
- Slack rich text blocks are converted to Notion format
- Markdown detection and conversion in `DynamicNotionService`
- Text converter utility in `src/utils/text_converter.py`

### User Mapping
- No static mapping files - all dynamic lookups
- Caches discovered users for performance
- Handles guest users and external collaborators

### Async Processing
- Modal submissions return immediately with loading state
- Background processing for AI analysis and task creation
- Updates sent via Slack Web API after processing

### Error Handling
- Comprehensive try-catch blocks in all endpoints
- User-friendly error messages in Slack
- Detailed logging for debugging

## Testing Approach

- Integration tests in `tests/test_complete_workflow.py`
- Individual component tests for Notion and Slack services
- Debug utilities for investigating user mapping issues

## Important Considerations

1. **Environment Separation**:
   - Always use `ENV=local` for development and `ENV=production` for production
   - Create separate Slack Apps for each environment to avoid command conflicts
   - Use different Notion databases for development and production

2. **Slack URL Configuration**: When running locally, update Slack app with ngrok URLs:
   - Slash Commands: `{ngrok-url}/slack/commands`
   - Interactive Components: `{ngrok-url}/slack/interactive`

3. **Command Configuration**:
   - Development Slack app should use `/task-request-dev` command
   - Production Slack app should use `/task-request` command
   - Update Slack app manifest according to environment (different app names and colors)

4. **Notion Permissions**: Integration must have access to both the database and users

5. **Guest User Handling**: System automatically discovers and maps guest users without manual configuration

6. **AI Enhancement**: Optional feature - degrades gracefully if GEMINI_API_KEY not provided

7. **Google Calendar Integration**: Optional feature controlled by SERVICE_ACCOUNT_JSON setting

8. **State Management**: Modal sessions stored in memory - not suitable for multi-instance deployments without Redis/shared state