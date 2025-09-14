#!/usr/bin/env python3
"""
Notionゲストユーザー調査スクリプト
"""
import os
from dotenv import load_dotenv
from notion_client import Client

# 環境変数を読み込み
load_dotenv()

NOTION_TOKEN = os.getenv('NOTION_TOKEN')
# 提供されたページID
PAGE_ID = "26e5c5c85ce88144b95ec0dc281d12c5"

def investigate_page_users():
    """特定のページのユーザー設定を調査"""
    print("🔍 Notionページのユーザー設定調査")
    print(f"Page ID: {PAGE_ID}")
    print("-" * 50)

    client = Client(auth=NOTION_TOKEN)

    try:
        # ページ情報を取得
        page = client.pages.retrieve(page_id=PAGE_ID)

        print(f"📋 Page Title: {page.get('properties', {}).get('タイトル', {}).get('title', [{}])[0].get('text', {}).get('content', 'No title')}")
        print()

        # プロパティを調査
        properties = page.get('properties', {})

        for prop_name, prop_data in properties.items():
            print(f"🏷️ Property: {prop_name}")
            print(f"   Type: {prop_data.get('type')}")

            if prop_data.get('type') == 'people':
                people = prop_data.get('people', [])
                print(f"   People count: {len(people)}")

                for person in people:
                    print(f"   👤 Person:")
                    print(f"      ID: {person.get('id')}")
                    print(f"      Name: {person.get('name', 'No name')}")
                    print(f"      Type: {person.get('type', 'No type')}")
                    print(f"      Keys: {list(person.keys())}")

                    # person詳細情報
                    if person.get('type') == 'person' and 'person' in person:
                        person_detail = person.get('person', {})
                        print(f"      Email: {person_detail.get('email', 'No email')}")

            print()

    except Exception as e:
        print(f"❌ Error retrieving page: {e}")

def get_all_workspace_users():
    """ワークスペースの全ユーザーを再取得"""
    print("🔍 ワークスペース全ユーザー再調査")
    print("-" * 50)

    client = Client(auth=NOTION_TOKEN)

    try:
        # page_sizeを指定して全ユーザーを取得
        users = client.users.list(page_size=100)

        print(f"📋 総ユーザー数: {len(users['results'])}")
        print()

        emails_found = []

        for i, user in enumerate(users['results'], 1):
            user_type = user.get('type')
            user_name = user.get('name', 'No Name')
            user_id = user.get('id')

            if user_type == 'person':
                person_data = user.get('person', {})
                email = person_data.get('email', 'No email')
                print(f"👤 {user_name} (Member): {email}")
                emails_found.append(email)

            elif user_type != 'bot':
                print(f"👤 {user_name} ({user_type}): ID={user_id}")

        print(f"\n📧 Found emails: {emails_found}")

        # 目標のメールアドレスが含まれているかチェック
        target_emails = ['masuda.g@atoriba.jp', 'gals02513@gmail.com']
        for target_email in target_emails:
            if target_email in emails_found:
                print(f"✅ Found target email: {target_email}")
            else:
                print(f"❌ Missing target email: {target_email}")

    except Exception as e:
        print(f"❌ Error: {e}")

def try_create_test_page_with_email():
    """メールアドレス直接指定でページ作成を試す"""
    print("🔍 メールアドレス直接指定テスト")
    print("-" * 50)

    DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
    client = Client(auth=NOTION_TOKEN)

    # テスト用のメールアドレス
    test_emails = ['masuda.g@atoriba.jp', 'gals02513@gmail.com']

    for test_email in test_emails:
        print(f"📧 Testing email: {test_email}")

        try:
            from datetime import datetime

            # メールアドレス文字列をPeople型に直接設定を試す
            page = client.pages.create(
                parent={"database_id": DATABASE_ID},
                properties={
                    "タイトル": {
                        "title": [{"text": {"content": f"Email Test {test_email}"}}]
                    },
                    "納期": {
                        "date": {"start": datetime.now().isoformat()}
                    },
                    "ステータス": {
                        "status": {"name": "承認待ち"}
                    }
                    # Peopleプロパティは一旦スキップ
                }
            )

            page_id = page["id"]
            print(f"✅ Page created: https://www.notion.so/{page_id.replace('-', '')}")

        except Exception as e:
            print(f"❌ Failed to create page: {e}")

        print()

if __name__ == "__main__":
    investigate_page_users()
    print("\n" + "=" * 50 + "\n")
    get_all_workspace_users()
    print("\n" + "=" * 50 + "\n")
    try_create_test_page_with_email()