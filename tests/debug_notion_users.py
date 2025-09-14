#!/usr/bin/env python3
"""
Notionユーザー詳細調査スクリプト
"""
import os
import json
from dotenv import load_dotenv
from notion_client import Client

# 環境変数を読み込み
load_dotenv()

NOTION_TOKEN = os.getenv('NOTION_TOKEN')

def debug_all_users():
    """全Notionユーザーの詳細情報を表示"""
    print("🔍 Notion全ユーザー詳細調査")
    print("-" * 50)

    client = Client(auth=NOTION_TOKEN)

    try:
        users = client.users.list()
        print(f"📋 総ユーザー数: {len(users['results'])}")
        print()

        for i, user in enumerate(users['results'], 1):
            print(f"👤 User {i}:")
            print(f"   ID: {user.get('id', 'No ID')}")
            print(f"   Name: {user.get('name', 'No Name')}")
            print(f"   Type: {user.get('type', 'No Type')}")

            # 全キー表示
            print(f"   Available keys: {list(user.keys())}")

            # タイプ別詳細情報
            if user.get('type') == 'person':
                person_data = user.get('person', {})
                print(f"   Person data keys: {list(person_data.keys())}")
                print(f"   Email: {person_data.get('email', 'No email')}")

            elif user.get('type') == 'bot':
                bot_data = user.get('bot', {})
                print(f"   Bot data keys: {list(bot_data.keys())}")

            else:
                print(f"   Unknown type data: {json.dumps(user, indent=2, ensure_ascii=False)}")

            print()

    except Exception as e:
        print(f"❌ Error: {e}")

def check_database_permissions():
    """データベースの共有情報を確認"""
    print("🔍 データベース権限調査")
    print("-" * 50)

    DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
    client = Client(auth=NOTION_TOKEN)

    try:
        # データベース情報を取得
        database = client.databases.retrieve(database_id=DATABASE_ID)

        print(f"📋 Database: {database['title'][0]['text']['content']}")

        # Peopleプロパティがあるか確認
        properties = database.get('properties', {})

        for prop_name, prop_info in properties.items():
            if prop_info.get('type') == 'people':
                print(f"👥 People property found: {prop_name}")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    debug_all_users()
    print("\n" + "=" * 50 + "\n")
    check_database_permissions()