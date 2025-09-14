#!/usr/bin/env python3
"""
Notionデータベース構造確認ツール
"""
import os
from dotenv import load_dotenv
from notion_client import Client

load_dotenv()

NOTION_TOKEN = os.getenv('NOTION_TOKEN')
# 提供されたページID（データベースビューのURL）
MAPPING_PAGE_ID = "26e5c5c85ce88069bec2f05ef9f55d54"

def check_page_info():
    """ページ情報を確認してデータベースIDを特定"""
    print("🔍 Notionページ情報確認")
    print("-" * 60)

    client = Client(auth=NOTION_TOKEN)

    try:
        # ページ情報を取得
        page = client.pages.retrieve(page_id=MAPPING_PAGE_ID)

        print(f"📄 Page ID: {page['id']}")
        print(f"📅 Created: {page.get('created_time', 'Unknown')}")
        print(f"🆔 Parent: {page.get('parent', {})}")

        # ページの親を確認
        parent = page.get('parent', {})
        if parent.get('type') == 'database_id':
            database_id = parent.get('database_id')
            print(f"📊 Parent Database ID: {database_id}")
            return database_id
        else:
            print(f"⚠️ このページの親はデータベースではありません: {parent.get('type')}")
            return None

    except Exception as e:
        print(f"❌ エラー: {e}")
        return None

def check_database_structure(database_id):
    """データベースの構造を確認"""
    print("🔍 Notionデータベース構造確認")
    print("-" * 60)

    client = Client(auth=NOTION_TOKEN)

    try:
        # データベース情報を取得
        database = client.databases.retrieve(database_id=database_id)

        print(f"📋 Database: {database['title'][0]['text']['content']}")
        print(f"📅 Created: {database.get('created_time', 'Unknown')}")
        print(f"🆔 ID: {database['id']}")
        print()

        # プロパティ構造を確認
        properties = database.get('properties', {})

        print("🏷️ プロパティ一覧:")
        print("-" * 40)

        for prop_name, prop_info in properties.items():
            prop_type = prop_info.get('type')
            print(f"📌 {prop_name}")
            print(f"   タイプ: {prop_type}")

            # タイプ別の詳細情報
            if prop_type == 'select':
                options = prop_info.get('select', {}).get('options', [])
                print(f"   選択肢: {[opt['name'] for opt in options]}")

            elif prop_type == 'status':
                groups = prop_info.get('status', {}).get('groups', [])
                for group in groups:
                    group_name = group.get('name', 'Unknown Group')
                    options = [opt['name'] for opt in group.get('options', [])]
                    print(f"   {group_name}: {options}")

            elif prop_type == 'people':
                print(f"   People プロパティ")

            elif prop_type == 'date':
                print(f"   Date プロパティ")

            elif prop_type == 'title':
                print(f"   タイトルプロパティ")

            elif prop_type == 'rich_text':
                print(f"   リッチテキストプロパティ")

            print()

    except Exception as e:
        print(f"❌ エラー: {e}")

def check_database_content(database_id):
    """データベースの内容を確認（Peopleプロパティのユーザー情報）"""
    print("\n🔍 データベース内容確認")
    print("-" * 60)

    client = Client(auth=NOTION_TOKEN)

    try:
        # データベース内の全ページを取得
        pages = client.databases.query(database_id=database_id)

        print(f"📋 総ページ数: {len(pages['results'])}")
        print()

        user_mapping = {}

        for i, page in enumerate(pages['results'], 1):
            properties = page.get('properties', {})

            # タイトル取得
            title = "No Title"
            if 'タイトル' in properties and properties['タイトル'].get('title'):
                title = properties['タイトル']['title'][0]['text']['content']
            elif 'Name' in properties and properties['Name'].get('title'):
                title = properties['Name']['title'][0]['text']['content']

            print(f"📄 Page {i}: {title}")

            # 全てのPeopleプロパティをチェック
            for prop_name, prop_data in properties.items():
                if prop_data.get('type') == 'people':
                    people = prop_data.get('people', [])
                    print(f"   👥 {prop_name}: {len(people)}人")

                    for person in people:
                        person_email = person.get('person', {}).get('email')
                        if person_email:
                            print(f"      - {person.get('name')} ({person_email})")
                            print(f"        ID: {person.get('id')}")

                            # マッピング情報を収集
                            if person_email not in user_mapping:
                                user_mapping[person_email] = {
                                    'id': person.get('id'),
                                    'name': person.get('name'),
                                    'email': person_email,
                                    'type': person.get('type'),
                                    'object': person.get('object'),
                                    'avatar_url': person.get('avatar_url')
                                }

            print()

        # マッピング情報のサマリー
        print("📊 発見されたユーザーマッピング:")
        print("-" * 40)
        for email, user_data in user_mapping.items():
            print(f"👤 {user_data['name']} ({email})")
            print(f"   ID: {user_data['id']}")

        print(f"\n📋 総ユーザー数: {len(user_mapping)}人")
        return user_mapping

    except Exception as e:
        print(f"❌ エラー: {e}")
        return {}

if __name__ == "__main__":
    print("🎯 Notionマッピングデータベース調査")
    print("=" * 60)

    # ページ情報確認してデータベースIDを取得
    database_id = check_page_info()

    if database_id:
        # データベース構造確認
        check_database_structure(database_id)

        # データベース内容確認
        user_mapping = check_database_content(database_id)
    else:
        print("❌ データベースIDを取得できませんでした")