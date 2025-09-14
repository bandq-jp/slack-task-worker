# 📁 プロジェクト構造

このドキュメントは、整理されたプロジェクト構造について説明します。

## 🏗️ ディレクトリ構造

```
slack-test/
├── README.md                 # メインの readme
├── Dockerfile               # Docker設定
├── main.py                  # メインアプリケーション
├── pyproject.toml          # Python依存関係
├── .env                    # 環境変数（秘匿）
├── .env.example            # 環境変数のテンプレート
├── .user_mapping.json      # ユーザーマッピングファイル（秘匿）
├── .gitignore             # Git除外設定
├── uv.lock               # 依存関係ロックファイル
│
├── src/                  # アプリケーションコード
│   ├── domain/          # ドメイン層（エンティティ、リポジトリ）
│   ├── application/     # アプリケーション層（サービス、DTO）
│   ├── infrastructure/  # インフラ層（Slack、Notion API）
│   └── presentation/    # プレゼンテーション層（API エンドポイント）
│
├── docs/                # ドキュメント
│   ├── PROJECT_STRUCTURE.md     # このファイル
│   ├── NOTION_SETUP.md          # Notion セットアップガイド
│   ├── NOTION_INTEGRATION_FIX.md # Notion 統合修正ガイド
│   ├── SLACK_SETUP.md           # Slack セットアップガイド
│   ├── SLACK_EMAIL_FIX.md       # Slack メール権限修正ガイド
│   └── SLACK_TROUBLESHOOTING.md # Slack トラブルシューティング
│
├── admin/               # 管理ツール
│   ├── setup_user_mapping.py   # ユーザーマッピング初期セットアップ
│   └── update_user_mapping.py  # ユーザーマッピング更新・メンテナンス
│
├── tests/               # テスト・調査スクリプト
│   ├── test_complete_workflow.py    # 完全ワークフローテスト
│   ├── test_notion.py              # Notion API テスト
│   ├── test_guest_assignment.py    # ゲストユーザー割り当てテスト
│   ├── debug_notion_users.py       # Notion ユーザーデバッグ
│   ├── fix_notion_status.py        # Notion ステータス修正
│   ├── investigate_guest_users.py  # ゲストユーザー調査
│   └── notion_guest_search.py      # ゲストユーザー検索実装
│
├── scripts/             # 実行スクリプト
│   ├── run_local.sh    # ローカル実行スクリプト
│   └── setup_ngrok.sh  # ngrok セットアップ
│
└── setup/               # セットアップ設定
    └── slack-app-manifest.json  # Slack アプリマニフェスト
```

## 🚀 使用方法

### 初回セットアップ
1. **依存関係インストール**: `uv sync`
2. **環境変数設定**: `.env.example` を参考に `.env` を作成
3. **ユーザーマッピング**: `python admin/setup_user_mapping.py` を実行
4. **アプリケーション起動**: `uv run main.py`

### 開発・運用
- **ローカル開発**: `scripts/run_local.sh`
- **新しいユーザー追加**: `python admin/update_user_mapping.py`
- **テスト実行**: `python tests/test_complete_workflow.py`
- **トラブルシューティング**: `docs/` 内の各種ガイドを参照

### セットアップガイド
- **Slack セットアップ**: [SLACK_SETUP.md](SLACK_SETUP.md)
- **Notion セットアップ**: [NOTION_SETUP.md](NOTION_SETUP.md)
- **統合設定**: [NOTION_INTEGRATION_FIX.md](NOTION_INTEGRATION_FIX.md)

## 🔧 管理・メンテナンス

### ユーザー管理
- **初回**: `admin/setup_user_mapping.py` で既存データベースからユーザー抽出
- **追加**: `admin/update_user_mapping.py` で新規ユーザー追加・更新
- **確認**: `tests/test_complete_workflow.py` で動作確認

### ファイル管理
- **秘匿ファイル**: `.env`, `.user_mapping.json` は Git に含めない
- **設定ファイル**: `setup/` 内のマニフェストファイルを使用
- **ログ**: アプリケーション実行時のログで問題を特定

## 📚 アーキテクチャ

このプロジェクトは **DDD（ドメイン駆動設計）/Clean Architecture** を採用しています：

- **Domain Layer** (`src/domain/`): ビジネスロジック・エンティティ
- **Application Layer** (`src/application/`): ユースケース・サービス
- **Infrastructure Layer** (`src/infrastructure/`): 外部API・データベース
- **Presentation Layer** (`src/presentation/`): Web API・エンドポイント

この構造により、**テスタブル**で **保守しやすい** コードベースを実現しています。