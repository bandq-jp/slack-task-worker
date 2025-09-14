from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from src.presentation.api.slack_endpoints import router as slack_router


def create_app() -> FastAPI:
    """アプリケーションファクトリー"""
    app = FastAPI(
        title="Slack-Notion Task Management System",
        description="Slack経由でタスク依頼を作成し、Notionに保存するシステム",
        version="1.0.0",
    )

    # CORS設定
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ルーターの登録
    app.include_router(slack_router)

    @app.get("/")
    async def root():
        return {"message": "Slack-Notion Task Management System is running"}

    @app.get("/health")
    async def health_check():
        return {"status": "healthy"}

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )