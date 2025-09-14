# Slack App セットアップガイド

## 1. Slack App の作成

### Step 1: 基本的なmanifestでアプリを作成

1. https://api.slack.com/apps にアクセス
2. 「Create New App」→「From an app manifest」を選択
3. ワークスペースを選択
4. 以下の基本manifestをコピーして貼り付け：

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
1. 左サイドバーの「Slash Commands」をクリック
2. 「Create New Command」をクリック
3. 以下を入力：
   - Command: `/task-request`
   - Request URL: `https://your-ngrok-url.ngrok.io/slack/commands`
   - Short Description: `新しいタスク依頼を作成`
   - Usage Hint: `タスク依頼フォームを開きます`
4. 「Save」をクリック

### Step 5: Interactivityの設定
1. 左サイドバーの「Interactivity & Shortcuts」をクリック
2. 「Interactivity」をONにする
3. Request URL: `https://your-ngrok-url.ngrok.io/slack/interactive`
4. 「Save Changes」をクリック

## 4. 環境変数の設定

`.env`ファイルを作成：

```bash
# Slack Configuration
SLACK_TOKEN=xoxp-your-user-token（オプション）
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_SIGNING_SECRET=your-signing-secret

# Notion Configuration（後で設定）
NOTION_TOKEN=secret_your-notion-token
NOTION_DATABASE_ID=your-database-id
```

## 5. アプリケーションの起動

```bash
# FastAPIサーバーの起動
./run_local.sh

# 別ターミナルでngrokを起動
ngrok http 8000
```

## 6. 動作確認

1. Slackワークスペースで `/task-request` と入力
2. モーダルが表示されることを確認
3. タスク情報を入力して送信
4. 依頼先にDMが送信されることを確認

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