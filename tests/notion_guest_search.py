#!/usr/bin/env python3
"""
Notion APIでゲストユーザーをメールアドレスから検索する方法の実装
"""
import os
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv
from notion_client import Client

load_dotenv()

NOTION_TOKEN = os.getenv('NOTION_TOKEN')
DATABASE_ID = os.getenv('NOTION_DATABASE_ID')

class NotionGuestUserFinder:
    """データベース内の既存ページからゲストユーザーを検索"""

    def __init__(self, notion_token: str, database_id: str):
        self.client = Client(auth=notion_token)
        self.database_id = database_id

    def find_user_by_email_in_database(self, email: str) -> Optional[Dict[str, Any]]:
        """データベース内の全ページを検索してメールアドレスからユーザーを見つける"""
        print(f"🔍 データベース内でメール検索: {email}")

        try:
            # データベース内の全ページを取得
            pages = self.client.databases.query(database_id=self.database_id)

            user_cache = {}  # メールアドレス -> ユーザーオブジェクトのキャッシュ

            for page in pages.get('results', []):
                properties = page.get('properties', {})

                # 全てのPeopleプロパティを検索
                for prop_name, prop_data in properties.items():
                    if prop_data.get('type') == 'people':
                        people = prop_data.get('people', [])

                        for person in people:
                            person_email = person.get('person', {}).get('email')

                            if person_email:
                                user_cache[person_email.lower()] = {
                                    'id': person.get('id'),
                                    'name': person.get('name'),
                                    'email': person_email,
                                    'type': person.get('type'),
                                    'object': person.get('object'),
                                    'avatar_url': person.get('avatar_url')
                                }

            print(f"📋 キャッシュされたユーザー: {len(user_cache)}人")
            for cached_email, user_data in user_cache.items():
                print(f"   - {user_data['name']} ({cached_email})")

            # 目標のメールアドレスを検索
            target_user = user_cache.get(email.lower())
            if target_user:
                print(f"✅ ユーザー見つかりました: {target_user['name']} ({target_user['email']})")
                return {
                    'id': target_user['id'],
                    'object': target_user['object'],
                    'type': target_user['type'],
                    'name': target_user['name'],
                    'avatar_url': target_user['avatar_url'],
                    'person': {'email': target_user['email']}
                }
            else:
                print(f"❌ ユーザーが見つかりません: {email}")
                return None

        except Exception as e:
            print(f"❌ エラー: {e}")
            return None

    def find_all_users_in_database(self) -> Dict[str, Dict[str, Any]]:
        """データベース内の全ユーザーを取得してキャッシュ"""
        print("🔍 データベース内の全ユーザーをキャッシュ中...")

        try:
            pages = self.client.databases.query(database_id=self.database_id)
            user_cache = {}

            for page in pages.get('results', []):
                properties = page.get('properties', {})

                for prop_name, prop_data in properties.items():
                    if prop_data.get('type') == 'people':
                        people = prop_data.get('people', [])

                        for person in people:
                            person_email = person.get('person', {}).get('email')

                            if person_email and person_email.lower() not in user_cache:
                                user_cache[person_email.lower()] = {
                                    'id': person.get('id'),
                                    'name': person.get('name'),
                                    'email': person_email,
                                    'type': person.get('type'),
                                    'object': person.get('object'),
                                    'avatar_url': person.get('avatar_url')
                                }

            print(f"📋 キャッシュ完了: {len(user_cache)}人のユーザー")
            return user_cache

        except Exception as e:
            print(f"❌ エラー: {e}")
            return {}

def test_guest_user_search():
    """ゲストユーザー検索のテスト"""
    finder = NotionGuestUserFinder(NOTION_TOKEN, DATABASE_ID)

    # テスト対象のメールアドレス
    test_emails = [
        'masuda.g@atoriba.jp',
        'gals02513@gmail.com',
        'f25c142e@mail.cc.niigata-u.ac.jp',  # 正規メンバー
        'nonexistent@example.com'  # 存在しないメール
    ]

    print("=" * 60)
    print("🧪 ゲストユーザー検索テスト")
    print("=" * 60)

    for email in test_emails:
        print(f"\n📧 テスト: {email}")
        print("-" * 40)

        user = finder.find_user_by_email_in_database(email)

        if user:
            print(f"✅ 見つかりました!")
            print(f"   ID: {user['id']}")
            print(f"   Name: {user['name']}")
            print(f"   Email: {user['person']['email']}")
        else:
            print("❌ 見つかりませんでした")

    print("\n" + "=" * 60)
    print("📋 全ユーザーキャッシュ")
    print("=" * 60)

    all_users = finder.find_all_users_in_database()
    for email, user_data in all_users.items():
        print(f"👤 {user_data['name']} ({email}) - ID: {user_data['id']}")

if __name__ == "__main__":
    test_guest_user_search()