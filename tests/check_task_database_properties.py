#!/usr/bin/env python3
"""
タスクデータベースのプロパティ一覧を取得・確認するスクリプト
既存のプロパティを一覧化してドキュメント化する
"""
import os
import json
from dotenv import load_dotenv
from notion_client import Client

load_dotenv()

NOTION_TOKEN = os.getenv('NOTION_TOKEN')
NOTION_DATABASE_ID = os.getenv('NOTION_DATABASE_ID')

def check_task_database_properties():
    """タスクデータベースのプロパティ構造を詳細に確認"""
    print("=" * 80)
    print("🔍 タスクデータベースプロパティ一覧取得")
    print("=" * 80)
    print(f"📊 Database ID: {NOTION_DATABASE_ID}")
    print()

    client = Client(auth=NOTION_TOKEN)

    try:
        # データベース情報を取得
        database = client.databases.retrieve(database_id=NOTION_DATABASE_ID)

        # データベース名
        db_title = "Unknown"
        if database.get('title') and len(database['title']) > 0:
            db_title = database['title'][0].get('text', {}).get('content', 'Unknown')

        print(f"📋 データベース名: {db_title}")
        print(f"📅 作成日時: {database.get('created_time', 'Unknown')}")
        print(f"🆔 Database ID: {database['id']}")
        print()
        print("=" * 80)

        # プロパティ構造を確認
        properties = database.get('properties', {})

        print(f"🏷️  プロパティ一覧 (合計 {len(properties)} 個)")
        print("=" * 80)
        print()

        # プロパティを種類別に分類
        property_summary = {
            'title': [],
            'date': [],
            'select': [],
            'status': [],
            'people': [],
            'rich_text': [],
            'checkbox': [],
            'number': [],
            'url': [],
            'email': [],
            'phone_number': [],
            'formula': [],
            'relation': [],
            'rollup': [],
            'created_time': [],
            'created_by': [],
            'last_edited_time': [],
            'last_edited_by': [],
            'files': [],
            'multi_select': [],
            'other': []
        }

        for prop_name, prop_info in sorted(properties.items()):
            prop_type = prop_info.get('type')

            print(f"📌 {prop_name}")
            print(f"   Type: {prop_type}")

            # プロパティを分類
            if prop_type in property_summary:
                property_summary[prop_type].append(prop_name)
            else:
                property_summary['other'].append(prop_name)

            # タイプ別の詳細情報
            if prop_type == 'select':
                options = prop_info.get('select', {}).get('options', [])
                option_names = [opt['name'] for opt in options]
                print(f"   選択肢: {option_names}")

            elif prop_type == 'multi_select':
                options = prop_info.get('multi_select', {}).get('options', [])
                option_names = [opt['name'] for opt in options]
                print(f"   選択肢: {option_names}")

            elif prop_type == 'status':
                status_config = prop_info.get('status', {})
                groups = status_config.get('groups', [])
                all_options = []
                for group in groups:
                    group_name = group.get('name', 'Unknown Group')
                    options = [opt['name'] for opt in group.get('options', [])]
                    all_options.extend(options)
                    print(f"   Group '{group_name}': {options}")
                print(f"   全ステータス: {all_options}")

            elif prop_type == 'date':
                print(f"   日付プロパティ")

            elif prop_type == 'people':
                print(f"   人物プロパティ")

            elif prop_type == 'title':
                print(f"   タイトルプロパティ（必須）")

            elif prop_type == 'rich_text':
                print(f"   リッチテキストプロパティ")

            elif prop_type == 'checkbox':
                print(f"   チェックボックスプロパティ")

            elif prop_type == 'number':
                number_format = prop_info.get('number', {}).get('format', 'number')
                print(f"   数値プロパティ (format: {number_format})")

            elif prop_type == 'url':
                print(f"   URLプロパティ")

            elif prop_type == 'formula':
                expression = prop_info.get('formula', {}).get('expression', '')
                print(f"   計算式: {expression}")

            elif prop_type == 'relation':
                relation_db = prop_info.get('relation', {}).get('database_id', 'Unknown')
                print(f"   リレーション先DB: {relation_db}")

            elif prop_type == 'rollup':
                rollup_prop = prop_info.get('rollup', {}).get('rollup_property_name', 'Unknown')
                rollup_func = prop_info.get('rollup', {}).get('function', 'Unknown')
                print(f"   Rollup: {rollup_prop} ({rollup_func})")

            print()

        # サマリー表示
        print("=" * 80)
        print("📊 プロパティタイプ別サマリー")
        print("=" * 80)

        for prop_type, prop_names in property_summary.items():
            if prop_names:
                print(f"\n{prop_type.upper()} ({len(prop_names)}個):")
                for name in prop_names:
                    print(f"  - {name}")

        # 承認待ち関連プロパティのチェック
        print("\n" + "=" * 80)
        print("🔍 承認待ち関連プロパティの確認")
        print("=" * 80)

        required_for_approval = [
            ("ステータス", "select or status"),
            ("完了ステータス", "select or status"),
            ("延期ステータス", "select or status"),
            ("タスク承認開始日時", "date"),
            ("承認リマインド最終送信日時", "date"),
            ("延期申請日時", "date"),
            ("完了申請日時", "date"),
            ("依頼者", "people"),
            ("依頼先", "people"),
        ]

        print("\n必要なプロパティの確認:")
        for prop_name, expected_type in required_for_approval:
            if prop_name in properties:
                actual_type = properties[prop_name].get('type')
                status = "✅" if expected_type.replace(" or status", "").replace(" or select", "") in actual_type else "⚠️"
                print(f"{status} {prop_name}: {actual_type}")
            else:
                print(f"❌ {prop_name}: 存在しません (必要タイプ: {expected_type})")

        # JSON形式でも出力
        print("\n" + "=" * 80)
        print("📄 JSON形式のプロパティ構造 (開発用)")
        print("=" * 80)

        simplified_props = {}
        for prop_name, prop_info in properties.items():
            prop_type = prop_info.get('type')
            simplified_props[prop_name] = {
                'type': prop_type,
            }

            if prop_type == 'select':
                simplified_props[prop_name]['options'] = [opt['name'] for opt in prop_info.get('select', {}).get('options', [])]
            elif prop_type == 'multi_select':
                simplified_props[prop_name]['options'] = [opt['name'] for opt in prop_info.get('multi_select', {}).get('options', [])]
            elif prop_type == 'status':
                all_statuses = []
                for group in prop_info.get('status', {}).get('groups', []):
                    all_statuses.extend([opt['name'] for opt in group.get('options', [])])
                simplified_props[prop_name]['options'] = all_statuses

        print(json.dumps(simplified_props, ensure_ascii=False, indent=2))

        return properties

    except Exception as e:
        print(f"❌ エラー: {e}")
        import traceback
        traceback.print_exc()
        return None


