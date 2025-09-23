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
2. **納期** (Date) - 日付
3. **ステータス** (Select) - セレクトボックス
   - オプション: `承認待ち`, `承認済み`, `差し戻し`
4. **依頼者** (Person) - 人物
5. **依頼先** (Person) - 人物

### オプションプロパティ:
6. **差し戻し理由** (Text) - リッチテキスト

### リマインド / 延期ワークフロー用プロパティ（新機能）
以下を追加することで自動リマインド・延期申請・評価連動が機能します。

1. **リマインドフェーズ** (Select)
   - オプション: `未送信`, `期日前`, `当日`, `超過`, `既読`
2. **リマインド既読** (Checkbox)
3. **最終リマインド日時** (Date & Time)
4. **最終既読日時** (Date & Time)
5. **延期ステータス** (Select)
   - オプション: `なし`, `申請中`, `承認済`, `却下`
6. **延期期日（申請中）** (Date & Time)
7. **延期理由（申請中）** (Rich text)
8. **納期超過ポイント** (Number)

> Notion上で「依頼先」ごとに本数値を合計するギャラリービューやボードビューを作成すると、評価ポイントの集計が簡単になります。

**注意**: タスクの詳細内容はプロパティではなく、ページ本文に記述されます。

### データベースプロパティ作成手順:
1. データベースページを開く
2. 右上の「...」メニュー → 「プロパティを編集」
3. 各プロパティを上記の通り追加/変更

## 3. 監査ログ用データベースの作成（推奨）

自動リマインド、既読、延期申請の履歴を保管するために、Notionで新規データベースを作成してください。例: **タスク監査ログ**。

### 監査ログデータベースのプロパティ
1. **イベント** (Title)
2. **関連タスク** (Relation) - タスク本体のデータベースを対象にする
3. **種別** (Select) - 例: `リマインド送信`, `リマインド既読`, `延期申請`, `延期承認`, `延期却下`, `期限超過`
4. **詳細** (Rich text)
5. **実施者** (People)
6. **日時** (Date & Time)

作成後、メインのタスクデータベースと相互にリレーションを張り、`.env` に `NOTION_AUDIT_DATABASE_ID` を設定してください。

## 4. データベースへのアクセス許可

### Step 3: Integrationにデータベースアクセスを許可
1. データベースページで右上の「共有」をクリック
2. 「招待」セクションで作成したIntegration「Task Request Bot」を検索
3. 「招待」をクリック

## 5. 環境変数の設定

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

## 6. プロパティ名のカスタマイズ

もし既存のプロパティ名が異なる場合は、`src/infrastructure/notion/dynamic_notion_service.py`の以下の部分を変更してください：

```python
properties = {
    "タイトル": {  # あなたのタイトルプロパティ名に変更
        "title": [{"text": {"content": task.title}}],
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

**重要**: タスクの詳細内容（description）はプロパティではなく、ページ本文に記載されます。

## 7. 動作確認

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
