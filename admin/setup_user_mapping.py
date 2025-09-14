#!/usr/bin/env python3
"""
Notion ユーザーマッピング初期セットアップツール
- 既存のデータベースから全ユーザー情報を抽出
- セキュアなマッピングファイルを自動生成
- 検証とテスト機能付き
"""
import os
import json
from typing import Dict, Any, Set, List
from datetime import datetime
from dotenv import load_dotenv
from notion_client import Client

load_dotenv()

NOTION_TOKEN = os.getenv('NOTION_TOKEN')
MAPPING_FILE = '/home/als0028/work/bandq/slack-test/.user_mapping.json'

class UserMappingSetup:
    """ユーザーマッピングの初期セットアップ"""

    def __init__(self, notion_token: str):
        self.client = Client(auth=notion_token)
        self.user_mapping = {}
        self.statistics = {
            'databases_scanned': 0,
            'pages_scanned': 0,
            'unique_users_found': 0,
            'setup_time': None
        }

    def scan_database_for_users(self, database_id: str, database_name: str = "") -> Set[Dict[str, Any]]:
        """データベース内の全ユーザーを検索"""
        print(f"🔍 データベーススキャン: {database_name or database_id}")
        users_found = set()

        try:
            # データベース内の全ページを取得
            has_more = True
            next_cursor = None

            while has_more:
                query_params = {"database_id": database_id}
                if next_cursor:
                    query_params["start_cursor"] = next_cursor

                response = self.client.databases.query(**query_params)
                pages = response.get('results', [])

                for page in pages:
                    self.statistics['pages_scanned'] += 1
                    properties = page.get('properties', {})

                    # 全てのPeopleプロパティをスキャン
                    for prop_name, prop_data in properties.items():
                        if prop_data.get('type') == 'people':
                            people = prop_data.get('people', [])

                            for person in people:
                                person_email = person.get('person', {}).get('email')
                                if person_email:
                                    user_info = {
                                        'id': person.get('id'),
                                        'name': person.get('name'),
                                        'email': person_email,
                                        'type': person.get('type'),
                                        'object': person.get('object'),
                                        'avatar_url': person.get('avatar_url')
                                    }

                                    # セットに追加（重複除去のため、emailをキーにする）
                                    users_found.add((person_email, json.dumps(user_info, sort_keys=True)))

                has_more = response.get('has_more', False)
                next_cursor = response.get('next_cursor')

            self.statistics['databases_scanned'] += 1
            print(f"   📋 見つかったユーザー: {len(users_found)}人")

        except Exception as e:
            print(f"   ❌ エラー: {e}")

        return users_found

    def scan_multiple_databases(self, database_configs: List[Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
        """複数のデータベースをスキャンしてユーザーマッピングを生成"""
        print("🚀 ユーザーマッピング初期セットアップ開始")
        print("=" * 60)

        setup_start_time = datetime.now()
        all_users = set()

        # 各データベースをスキャン
        for config in database_configs:
            database_id = config['id']
            database_name = config.get('name', '')

            users_from_db = self.scan_database_for_users(database_id, database_name)
            all_users.update(users_from_db)

        # ユーザー情報を辞書形式に変換
        user_mapping = {}
        for email, user_json in all_users:
            user_info = json.loads(user_json)
            user_mapping[email.lower()] = {
                'id': user_info['id'],
                'name': user_info['name'],
                'email': user_info['email'],
                'type': user_info['type'],
                'object': user_info['object'],
                'avatar_url': user_info.get('avatar_url'),
                'last_seen': datetime.now().isoformat()
            }

        self.user_mapping = user_mapping
        self.statistics['unique_users_found'] = len(user_mapping)
        self.statistics['setup_time'] = (datetime.now() - setup_start_time).total_seconds()

        print("\n" + "=" * 60)
        print("📊 スキャン結果:")
        print(f"   データベース数: {self.statistics['databases_scanned']}")
        print(f"   ページ数: {self.statistics['pages_scanned']}")
        print(f"   ユニークユーザー数: {self.statistics['unique_users_found']}")
        print(f"   処理時間: {self.statistics['setup_time']:.2f}秒")

        return user_mapping

    def save_mapping_file(self, filepath: str) -> bool:
        """マッピングファイルを保存"""
        try:
            mapping_data = {
                'version': '1.0',
                'created_at': datetime.now().isoformat(),
                'statistics': self.statistics,
                'email_to_notion_id': self.user_mapping
            }

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(mapping_data, f, indent=2, ensure_ascii=False)

            print(f"✅ マッピングファイル保存完了: {filepath}")
            return True

        except Exception as e:
            print(f"❌ マッピングファイル保存エラー: {e}")
            return False

    def validate_mapping(self) -> bool:
        """マッピングデータの検証"""
        print("\n🔍 マッピングデータ検証中...")

        validation_results = {
            'total_users': len(self.user_mapping),
            'valid_emails': 0,
            'valid_ids': 0,
            'missing_data': []
        }

        for email, user_data in self.user_mapping.items():
            # メール形式チェック
            if '@' in email and '.' in email.split('@')[1]:
                validation_results['valid_emails'] += 1

            # ID存在チェック
            if user_data.get('id') and len(user_data['id']) > 10:
                validation_results['valid_ids'] += 1

            # 必須データチェック
            required_fields = ['id', 'name', 'email']
            missing_fields = [field for field in required_fields if not user_data.get(field)]
            if missing_fields:
                validation_results['missing_data'].append({
                    'email': email,
                    'missing_fields': missing_fields
                })

        # 検証結果表示
        print(f"   ✅ 総ユーザー数: {validation_results['total_users']}")
        print(f"   ✅ 有効なメール: {validation_results['valid_emails']}/{validation_results['total_users']}")
        print(f"   ✅ 有効なID: {validation_results['valid_ids']}/{validation_results['total_users']}")

        if validation_results['missing_data']:
            print(f"   ⚠️ 不完全なデータ: {len(validation_results['missing_data'])}件")
            for issue in validation_results['missing_data'][:3]:  # 最初の3件のみ表示
                print(f"      - {issue['email']}: {', '.join(issue['missing_fields'])}が不足")

        is_valid = (
            validation_results['valid_emails'] == validation_results['total_users'] and
            validation_results['valid_ids'] == validation_results['total_users'] and
            len(validation_results['missing_data']) == 0
        )

        if is_valid:
            print("   ✅ 検証完了: データは正常です")
        else:
            print("   ⚠️ 検証完了: 一部データに問題があります")

        return is_valid

    def display_user_list(self, limit: int = 10):
        """ユーザー一覧を表示"""
        print(f"\n👥 検出されたユーザー一覧 (上位{min(limit, len(self.user_mapping))}人):")
        print("-" * 60)

        for i, (email, user_data) in enumerate(list(self.user_mapping.items())[:limit]):
            print(f"{i+1:2d}. {user_data['name']} ({email})")
            print(f"    ID: {user_data['id']}")
            print()

        if len(self.user_mapping) > limit:
            print(f"... 他 {len(self.user_mapping) - limit} 人")


def main():
    """メイン実行関数"""
    print("🎯 Notion ユーザーマッピング初期セットアップ")
    print("=" * 60)

    # データベース設定（複数のデータベースを指定可能）
    database_configs = [
        {
            'id': os.getenv('NOTION_DATABASE_ID'),
            'name': 'メインタスクDB'
        }
        # 追加のデータベースがあれば以下に追加
        # {
        #     'id': 'another-database-id',
        #     'name': '別のDB'
        # }
    ]

    # セットアップ実行
    setup = UserMappingSetup(NOTION_TOKEN)
    user_mapping = setup.scan_multiple_databases(database_configs)

    if user_mapping:
        # 検証実行
        is_valid = setup.validate_mapping()

        # ユーザー一覧表示
        setup.display_user_list()

        # ファイル保存
        if setup.save_mapping_file(MAPPING_FILE):
            print(f"\n🎉 セットアップ完了!")
            print(f"   マッピングファイル: {MAPPING_FILE}")
            print(f"   ユーザー数: {len(user_mapping)}人")
            print(f"\n💡 次のステップ:")
            print(f"   1. NotionServiceでこのマッピングファイルを使用")
            print(f"   2. 新しいユーザー追加時は update_user_mapping.py を実行")
        else:
            print("\n❌ セットアップ失敗")

    else:
        print("\n❌ ユーザーが見つかりませんでした")


if __name__ == "__main__":
    main()