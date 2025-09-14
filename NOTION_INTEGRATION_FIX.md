# 🔧 Notion Integration権限エラーの解決方法

## エラー内容
```
Could not find database with ID: 26e5c5c8-5ce8-800e-9400-e4c2421903c3.
Make sure the relevant pages and databases are shared with your integration.
```

## 🎯 解決手順

### Step 1: Notionデータベースページにアクセス

1. **ブラウザでNotionを開く**
2. **以下のURLにアクセス**:
   ```
   https://www.notion.so/26e5c5c85ce8800e9400e4c2421903c3
   ```

### Step 2: Integrationをデータベースに招待

1. **データベースページの右上「共有」ボタンをクリック**

2. **「招待」セクションで以下を実行**:
   - 検索ボックスに「**Task Request Bot**」と入力
   - または、作成したIntegration名を入力

3. **Integrationが表示されたら「招待」をクリック**

4. **権限が「編集可能」になっていることを確認**

### Step 3: Integration Tokenの確認

1. **Notion Integration設定ページ**を確認:
   - https://www.notion.so/my-integrations

2. **「Task Request Bot」をクリック**

3. **「Internal Integration Token」をコピー**
   - `secret_`で始まる長い文字列

4. **`.env`ファイルの`NOTION_TOKEN`を更新**:
   ```bash
   NOTION_TOKEN=secret_実際のトークン
   ```

### Step 4: データベースプロパティの確認

データベースに以下のプロパティが存在することを確認:

✅ **必須プロパティ**:
- [ ] **タイトル** (Title)
- [ ] **納期** (Date)
- [ ] **ステータス** (Select)
  - オプション: `承認待ち`, `承認済み`, `差し戻し`
- [ ] **依頼者** (Person)
- [ ] **依頼先** (Person)

### Step 5: 動作確認

1. **サーバーを再起動**:
   ```bash
   # Ctrl+C でサーバーを停止
   uv run main.py
   ```

2. **Slackで再度テスト**:
   - `/task-request` でタスクを作成
   - 承認ボタンをクリック
   - Notionデータベースにタスクが追加されるか確認

## 🔍 トラブルシューティング

### ❌ 依然としてエラーが発生する場合:

1. **データベースIDの確認**:
   - URL: `https://www.notion.so/26e5c5c85ce8800e9400e4c2421903c3`
   - ID: `26e5c5c85ce8800e9400e4c2421903c3`

2. **Integration名の確認**:
   - Notion設定ページで正確な名前を確認

3. **ワークスペースの確認**:
   - Integrationとデータベースが同じワークスペースにあるか

4. **権限レベルの確認**:
   - 「コメントのみ」ではなく「編集可能」になっているか

### 🔄 完全リセット方法:

1. **Integration削除** → **新規作成**
2. **新しいトークンで`.env`更新**
3. **データベースに再度招待**

## 📝 成功の確認方法

✅ エラーがなくなる
✅ コンソールに「⚠️ Notionページの作成に失敗しました」が表示されない
✅ Notionデータベースに新しいタスクページが作成される
✅ Slackで承認通知が正常に送信される