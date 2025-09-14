# 🚀 Cloud Run デプロイガイド

このガイドでは、Slack-Notion Task Management SystemをGoogle Cloud Runにデプロイする方法を説明します。

## 🎯 Cloud Run対応の特徴

- **ステートレス対応**: ユーザーマッピングをGoogle Cloud Storageに保存
- **自動環境判定**: ローカル開発時はローカルファイル、Cloud Run時はGCS使用
- **高速キャッシュ**: メモリ内キャッシュでGCSアクセスを最適化
- **自動スケーリング**: トラフィックに応じて自動でスケール

## 📋 前提条件

### 必要なツール
- Google Cloud CLI (`gcloud`)
- Docker
- uv (Python package manager)

### Google Cloudの設定
```bash
# Google Cloud CLIにログイン
gcloud auth login

# プロジェクトを設定
gcloud config set project YOUR_PROJECT_ID

# 必要なAPIを有効化
gcloud services enable run.googleapis.com storage.googleapis.com
```

## 🔧 デプロイ手順

### Step 1: 依存関係の追加

```bash
# Google Cloud Storage クライアントを追加
uv add google-cloud-storage
```

### Step 2: サービスアカウントの作成

```bash
# サービスアカウント作成
gcloud iam service-accounts create slack-notion-service \
  --display-name "Slack Notion Task Service"

# Cloud Storage権限を付与
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:slack-notion-service@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.admin"

# サービスアカウントキーをダウンロード（ローカル開発用）
gcloud iam service-accounts keys create service-account-key.json \
  --iam-account=slack-notion-service@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

### Step 3: GCSバケットの作成

```bash
# バケット作成（グローバルに一意な名前を指定）
export BUCKET_NAME="slack-notion-mappings-$(date +%s)"
gsutil mb gs://$BUCKET_NAME

# バケット名を環境変数に追加
echo "GCS_BUCKET_NAME=$BUCKET_NAME" >> .env
```

### Step 4: ユーザーマッピングのデプロイ

```bash
# ローカルマッピングファイルをGCSにデプロイ
python admin/deploy_mapping_to_gcs.py \
  --bucket $BUCKET_NAME \
  --local-file .user_mapping.json \
  --service-account service-account-key.json

# デプロイ確認
python admin/deploy_mapping_to_gcs.py \
  --bucket $BUCKET_NAME \
  --verify-only \
  --service-account service-account-key.json
```

### Step 5: Dockerイメージのビルド・プッシュ

```bash
# プロジェクトIDを設定
export PROJECT_ID="your-gcp-project-id"

# Artifact Registryリポジトリ作成
gcloud artifacts repositories create slack-notion-repo \
  --repository-format=docker \
  --location=asia-northeast1

# Docker認証設定
gcloud auth configure-docker asia-northeast1-docker.pkg.dev

# イメージビルド
docker build -t asia-northeast1-docker.pkg.dev/$PROJECT_ID/slack-notion-repo/slack-notion-task:latest .

# イメージプッシュ
docker push asia-northeast1-docker.pkg.dev/$PROJECT_ID/slack-notion-repo/slack-notion-task:latest
```

### Step 6: Cloud Runサービスのデプロイ

```bash
# 環境変数を読み込み
source .env

# Cloud Runサービスデプロイ
gcloud run deploy slack-notion-task \
  --image asia-northeast1-docker.pkg.dev/$PROJECT_ID/slack-notion-repo/slack-notion-task:latest \
  --platform managed \
  --region asia-northeast1 \
  --allow-unauthenticated \
  --service-account slack-notion-service@$PROJECT_ID.iam.gserviceaccount.com \
  --set-env-vars "SLACK_BOT_TOKEN=$SLACK_BOT_TOKEN,SLACK_SIGNING_SECRET=$SLACK_SIGNING_SECRET,NOTION_TOKEN=$NOTION_TOKEN,NOTION_DATABASE_ID=$NOTION_DATABASE_ID,GCS_BUCKET_NAME=$GCS_BUCKET_NAME" \
  --memory 1Gi \
  --cpu 1 \
  --concurrency 100 \
  --timeout 300 \
  --max-instances 10
