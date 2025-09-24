# Slack App セットアップガイド

## 重要: 環境分離について

このシステムは本番環境とローカル開発環境を分離して運用できます：

- **本番環境**: `/task-request` コマンド、"Task Request Bot"
- **開発環境**: `/task-request-dev` コマンド、"Task Request Bot (Dev)"

**本番とローカルで異なるSlackアプリを作成することを強く推奨します。**

## 1. Slack App の作成

### Step 1: 基本的なmanifestでアプリを作成

1. https://api.slack.com/apps にアクセス
2. 「Create New App」→「From an app manifest」を選択
3. ワークスペースを選択
4. 環境に応じて以下のmanifestを使用：

#### 本番環境用 manifest:
```json
{
    "display_information": {
        "name": "Task Request Bot",
        "description": "SlackとNotionを連携したタスク依頼管理システム",
        "background_color": "#2c2d30"
    },
    "features": {
        "bot_user": {
            "display_name": "Task Request Bot",
            "always_online": true
        }
    },
    "oauth_config": {
        "scopes": {
            "bot": [
                "chat:write",
                "im:write",
                "users:read",
                "users:read.email",
                "commands"
            ]
        }
    },
    "settings": {
        "org_deploy_enabled": false,
        "socket_mode_enabled": false,
        "token_rotation_enabled": false
    }
}
```

#### 開発環境用 manifest:
```json
{
    "display_information": {
        "name": "Task Request Bot (Dev)",
        "description": "SlackとNotionを連携したタスク依頼管理システム（開発環境）",
        "background_color": "#ff6b00"
    },
    "features": {
        "bot_user": {
            "display_name": "Task Request Bot (Dev)",
            "always_online": true
        }
    },
    "oauth_config": {
        "scopes": {
            "bot": [
                "chat:write",
                "im:write",
                "users:read",
                "users:read.email",
                "commands"
            ]
        }
    },
    "settings": {
        "org_deploy_enabled": false,
        "socket_mode_enabled": false,
        "token_rotation_enabled": false
    }
}
```

5. 「Next」→「Create」をクリック

### Step 2: アプリをワークスペースにインストール

1. 作成後のアプリ管理画面で「Install to Workspace」をクリック
2. 権限を確認して「許可する」

## 2. トークンの取得

### Bot Token:
1. 左サイドバーの「OAuth & Permissions」をクリック
2. 「Install to Workspace」をクリック
3. 権限を確認して「許可する」
4. 「Bot User OAuth Token」（xoxb-で始まる）をコピー

### User Token（オプション）:
1. 「OAuth & Permissions」ページ
2. 「User Token Scopes」セクションで以下を追加：
   - `users:read`
3. 再インストール
4. 「User OAuth Token」（xoxp-で始まる）をコピー

### Signing Secret:
1. 左サイドバーの「Basic Information」をクリック
2. 「App Credentials」セクション
3. 「Signing Secret」の「Show」をクリックしてコピー

## 3. 機能の手動設定（ngrok起動後）

### Step 3: ngrokの起動
```bash
# 別ターミナルで実行
ngrok http 8000
```

表示されるHTTPS URLをコピー（例: `https://abc123.ngrok.io`）

### Step 4: Slash Commandsの追加

**重要**: 環境に応じて異なるコマンド名を使用してください

#### 本番環境の場合:
1. 左サイドバーの「Slash Commands」をクリック
2. 「Create New Command」をクリック
3. 以下を入力：
   - Command: `/task-request`
   - Request URL: `https://your-production-url.com/slack/commands`
   - Short Description: `新しいタスク依頼を作成`
   - Usage Hint: `タスク依頼フォームを開きます`
4. 「Save」をクリック

#### 開発環境の場合:
1. 左サイドバーの「Slash Commands」をクリック
2. 「Create New Command」をクリック
3. 以下を入力：
   - Command: `/task-request-dev`
   - Request URL: `https://your-ngrok-url.ngrok.io/slack/commands`
   - Short Description: `新しいタスク依頼を作成 (Dev)`
   - Usage Hint: `タスク依頼フォームを開きます（開発環境）`
4. 「Save」をクリック

### Step 5: Interactivityの設定
1. 左サイドバーの「Interactivity & Shortcuts」をクリック
2. 「Interactivity」をONにする
3. Request URL: `https://your-ngrok-url.ngrok.io/slack/interactive`
4. 「Save Changes」をクリック

## 4. 環境変数の設定

### 開発環境用 `.env`ファイル:

```bash
# Environment
ENV=local

# Slack Configuration (Development App)
SLACK_TOKEN=xoxp-your-dev-user-token（オプション）
SLACK_BOT_TOKEN=xoxb-your-dev-bot-token
SLACK_SIGNING_SECRET=your-dev-signing-secret

# Notion Configuration
NOTION_TOKEN=secret_your-notion-token
NOTION_DATABASE_ID=your-database-id

# Google Calendar Integration (オプショナル)
SERVICE_ACCOUNT_JSON=./secrets/service-account.json
```

### 本番環境用環境変数:

```bash
# Environment
ENV=production

# Slack Configuration (Production App)
SLACK_BOT_TOKEN=xoxb-your-production-bot-token
SLACK_SIGNING_SECRET=your-production-signing-secret

# Notion Configuration
NOTION_TOKEN=secret_your-production-notion-token
NOTION_DATABASE_ID=your-production-database-id

# Google Calendar Integration (オプショナル)
SERVICE_ACCOUNT_JSON="{"type":"service_account",...}" # JSON文字列
```

## 5. アプリケーションの起動

```bash
# FastAPIサーバーの起動
./run_local.sh

# 別ターミナルでngrokを起動
ngrok http 8000
```

## 6. 動作確認

### 開発環境:
1. Slackワークスペースで `/task-request-dev` と入力
2. "タスク依頼作成 (Dev)" モーダルが表示されることを確認
3. タスク情報を入力して送信
4. 依頼先にDMが送信されることを確認

### 本番環境:
1. Slackワークスペースで `/task-request` と入力
2. "タスク依頼作成" モーダルが表示されることを確認
3. タスク情報を入力して送信
4. 依頼先にDMが送信されることを確認

## 7. 環境分離の効果

この設定により以下の効果があります：

- ✅ 開発時に本番データを誤って変更するリスクを排除
- ✅ スラッシュコマンドの競合を回避
- ✅ 開発環境と本番環境の明確な識別
- ✅ 異なるNotionデータベースや設定の使用が可能

## トラブルシューティング

### コマンドが認識されない場合：
- Slash Commandsの設定を確認
- URLが正しく設定されているか確認
- ngrokが起動しているか確認

### モーダルが表示されない場合：
- Interactivityが有効になっているか確認
- Request URLが正しいか確認
- サーバーのログを確認

### DMが送信されない場合：
- Bot Tokenが正しく設定されているか確認
- `chat:write`と`im:write`権限があるか確認
- ユーザーIDが正しく取得できているか確認