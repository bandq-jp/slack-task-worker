#!/usr/bin/env python3
"""
マッピング用タスクデータベースから自動でユーザーマッピングを生成するツール
環境変数にマッピング用データベースIDを設定して使用
"""
import os
import json
from typing import Dict, Any, Set, Optional
from datetime import datetime
from dotenv import load_dotenv
from notion_client import Client

load_dotenv()

NOTION_TOKEN = os.getenv('NOTION_TOKEN')
# マッピング用データベースID（環境変数から取得、なければメインのタスクDBを使用）
MAPPING_DATABASE_ID = os.getenv('MAPPING_DATABASE_ID', os.getenv('NOTION_DATABASE_ID'))
MAPPING_FILE = os.path.join(os.path.dirname(__file__), '..', '.user_mapping.json')

class DatabaseMappingGenerator:
    """データベースからユーザーマッピングを自動生成"""

    def __init__(self, notion_token: str, database_id: str):
        self.client = Client(auth=notion_token)
        self.database_id = database_id
        self.user_mapping = {}
        self.statistics = {
            'database_scanned': 1,
            'pages_scanned': 0,
            'unique_users_found': 0,
            'setup_time': None,
            'mapping_source': 'database_mapping'
        }

    def detect_mapping_page(self) -> Optional[str]:
        """マッピング専用ページを自動検出"""
        try:
            pages = self.client.databases.query(database_id=self.database_id)

            # マッピング専用のキーワードを含むページを検索
            mapping_keywords = [
                '削除しないでください',
                'ユーザーマッピング',
                'User Mapping',
                'mapping',
                'マッピング用'
            ]

            for page in pages.get('results', []):
                properties = page.get('properties', {})

                # タイトル取得
                title = ""
                if 'タイトル' in properties and properties['タイトル'].get('title'):
                    title = properties['タイトル']['title'][0]['text']['content']
                elif 'Name' in properties and properties['Name'].get('title'):
                    title = properties['Name']['title'][0]['text']['content']

                # マッピング専用ページかチェック
                for keyword in mapping_keywords:
                    if keyword in title:
                        print(f"✅ マッピング専用ページ発見: '{title}' (ID: {page['id']})")
                        return page['id']

            print("⚠️ 専用マッピングページが見つかりません - 全ページからマッピング生成")
            return None

        except Exception as e:
            print(f"❌ マッピングページ検出エラー: {e}")
            return None

    def extract_users_from_database(self, mapping_page_id: str = None) -> Dict[str, Dict[str, Any]]:
        """データベースから全ユーザーを抽出してマッピング生成"""
        print("🚀 データベースユーザーマッピング生成開始")
        print("=" * 60)

        setup_start_time = datetime.now()
        all_users = set()

        try:
            # データベース情報表示
            database = self.client.databases.retrieve(database_id=self.database_id)
            db_title = database['title'][0]['text']['content']
            print(f"📊 対象データベース: {db_title}")
            print(f"🆔 データベースID: {self.database_id}")

            if mapping_page_id:
                print(f"🎯 マッピング専用ページ重点スキャン")
            else:
                print(f"🔍 全ページスキャン")

            # ページ取得
            pages = self.client.databases.query(database_id=self.database_id)
            total_pages = len(pages.get('results', []))
            self.statistics['pages_scanned'] = total_pages

            print(f"📋 総ページ数: {total_pages}")
            print("-" * 40)

            for i, page in enumerate(pages.get('results', []), 1):
                properties = page.get('properties', {})

                # タイトル取得
                title = "No Title"
                if 'タイトル' in properties and properties['タイトル'].get('title'):
                    title = properties['タイトル']['title'][0]['text']['content']
                elif 'Name' in properties and properties['Name'].get('title'):
                    title = properties['Name']['title'][0]['text']['content']

                # マッピング専用ページかどうかの判定
                is_mapping_page = mapping_page_id and page['id'] == mapping_page_id

                if is_mapping_page:
                    print(f"🎯 Page {i}: {title} ★マッピング専用★")
                elif mapping_page_id:
                    # マッピング専用ページがある場合は他のページをスキップ
                    continue
                else:
                    print(f"📄 Page {i}: {title}")

                # 全てのPeopleプロパティをスキャン
                people_found = 0
                for prop_name, prop_data in properties.items():
                    if prop_data.get('type') == 'people':
                        people = prop_data.get('people', [])
                        people_found += len(people)

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

                                # セットに追加（重複除去）
                                all_users.add((person_email, json.dumps(user_info, sort_keys=True)))

                if people_found > 0:
                    print(f"   👥 ユーザー: {people_found}人")

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
                    'last_seen': datetime.now().isoformat(),
                    'source': 'database_mapping'
                }

            self.user_mapping = user_mapping
            self.statistics['unique_users_found'] = len(user_mapping)
            self.statistics['setup_time'] = (datetime.now() - setup_start_time).total_seconds()

            print("\n" + "=" * 60)
            print("📊 マッピング生成結果:")
            print(f"   データベース: {db_title}")
            print(f"   ページ数: {self.statistics['pages_scanned']}")
            print(f"   ユニークユーザー数: {self.statistics['unique_users_found']}")
            print(f"   処理時間: {self.statistics['setup_time']:.2f}秒")

            return user_mapping

        except Exception as e:
            print(f"❌ マッピング生成エラー: {e}")
            return {}

    def save_mapping_file(self, filepath: str) -> bool:
        """マッピングファイルを保存"""
        try:
            mapping_data = {
                'version': '1.0',
                'created_at': datetime.now().isoformat(),
                'statistics': self.statistics,
                'source_database_id': self.database_id,
                'email_to_notion_id': self.user_mapping,
                'generation_method': 'database_auto_extraction'
            }

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(mapping_data, f, indent=2, ensure_ascii=False)

            print(f"✅ マッピングファイル保存完了: {filepath}")
            return True

        except Exception as e:
            print(f"❌ マッピングファイル保存エラー: {e}")
            return False

    def display_user_list(self, limit: int = 20):
        """ユーザー一覧を表示"""
        print(f"\n👥 生成されたユーザーマッピング (上位{min(limit, len(self.user_mapping))}人):")
        print("-" * 60)

        for i, (email, user_data) in enumerate(list(self.user_mapping.items())[:limit]):
            print(f"{i+1:2d}. {user_data['name']} ({email})")
            print(f"    ID: {user_data['id']}")
            print(f"    Type: {user_data.get('type', 'unknown')}")
            print()

        if len(self.user_mapping) > limit:
            print(f"... 他 {len(self.user_mapping) - limit} 人")

    def check_status_property(self):
        """ステータスプロパティの構造を確認"""
        try:
            database = self.client.databases.retrieve(database_id=self.database_id)
            properties = database.get('properties', {})

            status_prop = properties.get('ステータス')
            if not status_prop:
                print("⚠️ 'ステータス' プロパティが見つかりません")
                return

            prop_type = status_prop.get('type')
            print(f"\n📌 ステータスプロパティ確認:")
            print(f"   タイプ: {prop_type}")

            if prop_type == 'select':
                options = status_prop.get('select', {}).get('options', [])
                option_names = [opt['name'] for opt in options]
                print(f"   選択肢: {option_names}")

                # NotionServiceの更新が必要かチェック
                expected_options = ['承認待ち', '承認済み', '差し戻し', '完了', '無効']
                missing_options = [opt for opt in expected_options if opt not in option_names]

                if missing_options:
                    print(f"⚠️ NotionServiceで追加対応が必要: {missing_options}")
                else:
                    print("✅ すべての選択肢が対応済み")

            elif prop_type == 'status':
                print("⚠️ ステータスタイプです - NotionServiceの更新が必要")

        except Exception as e:
            print(f"❌ ステータスプロパティ確認エラー: {e}")


