# Slack スラッシュコマンドのトラブルシューティング

## スラッシュコマンドが表示されない場合のチェックリスト

### 1. Slash Commandsの設定確認

Slack App管理画面で以下を確認：

1. **左サイドバー「Slash Commands」をクリック**
2. コマンドが登録されているか確認
   - コマンド名: `/task-request`
   - Request URL: 設定されているか

もし登録されていない場合：
1. 「Create New Command」をクリック
2. 以下を入力：
   ```
   Command: /task-request
   Request URL: （後でngrok起動後に設定）
   Short Description: 新しいタスク依頼を作成
   Usage Hint: タスク依頼フォームを開きます
   ```
3. 「Save」をクリック

### 2. アプリの再インストール

1. **「OAuth & Permissions」ページに移動**
2. 「Reinstall to Workspace」をクリック
3. 権限を確認して「許可する」

### 3. スラッシュコマンドの確認方法

Slackで以下を試してください：

1. **任意のチャンネルで `/` を入力**
   - アプリのコマンドが表示されるか確認

2. **直接コマンドを入力**
   - `/task-request` を直接入力してEnter

3. **DMでテスト**
   - Task Request BotとのDMで `/task-request` を試す

### 4. 権限の確認

「OAuth & Permissions」で以下のスコープが設定されているか確認：

**Bot Token Scopes:**
- `commands`
- `chat:write`
- `im:write`
- `users:read`

### 5. ngrokとRequest URLの設定

スラッシュコマンドを動作させるには：

1. **ngrokを起動**
   ```bash
   ngrok http 8000
   ```

2. **Request URLを設定**
   - Slack App管理画面の「Slash Commands」
   - `/task-request`コマンドを編集
   - Request URL: `https://your-ngrok-url.ngrok.io/slack/commands`
   - 「Save」

### 6. Workspace設定の確認

1. **ワークスペースの管理者に確認**
   - アプリのインストールが制限されていないか
   - スラッシュコマンドの使用が制限されていないか

2. **アプリの表示設定**
   - ワークスペースでアプリが「利用可能」になっているか確認

### 7. デバッグ手順

1. **Slackアプリを完全に再起動**
   - Slackアプリを終了
   - 再度起動してログイン

2. **ブラウザ版Slackで確認**
   - https://slack.com でブラウザからアクセス
   - スラッシュコマンドが表示されるか確認

3. **別のチャンネルで試す**
   - パブリックチャンネル
   - プライベートチャンネル
   - DM

### 8. アプリの可視性確認

1. **Slack ワークスペースで確認**
   - 左サイドバーの「アプリ」セクション
   - Task Request Botが表示されているか
   - 表示されていない場合は「アプリを追加」から検索

2. **チャンネルにアプリを追加**
   - チャンネルの詳細設定
   - 「インテグレーション」タブ
   - 「アプリを追加」でTask Request Botを追加

## よくある原因と解決策

| 問題 | 原因 | 解決策 |
|------|------|--------|
| コマンドが全く表示されない | Slash Commandsが未設定 | 手動でコマンドを追加 |
| コマンドはあるがエラーになる | Request URLが未設定 | ngrok起動後にURLを設定 |
| 特定のチャンネルで使えない | アプリがチャンネルに追加されていない | チャンネルにアプリを追加 |
| 権限エラー | スコープ不足 | 必要なスコープを追加して再インストール |

## 確認コマンド

Slackで以下を試してください：
1. `/apps` - インストール済みアプリの確認
2. `/task-request` - 直接入力
3. DMで `/` を入力してアプリコマンドを確認