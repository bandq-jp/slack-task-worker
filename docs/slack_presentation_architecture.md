# Slack Presentation Layer Architecture

2024-06 更新で `src/presentation/api/slack_endpoints.py` の肥大化を解消し、以下のように役割を分割しました。

- `src/presentation/api/slack/context.py`
  - Slack / Notion / Task サービスなどの依存オブジェクトを組み立て、`SlackDependencies` として提供。
- `src/presentation/api/slack/config.py`
  - Pydantic 設定クラス `Settings` を定義し、プレゼンテーション層から環境値を参照できるようにしたもの。
- `src/presentation/api/slack/actions/approval_actions.py`
  - 承認ボタン押下のハンドリングを担当。処理中モーダルの表示と、成功・失敗の結果更新をまとめて実装。
  - タスク情報がメモリに存在しない場合でも、Notion スナップショットと Slack メール検索から復元して処理を継続。
- `src/presentation/api/slack/actions/extension_actions.py`
  - 延期申請モーダルの送信に加え、承認／却下ボタンの処理も担当。すべてのフローでローディングモーダル → 完了メッセージの流れを統一。
- `src/presentation/api/slack_endpoints.py`
  - ルーター初期化とルーティングの割当のみを担当し、実際の処理は各モジュールへ委譲。

加えて承認ボタンは、クリック直後にローディングモーダルを表示し、完了時にメッセージを更新するように改善しています。これにより、同時押下でもユーザーへ即フィードバックが返り、完了時に状態が明示的に伝わるようになりました。

今後、新しいインタラクションを追加する場合も `actions/` 配下にハンドラーを追加し、`context.py` で依存を組み立てて利用してください。