def check_sample_tasks():
    """サンプルタスクを取得して実際のデータ構造を確認"""
    print("\n" + "=" * 80)
    print("🔍 サンプルタスクの確認 (最新5件)")
    print("=" * 80)

    client = Client(auth=NOTION_TOKEN)

    try:
        # 最新5件のタスクを取得
        response = client.databases.query(
            database_id=NOTION_DATABASE_ID,
            page_size=5,
            sorts=[
                {
                    "timestamp": "created_time",
                    "direction": "descending",
                }
            ]
        )

        pages = response.get('results', [])
        print(f"\n取得したタスク数: {len(pages)}")
        print()

        for i, page in enumerate(pages, 1):
            properties = page.get('properties', {})

            # タイトル取得
            title = "No Title"
            for prop_name, prop_data in properties.items():
                if prop_data.get('type') == 'title':
                    title_array = prop_data.get('title', [])
                    if title_array:
                        title = title_array[0].get('text', {}).get('content', 'No Title')
                    break

            print(f"📄 タスク {i}: {title}")
            print(f"   Page ID: {page['id']}")
            print(f"   作成日時: {page.get('created_time', 'Unknown')}")

            # 主要プロパティの値を確認
            key_props = ['ステータス', '完了ステータス', '延期ステータス', '納期', '依頼者', '依頼先']
            for prop_name in key_props:
                if prop_name in properties:
                    prop_data = properties[prop_name]
                    prop_type = prop_data.get('type')

                    if prop_type == 'select':
                        value = prop_data.get('select', {}).get('name', 'なし') if prop_data.get('select') else 'なし'
                        print(f"   {prop_name}: {value}")
                    elif prop_type == 'status':
                        value = prop_data.get('status', {}).get('name', 'なし') if prop_data.get('status') else 'なし'
                        print(f"   {prop_name}: {value}")
                    elif prop_type == 'date':
                        date_obj = prop_data.get('date')
                        value = date_obj.get('start', 'なし') if date_obj else 'なし'
                        print(f"   {prop_name}: {value}")
                    elif prop_type == 'people':
                        people = prop_data.get('people', [])
                        names = [p.get('name', 'Unknown') for p in people]
                        print(f"   {prop_name}: {', '.join(names) if names else 'なし'}")

            print()

    except Exception as e:
        print(f"❌ エラー: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    if not NOTION_TOKEN:
        print("❌ NOTION_TOKEN が設定されていません")
        exit(1)

    if not NOTION_DATABASE_ID:
        print("❌ NOTION_DATABASE_ID が設定されていません")
        exit(1)

    # プロパティ一覧を取得
    properties = check_task_database_properties()

    if properties:
        # サンプルタスクも確認
        check_sample_tasks()

        print("\n" + "=" * 80)
        print("✅ プロパティ確認完了")
        print("=" * 80)
