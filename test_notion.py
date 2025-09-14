#!/usr/bin/env python3
"""
Notion API接続テストスクリプト
"""
import os
import sys
from datetime import datetime
from dotenv import load_dotenv
from notion_client import Client

# 環境変数を読み込み
load_dotenv()

NOTION_TOKEN = os.getenv('NOTION_TOKEN')
DATABASE_ID = os.getenv('NOTION_DATABASE_ID')

def test_notion_connection():
    """Notion API接続テスト"""
    print("🔧 Notion API接続テスト開始")
    print(f"Token: {NOTION_TOKEN[:20]}..." if NOTION_TOKEN else "Token: None")
    print(f"Database ID: {DATABASE_ID}")
    print("-" * 50)

    if not NOTION_TOKEN:
        print("❌ NOTION_TOKEN が設定されていません")
        return False

    if not DATABASE_ID:
        print("❌ NOTION_DATABASE_ID が設定されていません")
        return False

    try:
        client = Client(auth=NOTION_TOKEN)

        # 1. データベース情報を取得
        print("📋 1. データベース情報取得テスト")
        try:
            database = client.databases.retrieve(database_id=DATABASE_ID)
            print(f"✅ データベース取得成功: {database['title'][0]['text']['content']}")

            # プロパティ一覧を表示
            print("\n📝 データベースプロパティ:")
            for prop_name, prop_info in database['properties'].items():
                prop_type = prop_info['type']
                print(f"  - {prop_name}: {prop_type}")

                # Selectプロパティの場合、オプションも表示
                if prop_type == 'select' and 'select' in prop_info:
                    options = [opt['name'] for opt in prop_info['select'].get('options', [])]
                    print(f"    オプション: {options}")

        except Exception as e:
            print(f"❌ データベース取得失敗: {e}")
            return False

        # 2. ユーザー一覧取得テスト
        print(f"\n👥 2. ユーザー一覧取得テスト")
        try:
            users = client.users.list()
            print(f"✅ ユーザー取得成功 ({len(users['results'])}人)")
            for user in users['results']:
                user_type = user.get('type', 'unknown')
                if user_type == 'person':
                    name = user.get('name', 'Unknown')
                    email = user.get('person', {}).get('email', 'No email')
                    print(f"  - {name} ({email})")

        except Exception as e:
            print(f"❌ ユーザー取得失敗: {e}")

        # 3. テストページ作成
        print(f"\n📄 3. テストページ作成テスト")
        try:
            test_properties = {
                "タイトル": {
                    "title": [{"text": {"content": f"テスト_{datetime.now().strftime('%H%M%S')}"}}]
                },
                "納期": {
                    "date": {"start": datetime.now().isoformat()}
                },
                "ステータス": {
                    "select": {"name": "承認待ち"}
                }
            }

            # 依頼者・依頼先がある場合は追加
            if 'properties' in locals() and database['properties'].get('依頼者'):
                # 最初のPersonユーザーを使用
                person_users = [u for u in users['results'] if u.get('type') == 'person']
                if person_users:
                    test_properties["依頼者"] = {
                        "people": [{"object": "user", "id": person_users[0]["id"]}]
                    }
                    if len(person_users) > 1:
                        test_properties["依頼先"] = {
                            "people": [{"object": "user", "id": person_users[1]["id"]}]
                        }

            page = client.pages.create(
                parent={"database_id": DATABASE_ID},
                properties=test_properties,
                children=[
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"type": "text", "text": {"content": "これはAPI接続テストです。"}}]
                        }
                    }
                ]
            )

            page_id = page["id"]
            print(f"✅ テストページ作成成功")
            print(f"   Page ID: {page_id}")
            print(f"   URL: https://www.notion.so/{page_id.replace('-', '')}")

            # 4. ページ更新テスト
            print(f"\n🔄 4. ページ更新テスト")
            client.pages.update(
                page_id=page_id,
                properties={
                    "ステータス": {"select": {"name": "承認済み"}}
                }
            )
            print("✅ ページ更新成功")

            return True

        except Exception as e:
            print(f"❌ ページ作成失敗: {e}")
            print(f"エラー詳細: {type(e).__name__}: {str(e)}")

            # プロパティエラーの場合の詳細
            if "property" in str(e).lower():
                print("\n🔧 プロパティエラーの可能性:")
                print("以下のプロパティが正しく設定されているか確認:")
                print("- タイトル (Title)")
                print("- 納期 (Date)")
                print("- ステータス (Select)")
                print("- 依頼者 (Person) - オプション")
                print("- 依頼先 (Person) - オプション")

            return False

    except Exception as e:
        print(f"❌ クライアント初期化失敗: {e}")
        return False


def main():
    """メイン関数"""
    success = test_notion_connection()

    print("\n" + "=" * 50)
    if success:
        print("🎉 Notion API接続テスト完了！")
        print("すべての機能が正常に動作しています。")
    else:
        print("❌ Notion API接続テストに問題があります。")
        print("上記のエラーメッセージを確認して設定を修正してください。")
        sys.exit(1)


if __name__ == "__main__":
    main()