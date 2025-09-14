#!/usr/bin/env python3
"""
ゲストユーザーをPeopleプロパティに直接設定するテスト
"""
import os
from datetime import datetime
from dotenv import load_dotenv
from notion_client import Client

load_dotenv()

NOTION_TOKEN = os.getenv('NOTION_TOKEN')
DATABASE_ID = os.getenv('NOTION_DATABASE_ID')

def test_direct_guest_assignment():
    """発見されたゲストユーザーIDを直接使用してページ作成"""
    print("🔍 ゲストユーザー直接設定テスト")
    print("-" * 50)

    client = Client(auth=NOTION_TOKEN)

    # 調査で判明したゲストユーザーID
    guest_users = {
        'masuda.g@atoriba.jp': '26ed872b-594c-81e7-9b0e-00023e38ab93',
        'gals02513@gmail.com': '26ed872b-594c-81b0-9b7c-0002c2b07e9b'
    }

    try:
        # ゲストユーザーIDを直接指定してページ作成
        page = client.pages.create(
            parent={"database_id": DATABASE_ID},
            properties={
                "タイトル": {
                    "title": [{"text": {"content": "ゲストユーザー設定テスト"}}]
                },
                "納期": {
                    "date": {"start": datetime.now().isoformat()}
                },
                "ステータス": {
                    "status": {"name": "承認待ち"}
                },
                "依頼者": {
                    "people": [
                        {
                            "object": "user",
                            "id": guest_users['gals02513@gmail.com']
                        }
                    ]
                },
                "依頼先": {
                    "people": [
                        {
                            "object": "user",
                            "id": guest_users['masuda.g@atoriba.jp']
                        }
                    ]
                }
            }
        )

        page_id = page["id"]
        print(f"✅ ページ作成成功: https://www.notion.so/{page_id.replace('-', '')}")

        # 作成されたページのプロパティを確認
        created_page = client.pages.retrieve(page_id=page_id)

        # 依頼者プロパティ確認
        requester = created_page['properties']['依頼者']['people']
        if requester:
            print(f"✅ 依頼者設定成功: {requester[0]['name']} ({requester[0].get('person', {}).get('email', 'No email')})")

        # 依頼先プロパティ確認
        assignee = created_page['properties']['依頼先']['people']
        if assignee:
            print(f"✅ 依頼先設定成功: {assignee[0]['name']} ({assignee[0].get('person', {}).get('email', 'No email')})")

    except Exception as e:
        print(f"❌ エラー: {e}")

def test_email_to_user_id_mapping():
    """メールアドレスからユーザーIDへのマッピングをテスト"""
    print("\n🔍 メール->ユーザーIDマッピングテスト")
    print("-" * 50)

    client = Client(auth=NOTION_TOKEN)

    # 既知のページからユーザー情報を逆引き
    PAGE_ID = "26e5c5c85ce88144b95ec0dc281d12c5"

    try:
        page = client.pages.retrieve(page_id=PAGE_ID)

        # 全てのPeopleプロパティからユーザー情報を収集
        user_mapping = {}

        properties = page.get('properties', {})
        for prop_name, prop_data in properties.items():
            if prop_data.get('type') == 'people':
                people = prop_data.get('people', [])
                for person in people:
                    user_id = person.get('id')
                    email = person.get('person', {}).get('email')
                    name = person.get('name')

                    if email and user_id:
                        user_mapping[email] = {
                            'id': user_id,
                            'name': name
                        }

        print("📋 発見されたユーザーマッピング:")
        for email, user_info in user_mapping.items():
            print(f"   {email} -> {user_info['name']} (ID: {user_info['id']})")

        return user_mapping

    except Exception as e:
        print(f"❌ エラー: {e}")
        return {}

if __name__ == "__main__":
    # 既存ページからユーザーマッピングを取得
    user_mapping = test_email_to_user_id_mapping()

    print("\n" + "=" * 50 + "\n")

    # ゲストユーザー直接設定をテスト
    test_direct_guest_assignment()