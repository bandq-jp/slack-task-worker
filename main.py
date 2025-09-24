from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
from dotenv import load_dotenv
from src.presentation.api.slack_endpoints import router as slack_router

# 環境変数をロード
load_dotenv()


def create_app() -> FastAPI:
    """アプリケーションファクトリー"""
    # 環境に応じてアプリタイトルを変更
    env = os.getenv("ENV", "local")
    app_suffix = " (Dev)" if env != "production" else ""

    app = FastAPI(
        title=f"Slack-Notion Task Management System{app_suffix}",
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
        return {
            "message": f"Slack-Notion Task Management System{app_suffix} is running",
            "environment": env,
            "version": "1.0.0"
        }

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