def main():
    """メイン実行関数"""
    print("🎯 データベース自動ユーザーマッピング生成")
    print("=" * 60)

    if not MAPPING_DATABASE_ID:
        print("❌ データベースIDが設定されていません")
        print("💡 以下のいずれかを設定してください:")
        print("   - MAPPING_DATABASE_ID 環境変数")
        print("   - NOTION_DATABASE_ID 環境変数")
        return

    print(f"📊 使用データベースID: {MAPPING_DATABASE_ID}")

    # マッピング生成器初期化
    generator = DatabaseMappingGenerator(NOTION_TOKEN, MAPPING_DATABASE_ID)

    # ステータスプロパティ確認
    generator.check_status_property()

    # マッピング専用ページを検出
    mapping_page_id = generator.detect_mapping_page()

    # ユーザーマッピング生成
    user_mapping = generator.extract_users_from_database(mapping_page_id)

    if user_mapping:
        # ユーザー一覧表示
        generator.display_user_list()

        # ファイル保存
        if generator.save_mapping_file(MAPPING_FILE):
            print(f"\n🎉 マッピング生成完了!")
            print(f"   マッピングファイル: {MAPPING_FILE}")
            print(f"   ユーザー数: {len(user_mapping)}人")

            if mapping_page_id:
                print(f"\n💡 マッピング更新方法:")
                print(f"   1. '【削除しないでください】ユーザーマッピング用' ページを編集")
                print(f"   2. 依頼者/依頼先プロパティに新しいユーザーを追加")
                print(f"   3. このスクリプトを再実行")
            else:
                print(f"\n💡 推奨:")
                print(f"   1. マッピング専用ページを作成 ('【削除しないでください】ユーザーマッピング用')")
                print(f"   2. 全ユーザーを依頼者プロパティに設定")
                print(f"   3. このスクリプトを再実行でより高速化")

        else:
            print("\n❌ マッピング生成失敗")
    else:
        print("\n❌ ユーザーが見つかりませんでした")


if __name__ == "__main__":
    main()