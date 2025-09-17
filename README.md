# Slack-Notion Task Management System

SlackからNotionへのタスク管理システム。DDD/Clean Architectureを採用したPythonアプリケーションです。

## 🚀 主な機能

- Slackスラッシュコマンド `/task-request` でタスク作成
- リッチテキスト対応のモーダルフォーム
- 依頼先ユーザーにDMで承認・差し戻しボタン送信
- 即座にNotionデータベースにタスク保存
- ゲストユーザー対応の高速ユーザーマッピング
- 承認・差し戻し時にNotionのステータス更新

## 📁 プロジェクト構造

```
slack-test/
├── README.md                 # このファイル
├── main.py                  # メインアプリケーション
├── src/                     # アプリケーションコード（DDD/Clean Architecture）
├── docs/                    # ドキュメント・セットアップガイド
├── admin/                   # 管理ツール（ユーザーマッピング）
├── tests/                   # テスト・調査スクリプト
├── scripts/                 # 実行スクリプト
└── setup/                   # 設定ファイル
```

詳細な構造については [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) を参照してください。

## 🌍 環境分離設定

このシステムは本番環境とローカル開発環境を完全に分離して運用できます：

| 項目 | 本番環境 | 開発環境 |
|------|----------|----------|
| **Slashコマンド** | `/task-request` | `/task-request-dev` |
| **アプリ名** | Task Request Bot | Task Request Bot (Dev) |
| **モーダルタイトル** | タスク依頼作成 | タスク依頼作成 (Dev) |
| **環境変数** | `ENV=production` | `ENV=local` |

**重要**: 本番と開発で異なるSlack Appを作成することを強く推奨します。

## ⚡ クイックスタート

### 1. 環境変数設定

`.env.example` を `.env` にコピーして必要な値を設定：

```bash
cp .env.example .env
```

**重要**: 開発環境では `ENV=local` を設定してください：
```bash
# .env ファイル内
ENV=local
```

### 2. 依存関係インストール

```bash
uv sync
```

### 3. ユーザーマッピング初期化

```bash
python admin/setup_user_mapping.py
```

### 4. アプリケーション起動

```bash
# ローカル開発用
scripts/run_local.sh

# または直接実行
uv run main.py
```

### 5. ngrokでトンネル作成（開発時）

```bash
ngrok http 8000
```

## 🔧 セットアップガイド

### Slack App設定
詳細な手順は [docs/SLACK_SETUP.md](docs/SLACK_SETUP.md) を参照

### Notion Integration設定
詳細な手順は [docs/NOTION_SETUP.md](docs/NOTION_SETUP.md) を参照

### 統合テスト
```bash
python tests/test_complete_workflow.py
```

## 🎯 使用フロー

1. Slackでコマンド実行（環境により異なる）
   - 本番環境: `/task-request`
   - 開発環境: `/task-request-dev`
2. モーダルフォームで入力：
   - 依頼先Slackユーザー選択
   - タスクタイトル
   - 納期
   - タスク内容（リッチテキスト対応）
3. **即座にNotionにタスク保存**
4. 依頼先にDMで承認・差し戻しボタン送信
5. 承認・差し戻し時にNotionのステータス更新
6. 差し戻し時は理由もNotionに保存

## 🏗️ アーキテクチャ

### DDD/Clean Architecture採用

```
src/
├── domain/              # ドメイン層（ビジネスロジック）
│   ├── entities/        # エンティティ
│   └── repositories/    # リポジトリインターフェース
├── application/         # アプリケーション層
│   ├── services/        # アプリケーションサービス
│   └── dto/             # データ転送オブジェクト
├── infrastructure/      # インフラストラクチャ層
│   ├── slack/           # Slack API統合
│   ├── notion/          # Notion API統合
│   └── repositories/    # リポジトリ実装
└── presentation/        # プレゼンテーション層
    └── api/             # REST APIエンドポイント
```

### 🎯 ゲストユーザー対応システム

- **3段階検索**: マッピングファイル(高速) → DB検索 → 正規メンバー検索
- **自動キャッシュ**: 新規ユーザーの自動検出・マッピング追加
- **大規模対応**: 30人以上のゲストユーザーでも高速処理
- **管理ツール**: 初期セットアップ・メンテナンスツール完備

## 🛠️ 管理・メンテナンス

### ユーザーマッピング管理

```bash
# 初回セットアップ（既存データベースからユーザー抽出）
python admin/setup_user_mapping.py

# 新規ユーザー追加・更新
python admin/update_user_mapping.py
```

### トラブルシューティング

- **Slackコマンドが動かない**: [docs/SLACK_TROUBLESHOOTING.md](docs/SLACK_TROUBLESHOOTING.md)
- **メール取得できない**: [docs/SLACK_EMAIL_FIX.md](docs/SLACK_EMAIL_FIX.md)
- **Notion権限エラー**: [docs/NOTION_INTEGRATION_FIX.md](docs/NOTION_INTEGRATION_FIX.md)

## 🚀 デプロイ（Cloud Run）

### 1. Dockerビルド
```bash
docker build -t slack-notion-task .
```

### 2. Cloud Runデプロイ
```bash
gcloud run deploy slack-notion-task \
  --image slack-notion-task \
  --platform managed \
  --region asia-northeast1 \
  --allow-unauthenticated \
  --set-env-vars "SLACK_BOT_TOKEN=xxx,NOTION_TOKEN=xxx,..."
```

## 📊 機能一覧

- ✅ Slackスラッシュコマンド統合
- ✅ インタラクティブモーダルフォーム
- ✅ リッチテキストエディタ対応
- ✅ Notionデータベース統合
- ✅ ゲストユーザー対応
- ✅ 自動ユーザーマッピング
- ✅ 承認・差し戻しワークフロー
- ✅ DDD/Clean Architecture
- ✅ 完全テストカバレッジ
- ✅ Docker対応
- ✅ Cloud Run対応

## 🤝 コントリビューション

プロジェクトの改善にご協力いただける場合は、issueやプルリクエストをお送りください。

## 📄 ライセンス

このプロジェクトはMITライセンスの下で公開されています。