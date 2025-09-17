# Google Calendar連携セットアップガイド

このガイドでは、タスク承認時にGoogleカレンダーのタスクに自動追加する機能のセットアップ方法を説明します。

## 📋 前提条件

- Google Cloud Platform (GCP) アカウント
- プロジェクトの作成権限
- Google Workspace管理者権限（ドメイン全体の委任を設定する場合）

## 🔧 GCP設定

### 1. APIの有効化

GCP コンソールで以下のAPIを有効化してください：

1. **Google Calendar API**
   - カレンダーイベントの作成に使用

2. **Google Tasks API**
   - タスクリストへのタスク追加に使用

### 2. サービスアカウントの作成

1. GCPコンソールで「IAMと管理」→「サービスアカウント」を開く
2. 「サービスアカウントを作成」をクリック
3. 以下の情報を入力：
   - サービスアカウント名: `slack-task-worker`
   - サービスアカウントID: 自動生成される
   - 説明: Slack-Notionタスク管理システム用

4. 「作成して続行」をクリック
5. ロールは特に必要なし（ドメイン全体の委任を使用するため）
6. 「完了」をクリック

### 3. 認証キーの作成

1. 作成したサービスアカウントをクリック
2. 「キー」タブを選択
3. 「鍵を追加」→「新しい鍵を作成」
4. JSON形式を選択して「作成」
5. JSONファイルがダウンロードされる（重要: このファイルは再ダウンロードできません）

### 4. ドメイン全体の委任設定

Google Workspaceで他のユーザーのカレンダーにタスクを追加するため、ドメイン全体の委任が必要です。

1. サービスアカウントの詳細ページで「詳細」タブを開く
2. 「クライアントID」をコピー
3. Google Admin Console (admin.google.com) にログイン
4. 「セキュリティ」→「アクセスとデータ管理」→「API の制御」を開く
5. 「ドメイン全体の委任を管理」をクリック
6. 「新しく追加」をクリック
7. 以下を入力：
   - クライアントID: コピーしたID
   - OAuth スコープ:
     ```
     https://www.googleapis.com/auth/calendar,
     https://www.googleapis.com/auth/tasks
     ```
8. 「承認」をクリック

## 🚀 アプリケーション設定

### ローカル環境

1. ダウンロードしたJSONファイルを安全な場所に配置
   ```bash
   cp ~/Downloads/your-service-account.json ./secrets/service-account.json
   chmod 600 ./secrets/service-account.json
   ```

2. `.env`ファイルに設定を追加：
   ```env
   # Google Calendar Integration
   SERVICE_ACCOUNT_JSON=./secrets/service-account.json
   ENV=local
   ```

### 本番環境（Cloud Run）

1. Secret Managerにサービスアカウントキーを保存：
   ```bash
   gcloud secrets create slack-task-worker-sa-key \
     --data-file=./secrets/service-account.json
   ```

2. Cloud Runデプロイ時に環境変数を設定：
   ```bash
   # JSONファイルの内容を環境変数として設定
   export SA_JSON=$(cat ./secrets/service-account.json)

   gcloud run deploy slack-notion-task \
     --image gcr.io/your-project/slack-notion-task \
     --set-env-vars "SERVICE_ACCOUNT_JSON=$SA_JSON,ENV=production" \
     --region asia-northeast1
   ```

   または、Secret Managerを使用：
   ```bash
   gcloud run deploy slack-notion-task \
     --image gcr.io/your-project/slack-notion-task \
     --set-secrets="SERVICE_ACCOUNT_JSON=slack-task-worker-sa-key:latest" \
     --set-env-vars "ENV=production" \
     --region asia-northeast1
   ```

## ✅ 動作確認

1. アプリケーションを起動
2. Slackでタスクを作成
3. 承認ボタンを押す
4. 以下を確認：
   - Slackに「Googleカレンダーのタスクに追加しました」と表示される
   - Googleカレンダーのタスクリストにタスクが追加される

## 🔍 トラブルシューティング

### エラー: 権限が不足しています

- ドメイン全体の委任が正しく設定されていることを確認
- サービスアカウントのクライアントIDが正しいことを確認
- スコープが正しく設定されていることを確認

### エラー: ユーザーのメールアドレスが見つかりません

- Slackユーザーのプロフィールにメールアドレスが設定されていることを確認
- Slack APIの`users:read.email`スコープが有効になっていることを確認

### エラー: タスクの作成に失敗しました

- Google Tasks APIが有効になっていることを確認
- ユーザーがGoogle Workspaceアカウントを持っていることを確認
- サービスアカウントに正しい権限が付与されていることを確認

## 📝 注意事項

- サービスアカウントのJSONキーは機密情報です。Gitリポジトリにコミットしないでください
- 本番環境では必ずSecret Managerなどの安全な方法でキーを管理してください
- ドメイン全体の委任は強力な権限です。最小限の必要なスコープのみを付与してください

## 🔗 関連ドキュメント

- [Google Calendar API Documentation](https://developers.google.com/calendar)
- [Google Tasks API Documentation](https://developers.google.com/tasks)
- [Service Account Documentation](https://cloud.google.com/iam/docs/service-accounts)
- [Domain-wide Delegation](https://developers.google.com/admin-sdk/directory/v1/guides/delegation)