# 🔐 認証付きCloud RunでのSlack連携設定

Google Cloud Runで認証を有効にしている場合の、Slack App連携設定方法を説明します。

## 🎯 利用可能な方法

### 方法1: Google Cloud Endpoints + API Key（推奨）

最も簡単で安全な方法です。

#### Step 1: Cloud Endpoints設定ファイル作成

```yaml
# swagger.yaml
swagger: "2.0"
info:
  title: "Slack Task Worker API"
  description: "API for Slack Task Management System"
  version: "1.0.0"
host: "your-service-name-hash-uc.a.run.app"
schemes:
  - "https"
basePath: "/"

securityDefinitions:
  api_key:
    type: "apiKey"
    name: "key"
    in: "query"

security:
  - api_key: []

paths:
  /slack/commands:
    post:
      operationId: "slack_commands"
      security: []  # パブリックアクセス
      responses:
        200:
          description: "Success"
  /slack/interactive:
    post:
      operationId: "slack_interactive"
      security: []  # パブリックアクセス
      responses:
        200:
          description: "Success"
  /**:
    get:
      operationId: "catch_all"
      responses:
        200:
          description: "Success"
```

#### Step 2: Cloud Endpointsデプロイ

```bash
# Cloud Endpoints設定をデプロイ
gcloud endpoints services deploy swagger.yaml

# 設定名を取得
export ENDPOINTS_SERVICE_NAME=$(gcloud endpoints services list --format="value(serviceName)" --filter="title:Slack Task Worker API")
echo "Endpoints service: $ENDPOINTS_SERVICE_NAME"
```

#### Step 3: Cloud Runサービス更新

```bash
# Cloud RunにCloud Endpointsを統合
gcloud run deploy slack-notion-task \
  --image asia-northeast1-docker.pkg.dev/$PROJECT_ID/slack-notion-repo/slack-notion-task:latest \
  --platform managed \
  --region asia-northeast1 \
  --allow-unauthenticated \
  --set-env-vars "ENDPOINTS_SERVICE_NAME=$ENDPOINTS_SERVICE_NAME" \
  --service-account slack-notion-service@$PROJECT_ID.iam.gserviceaccount.com
```

### 方法2: Cloud Load Balancer + IAP（高セキュリティ）

企業レベルのセキュリティが必要な場合。

#### Step 1: Global Load Balancer作成

```bash
# 静的IPアドレス予約
gcloud compute addresses create slack-lb-ip --global

# HTTPSロードバランサー作成
gcloud compute backend-services create slack-backend \
  --protocol HTTP \
  --health-checks-region asia-northeast1 \
  --global

# Cloud Runサービスをバックエンドに追加
gcloud compute backend-services add-backend slack-backend \
  --network-endpoint-group=slack-neg \
  --network-endpoint-group-region=asia-northeast1 \
  --global
```

#### Step 2: Identity-Aware Proxy (IAP) 設定

```bash
# IAP有効化
gcloud iap web enable \
  --resource-type=backend-services \
  --service=slack-backend

# Slackからのアクセス許可（特定IPアドレス）
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="user:slack-service@slack.com" \
  --role="roles/iap.httpsResourceAccessor"
```

### 方法3: Cloud Runプロキシサービス（シンプル）

最も実装が簡単な方法。

#### Step 1: パブリックプロキシサービス作成

```python
# proxy-service.py
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response
import httpx
import os
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import service_account
import google.auth

app = FastAPI()

# 認証情報設定
SCOPES = ['https://www.googleapis.com/auth/cloud-platform']
TARGET_SERVICE_URL = os.getenv('TARGET_SERVICE_URL')  # 認証付きCloud Run URL

def get_auth_token():
    """サービスアカウントトークン取得"""
    credentials, project = google.auth.default(scopes=SCOPES)
    credentials.refresh(GoogleRequest())
    return credentials.token

@app.post("/slack/commands")
@app.post("/slack/interactive")
async def proxy_slack_requests(request: Request):
    """SlackリクエストをCloud Runにプロキシ"""
    try:
        # 認証トークン取得
        token = get_auth_token()
        
        # オリジナルリクエストボディ取得
        body = await request.body()
        
        # 認証付きでCloud Runに転送
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": request.headers.get("Content-Type"),
            "X-Forwarded-For": request.client.host,
        }
        
        # リクエスト転送
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{TARGET_SERVICE_URL}{request.url.path}",
                content=body,
                headers=headers,
                timeout=30.0
            )
            
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=dict(response.headers)
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
```

#### Step 2: プロキシサービスデプロイ

```dockerfile
# proxy.Dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY proxy-service.py .
COPY requirements-proxy.txt .

RUN pip install -r requirements-proxy.txt

EXPOSE 8080
CMD ["python", "proxy-service.py"]
```

