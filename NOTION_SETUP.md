# Notion セットアップガイド

## 1. Notion Integrationの作成

### Step 1: Notion Integrationを作成
1. https://www.notion.so/my-integrations にアクセス
2. 「+ New integration」をクリック
3. 以下を入力：
   - Name: `Task Request Bot`
   - Associated workspace: 使用するワークスペースを選択
   - Logo: お好みで
4. 「Submit」をクリック
5. 「Internal Integration Token」をコピー（secret_で始まる）

### Step 2: データベースIDの取得
あなたのNotionデータベースURL:
`https://www.notion.so/26e5c5c85ce8800e9400e4c2421903c3?v=26e5c5c85ce8807a926d000c4712c046&source=copy_link`

**データベースID: `26e5c5c85ce8800e9400e4c2421903c3`**

URLの`/`の後、`?`の前の32文字の文字列がデータベースIDです。

## 2. データベースプロパティの設定

以下のプロパティを作成してください：

### 必須プロパティ:
1. **タイトル** (Title) - 既存の場合はそのまま
2. **詳細** (Text) - リッチテキスト
3. **納期** (Date) - 日付
4. **ステータス** (Select) - セレクトボックス
   - オプション: `承認待ち`, `承認済み`, `差し戻し`
5. **依頼者** (Person) - 人物
6. **依頼先** (Person) - 人物

### オプションプロパティ:
7. **差し戻し理由** (Text) - リッチテキスト

### データベースプロパティ作成手順:
1. データベースページを開く
2. 右上の「...」メニュー → 「プロパティを編集」
3. 各プロパティを上記の通り追加/変更

## 3. データベースへのアクセス許可

### Step 3: Integrationにデータベースアクセスを許可
1. データベースページで右上の「共有」をクリック
2. 「招待」セクションで作成したIntegration「Task Request Bot」を検索
3. 「招待」をクリック

## 4. 環境変数の設定

`.env`ファイルを以下のように更新：

```bash
# Slack Configuration
SLACK_TOKEN=xoxp-your-slack-user-token
SLACK_BOT_TOKEN=xoxb-9517113054596-9511562695221-your-actual-bot-token
SLACK_SIGNING_SECRET=your-actual-signing-secret

# Notion Configuration
NOTION_TOKEN=secret_your-actual-notion-token
NOTION_DATABASE_ID=26e5c5c85ce8800e9400e4c2421903c3
```

## 5. プロパティ名のカスタマイズ

もし既存のプロパティ名が異なる場合は、`src/infrastructure/notion/notion_service.py`の以下の部分を変更してください：

```python
properties = {
    "タイトル": {  # あなたのタイトルプロパティ名に変更
        "title": [{"text": {"content": task.title}}],
    },
    "詳細": {  # あなたの詳細プロパティ名に変更
        "rich_text": [{"text": {"content": task.description}}],
    },
    "納期": {  # あなたの納期プロパティ名に変更
        "date": {"start": task.due_date.isoformat()},
    },
    "ステータス": {  # あなたのステータスプロパティ名に変更
        "select": {"name": self._get_status_name(task.status.value)},
    },
    "依頼者": {  # あなたの依頼者プロパティ名に変更
        "people": [{"object": "user", "id": requester_user["id"]}],
    },
    "依頼先": {  # あなたの依頼先プロパティ名に変更
        "people": [{"object": "user", "id": assignee_user["id"]}],
    },
}
```

## 6. 動作確認

1. Slackで `/task-request` コマンドを実行
2. タスクを作成して承認
3. Notionデータベースにタスクが追加されることを確認

## トラブルシューティング

### Notionユーザーが見つからない場合:
- Slack上のメールアドレスとNotionのメールアドレスが一致しているか確認
- Notionワークスペースに該当ユーザーが参加しているか確認

### データベースにアクセスできない場合:
- Integrationがデータベースに招待されているか確認
- データベースIDが正しいか確認

### プロパティが作成されない場合:
- プロパティ名が正確に一致しているか確認
- プロパティのタイプ（Text, Date, Select, Person）が正しいか確認