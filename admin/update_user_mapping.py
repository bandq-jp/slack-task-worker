#!/usr/bin/env python3
"""
Notion ユーザーマッピング更新ツール
- 新規ユーザーの追加
- 既存マッピングの更新
- 整合性チェック
"""
import os
import json
from typing import Dict, Any, Optional
from datetime import datetime
from dotenv import load_dotenv
from notion_client import Client

load_dotenv()

NOTION_TOKEN = os.getenv('NOTION_TOKEN')
MAPPING_FILE = os.path.join(os.path.dirname(__file__), '..', '.user_mapping.json')

class UserMappingUpdater:
    """ユーザーマッピングの更新とメンテナンス"""

    def __init__(self, notion_token: str, mapping_file: str):
        self.client = Client(auth=notion_token)
        self.mapping_file = mapping_file
        self.current_mapping = self.load_mapping()

    def load_mapping(self) -> Dict[str, Any]:
        """既存マッピングファイルの読み込み"""
        try:
            if os.path.exists(self.mapping_file):
                with open(self.mapping_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    print(f"✅ 既存マッピング読み込み: {len(data.get('email_to_notion_id', {}))}人")
                    return data
            else:
                print("⚠️ マッピングファイルが存在しません。新規作成します。")
                return {
                    'version': '1.0',
                    'created_at': datetime.now().isoformat(),
                    'email_to_notion_id': {}
                }
        except Exception as e:
            print(f"❌ マッピング読み込みエラー: {e}")
            return {'email_to_notion_id': {}}

    def add_user_by_id(self, email: str, notion_user_id: str, name: str = "") -> bool:
        """ユーザーIDを指定して手動追加"""
        print(f"👤 ユーザー手動追加: {email}")

        try:
            # Notion APIでユーザー詳細を取得して検証
            user = self.client.users.retrieve(user_id=notion_user_id)

            user_data = {
                'id': user.get('id'),
                'name': user.get('name', name),
                'email': email,
                'type': user.get('type'),
                'object': user.get('object'),
                'avatar_url': user.get('avatar_url'),
                'last_updated': datetime.now().isoformat(),
                'added_manually': True
            }

            self.current_mapping['email_to_notion_id'][email.lower()] = user_data
            print(f"✅ ユーザー追加成功: {user_data['name']} ({email})")
            return True

        except Exception as e:
            print(f"❌ ユーザー追加失敗: {e}")
            return False

    def search_and_add_user(self, email: str, database_id: str) -> bool:
        """データベース検索によるユーザー追加"""
        print(f"🔍 データベース検索: {email}")

        try:
            # データベース内のページを検索
            pages = self.client.databases.query(database_id=database_id)

            for page in pages.get('results', []):
                properties = page.get('properties', {})

                for prop_name, prop_data in properties.items():
                    if prop_data.get('type') == 'people':
                        people = prop_data.get('people', [])

                        for person in people:
                            person_email = person.get('person', {}).get('email')

                            if person_email and person_email.lower() == email.lower():
                                user_data = {
                                    'id': person.get('id'),
                                    'name': person.get('name'),
                                    'email': person_email,
                                    'type': person.get('type'),
                                    'object': person.get('object'),
                                    'avatar_url': person.get('avatar_url'),
                                    'last_updated': datetime.now().isoformat(),
                                    'found_in_database': database_id
                                }

                                self.current_mapping['email_to_notion_id'][email.lower()] = user_data
                                print(f"✅ ユーザー検索成功: {user_data['name']} ({email})")
                                return True

            print(f"❌ ユーザーが見つかりません: {email}")
            return False

        except Exception as e:
            print(f"❌ 検索エラー: {e}")
            return False

    def remove_user(self, email: str) -> bool:
        """ユーザーをマッピングから削除"""
        email_lower = email.lower()

        if email_lower in self.current_mapping['email_to_notion_id']:
            removed_user = self.current_mapping['email_to_notion_id'].pop(email_lower)
            print(f"✅ ユーザー削除: {removed_user['name']} ({email})")
            return True
        else:
            print(f"⚠️ ユーザーが見つかりません: {email}")
            return False

    def update_user_info(self, email: str) -> bool:
        """既存ユーザー情報の更新"""
        email_lower = email.lower()

        if email_lower not in self.current_mapping['email_to_notion_id']:
            print(f"⚠️ ユーザーが存在しません: {email}")
            return False

        try:
            user_data = self.current_mapping['email_to_notion_id'][email_lower]
            user_id = user_data['id']

            # Notion APIから最新情報を取得
            updated_user = self.client.users.retrieve(user_id=user_id)

            user_data.update({
                'name': updated_user.get('name', user_data['name']),
                'type': updated_user.get('type', user_data['type']),
                'avatar_url': updated_user.get('avatar_url'),
                'last_updated': datetime.now().isoformat()
            })

            print(f"✅ ユーザー情報更新: {user_data['name']} ({email})")
            return True

        except Exception as e:
            print(f"❌ 更新エラー: {e}")
            return False

    def validate_all_users(self) -> Dict[str, Any]:
        """全ユーザーの整合性チェック"""
        print("🔍 全ユーザー整合性チェック中...")

        validation_results = {
            'total_users': len(self.current_mapping['email_to_notion_id']),
            'valid_users': 0,
            'invalid_users': [],
            'unreachable_users': []
        }

        for email, user_data in self.current_mapping['email_to_notion_id'].items():
            try:
                # Notion APIでユーザーの存在確認
                user = self.client.users.retrieve(user_id=user_data['id'])
                validation_results['valid_users'] += 1

            except Exception as e:
                if "Could not find user" in str(e):
                    validation_results['unreachable_users'].append({
                        'email': email,
                        'name': user_data.get('name', 'Unknown'),
                        'error': 'User not found'
                    })
                else:
                    validation_results['invalid_users'].append({
                        'email': email,
                        'name': user_data.get('name', 'Unknown'),
                        'error': str(e)
                    })

        # 結果表示
        print(f"   ✅ 総ユーザー数: {validation_results['total_users']}")
        print(f"   ✅ 有効ユーザー: {validation_results['valid_users']}")

        if validation_results['invalid_users']:
            print(f"   ❌ 無効ユーザー: {len(validation_results['invalid_users'])}")

        if validation_results['unreachable_users']:
            print(f"   ⚠️ 到達不能ユーザー: {len(validation_results['unreachable_users'])}")

        return validation_results

    def save_mapping(self) -> bool:
        """更新されたマッピングを保存"""
        try:
            self.current_mapping['last_updated'] = datetime.now().isoformat()

            with open(self.mapping_file, 'w', encoding='utf-8') as f:
                json.dump(self.current_mapping, f, indent=2, ensure_ascii=False)

            print(f"✅ マッピング保存完了: {self.mapping_file}")
            return True

        except Exception as e:
            print(f"❌ 保存エラー: {e}")
            return False

    def display_users(self, limit: int = None):
        """ユーザー一覧表示"""
        users = self.current_mapping['email_to_notion_id']
        display_count = min(limit or len(users), len(users))

        print(f"\n👥 現在のユーザー一覧 ({display_count}/{len(users)}人):")
        print("-" * 60)

        for i, (email, user_data) in enumerate(list(users.items())[:display_count]):
            print(f"{i+1:2d}. {user_data['name']} ({email})")
            print(f"    ID: {user_data['id']}")
            if user_data.get('last_updated'):
                print(f"    更新: {user_data['last_updated'][:19]}")
            print()

        if len(users) > display_count:
            print(f"... 他 {len(users) - display_count} 人")


def main():
    """メイン実行関数"""
    print("🔧 Notion ユーザーマッピング更新ツール")
    print("=" * 60)

    updater = UserMappingUpdater(NOTION_TOKEN, MAPPING_FILE)

    while True:
        print("\n選択してください:")
        print("1. ユーザー手動追加 (ID指定)")
        print("2. ユーザー検索追加 (DB検索)")
        print("3. ユーザー削除")
        print("4. ユーザー情報更新")
        print("5. 全ユーザー整合性チェック")
        print("6. ユーザー一覧表示")
        print("7. 保存して終了")
        print("8. 終了(保存なし)")

        choice = input("\n選択 (1-8): ").strip()

        if choice == '1':
            email = input("メールアドレス: ").strip()
            notion_id = input("Notion ユーザーID: ").strip()
            name = input("名前 (任意): ").strip()

            if updater.add_user_by_id(email, notion_id, name):
                print("✅ 追加完了")

        elif choice == '2':
            email = input("メールアドレス: ").strip()
            database_id = input("検索対象DB ID (空白=デフォルト): ").strip()

            if not database_id:
                database_id = os.getenv('NOTION_DATABASE_ID')

            if updater.search_and_add_user(email, database_id):
                print("✅ 検索・追加完了")

        elif choice == '3':
            email = input("削除するメールアドレス: ").strip()
            if updater.remove_user(email):
                print("✅ 削除完了")

        elif choice == '4':
            email = input("更新するメールアドレス: ").strip()
            if updater.update_user_info(email):
                print("✅ 更新完了")

        elif choice == '5':
            results = updater.validate_all_users()
            print("✅ 整合性チェック完了")

        elif choice == '6':
            limit = input("表示件数 (空白=全て): ").strip()
            display_limit = int(limit) if limit.isdigit() else None
            updater.display_users(display_limit)

        elif choice == '7':
            if updater.save_mapping():
                print("✅ 保存完了。終了します。")
            else:
                print("❌ 保存失敗")
            break

        elif choice == '8':
            print("保存せずに終了します。")
            break

        else:
            print("❌ 無効な選択です")


if __name__ == "__main__":
    main()