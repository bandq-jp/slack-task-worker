#!/usr/bin/env python3
"""
完全なSlack→Notionワークフローのテスト
- ゲストユーザーマッピングの動作確認
- タスク作成の完全テスト
- エラーハンドリングの確認
"""
import os
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from src.infrastructure.notion.notion_service import NotionService
from src.domain.entities.task import TaskRequest, TaskStatus

load_dotenv()

NOTION_TOKEN = os.getenv('NOTION_TOKEN')
DATABASE_ID = os.getenv('NOTION_DATABASE_ID')

async def test_user_mapping_workflow():
    """ユーザーマッピングワークフローのテスト"""
    print("🧪 ユーザーマッピングワークフロー テスト")
    print("=" * 60)

    notion_service = NotionService(NOTION_TOKEN, DATABASE_ID)

    # テスト対象のメールアドレス
    test_cases = [
        {
            'email': 'masuda.g@atoriba.jp',
            'description': 'ゲストユーザー1（マッピングファイル内）'
        },
        {
            'email': 'gals02513@gmail.com',
            'description': 'ゲストユーザー2（マッピングファイル内）'
        },
        {
            'email': 'f25c142e@mail.cc.niigata-u.ac.jp',
            'description': '正規メンバー（users.list()で取得可能）'
        },
        {
            'email': 'nonexistent@example.com',
            'description': '存在しないユーザー'
        }
    ]

    results = []

    for test_case in test_cases:
        email = test_case['email']
        description = test_case['description']

        print(f"\n🔍 テスト: {description}")
        print(f"   メール: {email}")
        print("-" * 40)

        try:
            user = await notion_service._find_user_by_email(email)

            if user:
                result = {
                    'email': email,
                    'found': True,
                    'user_id': user['id'],
                    'user_name': user['name'],
                    'method': 'unknown'  # ログから推測
                }
                print(f"✅ 成功: {user['name']} (ID: {user['id']})")
            else:
                result = {
                    'email': email,
                    'found': False,
                    'error': 'User not found'
                }
                print(f"❌ 失敗: ユーザーが見つかりません")

            results.append(result)

        except Exception as e:
            print(f"❌ エラー: {e}")
            results.append({
                'email': email,
                'found': False,
                'error': str(e)
            })

    # 結果サマリー
    print(f"\n📊 テスト結果サマリー:")
    print("-" * 60)
    successful = len([r for r in results if r.get('found')])
    total = len(results)
    print(f"   成功: {successful}/{total}")

    for result in results:
        status = "✅" if result.get('found') else "❌"
        print(f"   {status} {result['email']}")

    return results

async def test_task_creation_workflow():
    """タスク作成ワークフローのテスト"""
    print("\n🧪 タスク作成ワークフロー テスト")
    print("=" * 60)

    notion_service = NotionService(NOTION_TOKEN, DATABASE_ID)

    # テスト用タスクデータ
    test_task = TaskRequest(
        title="ゲストユーザー対応テスト",
        description={
            "type": "rich_text",
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": "これはゲストユーザーマッピングのテストタスクです。\n\n"},
                },
                {
                    "type": "text",
                    "text": {"content": "機能:"},
                    "annotations": {"bold": True}
                },
                {
                    "type": "text",
                    "text": {"content": "\n• マッピングファイルでの高速検索\n• フォールバック検索\n• 自動キャッシュ更新\n"}
                }
            ]
        },
        due_date=datetime.now() + timedelta(days=3),
        status=TaskStatus.PENDING
    )

    # テストケース
    test_cases = [
        {
            'requester_email': 'gals02513@gmail.com',  # ゲストユーザー
            'assignee_email': 'masuda.g@atoriba.jp',   # ゲストユーザー
            'description': 'ゲスト→ゲスト'
        },
        {
            'requester_email': 'masuda.g@atoriba.jp',         # ゲストユーザー
            'assignee_email': 'f25c142e@mail.cc.niigata-u.ac.jp',  # 正規メンバー
            'description': 'ゲスト→メンバー'
        }
    ]

    task_results = []

    for i, test_case in enumerate(test_cases, 1):
        requester_email = test_case['requester_email']
        assignee_email = test_case['assignee_email']
        description = test_case['description']

        print(f"\n📝 タスク作成テスト {i}: {description}")
        print(f"   依頼者: {requester_email}")
        print(f"   依頼先: {assignee_email}")
        print("-" * 40)

        try:
            # タスクタイトルを一意にする
            test_task.title = f"テスト{i}: {description} - {datetime.now().strftime('%H:%M:%S')}"

            # タスク作成実行
            page_id = await notion_service.create_task(
                task=test_task,
                requester_email=requester_email,
                assignee_email=assignee_email
            )

            if page_id:
                page_url = f"https://www.notion.so/{page_id.replace('-', '')}"
                print(f"✅ タスク作成成功!")
                print(f"   ページID: {page_id}")
                print(f"   URL: {page_url}")

                task_results.append({
                    'test_case': description,
                    'success': True,
                    'page_id': page_id,
                    'page_url': page_url
                })
            else:
                print(f"❌ タスク作成失敗: page_id が None")
                task_results.append({
                    'test_case': description,
                    'success': False,
                    'error': 'page_id is None'
                })

        except Exception as e:
            print(f"❌ タスク作成エラー: {e}")
            task_results.append({
                'test_case': description,
                'success': False,
                'error': str(e)
            })

    # タスク作成結果サマリー
    print(f"\n📊 タスク作成結果サマリー:")
    print("-" * 60)
    successful_tasks = len([r for r in task_results if r.get('success')])
    total_tasks = len(task_results)
    print(f"   成功: {successful_tasks}/{total_tasks}")

    for result in task_results:
        status = "✅" if result.get('success') else "❌"
        print(f"   {status} {result['test_case']}")
        if result.get('page_url'):
            print(f"      {result['page_url']}")

    return task_results

async def main():
    """メインテスト実行"""
    print("🎯 完全なSlack→Notionワークフロー テスト")
    print("=" * 60)

    try:
        # Phase 1: ユーザーマッピングテスト
        user_results = await test_user_mapping_workflow()

        # Phase 2: タスク作成テスト
        task_results = await test_task_creation_workflow()

        # 総合結果
        print(f"\n🎉 総合テスト結果:")
        print("=" * 60)

        user_success = len([r for r in user_results if r.get('found')])
        task_success = len([r for r in task_results if r.get('success')])

        print(f"   ユーザー検索: {user_success}/{len(user_results)} 成功")
        print(f"   タスク作成:   {task_success}/{len(task_results)} 成功")

        if user_success == len(user_results) - 1 and task_success == len(task_results):  # -1 は存在しないユーザーテスト分
            print(f"\n🎉 すべてのテストが成功しました！")
            print(f"💡 ゲストユーザー対応システムが正常に動作しています")
        else:
            print(f"\n⚠️ 一部テストに問題があります")

    except Exception as e:
        print(f"❌ テスト実行エラー: {e}")

if __name__ == "__main__":
    asyncio.run(main())