# Concurrency Handling Update (2025-10)

このシステムでは、Slack からの同時操作（複数人によるボタン連打やリマインダー処理の競合など）で処理が衝突し、Notion や Slack への更新が失敗するケースがありました。  
そのため以下の変更を加えており、今後の開発でも同じ仕組みを利用してください。

## 追加した仕組み

### `ConcurrencyCoordinator`
- 実装場所: `src/utils/concurrency.py`
- グローバルな同時実行数を制限する `Semaphore` と、リソースごとの `asyncio.Lock` を組み合わせた調停クラス。
- `guard(key)` を使うことで、同じキー（例: Notion ページID）に対する処理が同時に走らないようにできる。

```python
from src.utils.concurrency import ConcurrencyCoordinator

concurrency = ConcurrencyCoordinator(max_concurrency=6)

async with concurrency.guard(page_id):
    # page_id 単位で排他制御される処理
    await notion_service.update_task_status(...)
```

### `TaskApplicationService` への組み込み
- `ConcurrencyCoordinator` を注入できるようにし、タスクの承認 / 再依頼処理では必ずロックを取得してから Notion と Slack へアクセス。
- これにより、複数人が同じタスクに対して同時にボタンを押しても、処理順序が保証される。

### Slack エンドポイントでの利用
- `src/presentation/api/slack_endpoints.py` で共有インスタンス `task_concurrency` を生成。
- 現時点では以下のハンドラーでロックを取得するように変更済み:
  - 承認ボタン (`approve_task`)
  - 延期却下 (`reject_extension_request`)
- 今後、完了承認・延期承認・リマインダー系など他の処理にも同じロックを広げることを想定。

## 使い方のガイドライン

1. **同じ Notion ページや Slack メッセージを更新する処理** は、必ず同じキーを指定して `guard(key)` で囲む。
2. **イベントループをブロックする処理** は極力避ける。必要であれば `asyncio.to_thread` 等を使ってオフロードする。
3. 新しいフローを追加するときは、`task_concurrency` を再利用するか、用途に合わせた Coordinator を注入する。

## 今後の TODO

- 延期承認 / 完了承認 など、まだロック未対応のハンドラーへ適用範囲を拡張する。（延長申請送信・承認・却下はロック対応済み）
- Slack SDK の同期 API を `asyncio.to_thread` でラップし、I/O 待ち中にイベントループが詰まらないように調整する。
- ロングラン処理のモーダル化: 承認フローでは導入済み。完了承認など他フローにも適用範囲を広げる。

ドキュメントやコードレビュー時は、本ページを参照して同一方針で実装を進めてください。
