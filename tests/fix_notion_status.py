#!/usr/bin/env python3
"""
Notionステータスプロパティ修正スクリプト
"""
import os
from dotenv import load_dotenv
from notion_client import Client

# 環境変数を読み込み
load_dotenv()

NOTION_TOKEN = os.getenv('NOTION_TOKEN')
DATABASE_ID = os.getenv('NOTION_DATABASE_ID')

def check_status_options():
    """ステータスプロパティのオプションを確認・修正"""
    print("🔧 Notionステータスプロパティチェック")

    client = Client(auth=NOTION_TOKEN)

    # データベース情報を取得
    database = client.databases.retrieve(database_id=DATABASE_ID)

    print(f"データベース名: {database['title'][0]['text']['content']}")

    # ステータスプロパティを確認
    status_prop = database['properties'].get('ステータス')
    if not status_prop:
        print("❌ 'ステータス' プロパティが見つかりません")
        return

    print(f"ステータスプロパティタイプ: {status_prop['type']}")

    if status_prop['type'] == 'status':
        # statusタイプの場合
        status_options = status_prop.get('status', {}).get('options', [])
        print(f"現在のステータスオプション ({len(status_options)}個):")

        for opt in status_options:
            print(f"  - {opt['name']} (ID: {opt['id']})")

        # 必要なオプションを確認
        required_options = ['承認待ち', '承認済み', '差し戻し']
        existing_names = [opt['name'] for opt in status_options]

        print(f"\n必要なオプション: {required_options}")
        print(f"不足しているオプション: {[opt for opt in required_options if opt not in existing_names]}")

        # 最初のオプション名を使ってテストページ作成を試行
        if status_options:
            first_option = status_options[0]['name']
            print(f"\nテスト: '{first_option}' でページ作成を試行")

            try:
                from datetime import datetime

                page = client.pages.create(
                    parent={"database_id": DATABASE_ID},
                    properties={
                        "タイトル": {
                            "title": [{"text": {"content": f"修正テスト_{datetime.now().strftime('%H%M%S')}"}}]
                        },
                        "納期": {
                            "date": {"start": datetime.now().isoformat()}
                        },
                        "ステータス": {
                            "status": {"name": first_option}
                        }
                    }
                )

                print(f"✅ ページ作成成功！")
                print(f"   URL: https://www.notion.so/{page['id'].replace('-', '')}")
                return True

            except Exception as e:
                print(f"❌ ページ作成失敗: {e}")
        else:
            print("❌ ステータスオプションが設定されていません")

    elif status_prop['type'] == 'select':
        # selectタイプの場合
        select_options = status_prop.get('select', {}).get('options', [])
        print(f"現在のセレクトオプション ({len(select_options)}個):")

        for opt in select_options:
            print(f"  - {opt['name']}")

        if select_options:
            first_option = select_options[0]['name']
            print(f"\nテスト: '{first_option}' でページ作成を試行")

            try:
                from datetime import datetime

                page = client.pages.create(
                    parent={"database_id": DATABASE_ID},
                    properties={
                        "タイトル": {
                            "title": [{"text": {"content": f"修正テスト_{datetime.now().strftime('%H%M%S')}"}}]
                        },
                        "納期": {
                            "date": {"start": datetime.now().isoformat()}
                        },
                        "ステータス": {
                            "select": {"name": first_option}
                        }
                    }
                )

                print(f"✅ ページ作成成功！")
                print(f"   URL: https://www.notion.so/{page['id'].replace('-', '')}")
                return True

            except Exception as e:
                print(f"❌ ページ作成失敗: {e}")

    return False

if __name__ == "__main__":
    check_status_options()