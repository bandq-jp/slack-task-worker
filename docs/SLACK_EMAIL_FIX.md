# 📧 Slackユーザーメール取得エラーの解決方法

## 問題の症状
```
⚠️ Email is empty for user lookup
```

## 原因
Slackアプリにメールアドレスにアクセスする権限が不足している可能性があります。

## 解決手順

### 1. Slack Appの権限確認

1. **Slack App管理画面**にアクセス
2. 左サイドバーの「**OAuth & Permissions**」をクリック
3. 「**Bot Token Scopes**」セクションを確認

### 2. 必要な権限を追加

現在の権限:
- `chat:write`
- `im:write`
- `users:read`
- `commands`

**追加が必要な権限**:
- `users:read.email` ← **これを追加！**

### 3. 権限追加手順

1. 「**Bot Token Scopes**」の「**Add an OAuth Scope**」をクリック
2. `users:read.email` を検索して追加
3. ページ上部に「**You need to reinstall your app**」メッセージが表示される
4. 「**reinstall your app**」リンクをクリック
5. 権限を確認して「**許可する**」

### 4. 権限の説明

- `users:read`: 基本的なユーザー情報（名前、IDなど）
- `users:read.email`: **ユーザーのメールアドレス** ← 必須

## 確認方法

権限追加後、もう一度 `/task-request` を実行して、コンソールログで以下が表示されることを確認：

```
📧 Email in profile: actual-email@example.com
```

## 追加の確認事項

### ワークスペース設定の確認

1. Slackワークスペースの設定で、アプリがメールアドレスにアクセスできるか確認
2. 個人のプライバシー設定でメールアドレスが公開されているか確認

### User Tokenの使用

Bot Tokenで取得できない場合は、User Tokenを使用する方法もあります：

```python
# SlackServiceのコンストラクタで
self.user_client = WebClient(token=slack_token)  # User Token

# get_user_info内で
response = self.user_client.users_info(user=user_id)  # User Token使用
```

## トラブルシューティング

### ケース1: 権限追加後もメールが取得できない
- ワークスペース管理者にメール表示設定を確認
- ユーザー個人のプライバシー設定を確認

### ケース2: 一部のユーザーのみメールが取得できない
- 外部ユーザー（ゲスト）はメールアドレスが制限される場合がある
- ユーザータイプ（Member, Admin, Guest）を確認

### ケース3: Enterprise Gridワークスペースの場合
- より厳しい権限制御がある場合があります
- 管理者に相談が必要な場合があります