```

### Step 7: Slack Appの更新

デプロイ完了後、Cloud RunのURLを使用してSlack Appの設定を更新：

```bash
# Cloud RunのURLを取得
gcloud run services describe slack-notion-task \
  --platform managed \
  --region asia-northeast1 \
  --format 'value(status.url)'
```

**Slack App設定で以下を更新:**
- Slash Commands: `{CLOUD_RUN_URL}/slack/commands`
- Interactivity & Shortcuts: `{CLOUD_RUN_URL}/slack/interactive`

## 🔍 運用・監視

### ログの確認
```bash
# リアルタイムログ
gcloud run services logs tail slack-notion-task \
  --platform managed \
  --region asia-northeast1

# 特定時間のログ
gcloud run services logs read slack-notion-task \
  --platform managed \
  --region asia-northeast1 \
  --since=2024-01-01
```

### GCSマッピングファイルの管理

```bash
# 現在のマッピング確認
python admin/deploy_mapping_to_gcs.py \
  --bucket $BUCKET_NAME \
  --verify-only

# ローカル更新後にGCS同期
python admin/deploy_mapping_to_gcs.py \
  --bucket $BUCKET_NAME \
  --local-file .user_mapping.json
```

### スケーリング調整
```bash
# 最大インスタンス数の調整
gcloud run services update slack-notion-task \
  --platform managed \
  --region asia-northeast1 \
  --max-instances 20

# メモリ・CPU調整
gcloud run services update slack-notion-task \
  --platform managed \
  --region asia-northeast1 \
  --memory 2Gi \
  --cpu 2
```

## 🛠️ トラブルシューティング

### 1. GCSアクセスエラー
```bash
# サービスアカウントの権限確認
gcloud projects get-iam-policy YOUR_PROJECT_ID \
  --filter="bindings.members:serviceAccount:slack-notion-service@YOUR_PROJECT_ID.iam.gserviceaccount.com"

# バケットのアクセス権限確認
gsutil iam get gs://$BUCKET_NAME
```

### 2. マッピングファイルが空
```bash
# GCSファイルの存在確認
gsutil ls -l gs://$BUCKET_NAME/

# ファイル内容確認
gsutil cat gs://$BUCKET_NAME/user_mapping.json | jq .
```

### 3. 環境変数の確認
```bash
# Cloud Runサービスの環境変数表示
gcloud run services describe slack-notion-task \
  --platform managed \
  --region asia-northeast1 \
  --format 'value(spec.template.spec.template.spec.containers[0].env[].name,spec.template.spec.template.spec.containers[0].env[].value)'
```

## 💰 コスト最適化

### 1. リソース調整
- **CPU**: 基本は1CPU、高負荷時のみ2CPU
- **メモリ**: 1Giで十分、大量ユーザーの場合2Gi
- **最大インスタンス**: 10-20程度で設定

### 2. GCS最適化
- **Storage Class**: Standard（頻繁アクセス）
- **バージョニング**: 無効（コスト削減）
- **ライフサイクル**: 古いバックアップの自動削除

### 3. モニタリング
```bash
# 使用量確認
gcloud run services describe slack-notion-task \
  --platform managed \
  --region asia-northeast1 \
  --format 'value(status.traffic[].latestRevision,status.traffic[].percent)'
```

## 🔄 自動デプロイ（オプション）

GitHub Actionsを使用した自動デプロイの設定例：

```yaml
# .github/workflows/deploy.yml
name: Deploy to Cloud Run
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: google-github-actions/auth@v1
        with:
          credentials_json: ${{ secrets.GCP_SA_KEY }}
      - name: Deploy to Cloud Run
        run: |
          gcloud run deploy slack-notion-task \
            --image gcr.io/$PROJECT_ID/slack-notion-task:$GITHUB_SHA \
            --platform managed \
            --region asia-northeast1
```

これでCloud Runへの完全なデプロイが完了します！