```bash
# プロキシサービスビルド・デプロイ
docker build -f proxy.Dockerfile -t slack-proxy .
docker tag slack-proxy asia-northeast1-docker.pkg.dev/$PROJECT_ID/slack-notion-repo/slack-proxy:latest
docker push asia-northeast1-docker.pkg.dev/$PROJECT_ID/slack-notion-repo/slack-proxy:latest

# プロキシをパブリックでデプロイ
gcloud run deploy slack-proxy \
  --image asia-northeast1-docker.pkg.dev/$PROJECT_ID/slack-notion-repo/slack-proxy:latest \
  --platform managed \
  --region asia-northeast1 \
  --allow-unauthenticated \
  --set-env-vars "TARGET_SERVICE_URL=https://your-auth-service-url" \
  --service-account slack-notion-service@$PROJECT_ID.iam.gserviceaccount.com
```

## 🔧 設定手順（方法3推奨）

### 1. 現在の認証付きサービスを維持

```bash
# 現在のサービスはそのまま（認証必要）
gcloud run deploy slack-notion-task \
  --image asia-northeast1-docker.pkg.dev/$PROJECT_ID/slack-notion-repo/slack-notion-task:latest \
  --platform managed \
  --region asia-northeast1 \
  --no-allow-unauthenticated \  # 認証必要
  --service-account slack-notion-service@$PROJECT_ID.iam.gserviceaccount.com
```

### 2. プロキシサービス作成

```python
# src/proxy/main.py
from fastapi import FastAPI, Request
from fastapi.responses import Response
import httpx
import os
from google.auth import default
from google.auth.transport.requests import Request as GoogleRequest

app = FastAPI()

credentials, project = default()
TARGET_URL = os.getenv('TARGET_SERVICE_URL')

@app.api_route("/slack/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_to_auth_service(request: Request, path: str):
    # 認証トークン取得
    credentials.refresh(GoogleRequest())
    token = credentials.token
    
    # リクエスト転送
    body = await request.body() if request.method in ["POST", "PUT"] else None
    
    headers = dict(request.headers)
    headers["Authorization"] = f"Bearer {token}"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.request(
            method=request.method,
            url=f"{TARGET_URL}/slack/{path}",
            content=body,
            headers=headers,
            params=dict(request.query_params)
        )
    
    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=dict(response.headers)
    )
```

### 3. Slack App設定更新

```
Request URL (Commands): https://your-proxy-service-url/slack/commands
Request URL (Interactive): https://your-proxy-service-url/slack/interactive
```

## 📊 各方法の比較

| 方法 | セキュリティ | 実装難易度 | コスト | 推奨度 |
|------|-------------|-----------|--------|---------|
| Cloud Endpoints | 高 | 中 | 低 | ★★★★☆ |
| Load Balancer + IAP | 最高 | 高 | 高 | ★★★☆☆ |
| プロキシサービス | 中〜高 | 低 | 最低 | ★★★★★ |

## 🚨 セキュリティ考慮事項

### 1. ネットワークセキュリティ

```bash
# VPCファイアウォール設定
gcloud compute firewall-rules create allow-slack-webhook \
  --allow tcp:443 \
  --source-ranges 0.0.0.0/0 \  # Slackからの接続許可
  --target-tags slack-proxy
```

### 2. ログ監視

```bash
# Cloud Loggingでアクセス監視
gcloud logging sinks create slack-audit-sink \
  bigquery.googleapis.com/projects/$PROJECT_ID/datasets/slack_audit \
  --log-filter='resource.type="cloud_run_revision" AND jsonPayload.path:"/slack/"'
```

### 3. レート制限

```python
# プロキシサービスにレート制限追加
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.post("/slack/commands")
@limiter.limit("10/minute")  # 1分間に10リクエスト制限
async def proxy_commands(request: Request):
    # プロキシ処理
```

## 🎯 推奨構成

**本番環境では方法3（プロキシサービス）を推奨**：

1. **シンプル**: 実装・運用が簡単
2. **低コスト**: 追加のインフラ不要
3. **柔軟**: カスタム認証ロジック追加可能
4. **監査**: すべてのリクエストをプロキシ経由で記録

この方法で、Slackからの接続を安全に受け付けながら、メインアプリケーションは認証保護されたままにできます。

## 🚀 クイックスタート

```bash
# 1. プロキシサービス作成
mkdir src/proxy
# 上記のmain.pyを作成

# 2. デプロイ
gcloud run deploy slack-proxy \
  --source src/proxy \
  --platform managed \
  --region asia-northeast1 \
  --allow-unauthenticated \
  --set-env-vars "TARGET_SERVICE_URL=https://your-auth-service-url"

# 3. Slack App設定更新
# Request URLs をプロキシサービスのURLに変更
```

これで認証付きCloud Runサービスへの安全なSlack連携が完了します！