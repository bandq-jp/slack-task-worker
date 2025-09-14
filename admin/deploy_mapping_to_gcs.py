#!/usr/bin/env python3
"""
ローカルのユーザーマッピングファイルをGCSにデプロイするツール
Cloud Runデプロイ前に実行
"""
import os
import json
import argparse
from datetime import datetime
from google.cloud import storage
from dotenv import load_dotenv

load_dotenv()

class MappingDeployer:
    """ユーザーマッピングのCloud環境デプロイ"""

    def __init__(self, bucket_name: str, service_account_path: str = None):
        self.bucket_name = bucket_name

        # サービスアカウントキーが指定されている場合
        if service_account_path and os.path.exists(service_account_path):
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = service_account_path

        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket_name)

    def deploy_local_mapping(self, local_mapping_file: str, gcs_file_name: str = "user_mapping.json") -> bool:
        """ローカルマッピングファイルをGCSにアップロード"""
        try:
            print(f"🚀 ローカルマッピングファイルをGCSにデプロイ")
            print(f"   ローカルファイル: {local_mapping_file}")
            print(f"   GCSバケット: {self.bucket_name}")
            print(f"   GCSファイル名: {gcs_file_name}")
            print("-" * 60)

            # ローカルファイル読み込み
            if not os.path.exists(local_mapping_file):
                print(f"❌ ローカルファイルが存在しません: {local_mapping_file}")
                return False

            with open(local_mapping_file, 'r', encoding='utf-8') as f:
                local_data = json.load(f)

            # Cloud環境用にメタデータを追加
            cloud_data = {
                'version': local_data.get('version', '1.0'),
                'created_at': local_data.get('created_at', datetime.now().isoformat()),
                'last_updated': datetime.now().isoformat(),
                'deployed_at': datetime.now().isoformat(),
                'email_to_notion_id': local_data.get('email_to_notion_id', {}),
                'deployment_info': {
                    'source': 'local_deployment',
                    'original_file': local_mapping_file,
                    'deployer': 'deploy_mapping_to_gcs.py',
                    'environment': 'cloud_run'
                }
            }

            # ユーザー数表示
            user_count = len(cloud_data['email_to_notion_id'])
            print(f"📋 デプロイ対象ユーザー数: {user_count}人")

            if user_count > 0:
                print("👥 ユーザー一覧:")
                for email, user_data in cloud_data['email_to_notion_id'].items():
                    print(f"   - {user_data.get('name', 'Unknown')} ({email})")

            # GCSにアップロード
            blob = self.bucket.blob(gcs_file_name)
            cloud_json = json.dumps(cloud_data, indent=2, ensure_ascii=False)

            blob.upload_from_string(cloud_json, content_type='application/json')

            print(f"✅ GCSデプロイ完了!")
            print(f"   GCS URL: gs://{self.bucket_name}/{gcs_file_name}")
            print(f"   ユーザー数: {user_count}人")

            return True

        except Exception as e:
            print(f"❌ デプロイエラー: {e}")
            return False

    def verify_gcs_mapping(self, gcs_file_name: str = "user_mapping.json") -> bool:
        """GCSのマッピングファイルを検証"""
        try:
            print(f"\n🔍 GCSマッピングファイル検証")
            print("-" * 60)

            blob = self.bucket.blob(gcs_file_name)

            if not blob.exists():
                print(f"❌ GCSファイルが存在しません: gs://{self.bucket_name}/{gcs_file_name}")
                return False

            # ファイル情報表示
            blob.reload()
            print(f"✅ ファイル存在確認: gs://{self.bucket_name}/{gcs_file_name}")
            print(f"   サイズ: {blob.size} bytes")
            print(f"   更新日時: {blob.updated}")
            print(f"   Content-Type: {blob.content_type}")

            # 内容確認
            content = blob.download_as_text()
            data = json.loads(content)

            user_count = len(data.get('email_to_notion_id', {}))
            print(f"   ユーザー数: {user_count}人")
            print(f"   最終更新: {data.get('last_updated', 'Unknown')}")
            print(f"   バージョン: {data.get('version', 'Unknown')}")

            if data.get('deployment_info'):
                deploy_info = data['deployment_info']
                print(f"   デプロイ情報:")
                print(f"     - デプロイ日時: {data.get('deployed_at', 'Unknown')}")
                print(f"     - 環境: {deploy_info.get('environment', 'Unknown')}")
                print(f"     - ソース: {deploy_info.get('source', 'Unknown')}")

            return True

        except Exception as e:
            print(f"❌ 検証エラー: {e}")
            return False

    def create_bucket_if_not_exists(self) -> bool:
        """バケットが存在しない場合は作成"""
        try:
            bucket = self.client.bucket(self.bucket_name)
            if not bucket.exists():
                print(f"🪣 GCSバケットを作成: {self.bucket_name}")
                bucket = self.client.create_bucket(self.bucket_name)
                print(f"✅ バケット作成完了: {self.bucket_name}")
            else:
                print(f"✅ バケット存在確認: {self.bucket_name}")

            return True

        except Exception as e:
            print(f"❌ バケット作成/確認エラー: {e}")
            return False


def main():
    """メイン実行関数"""
    parser = argparse.ArgumentParser(description='ローカルマッピングファイルをGCSにデプロイ')
    parser.add_argument('--bucket', required=True, help='GCSバケット名')
    parser.add_argument('--local-file', default='.user_mapping.json', help='ローカルマッピングファイル (デフォルト: .user_mapping.json)')
    parser.add_argument('--gcs-file', default='user_mapping.json', help='GCSファイル名 (デフォルト: user_mapping.json)')
    parser.add_argument('--service-account', help='サービスアカウントキーファイルのパス')
    parser.add_argument('--verify-only', action='store_true', help='デプロイせず検証のみ実行')

    args = parser.parse_args()

    print("🎯 Notion ユーザーマッピング GCS デプロイツール")
    print("=" * 60)

    # デプロイヤー初期化
    deployer = MappingDeployer(args.bucket, args.service_account)

    if args.verify_only:
        # 検証のみ
        success = deployer.verify_gcs_mapping(args.gcs_file)
    else:
        # バケット確認/作成
        if not deployer.create_bucket_if_not_exists():
            print("❌ バケットの準備に失敗しました")
            return

        # デプロイ実行
        success = deployer.deploy_local_mapping(args.local_file, args.gcs_file)

        if success:
            # デプロイ後の検証
            deployer.verify_gcs_mapping(args.gcs_file)

    if success:
        print(f"\n🎉 {'検証' if args.verify_only else 'デプロイ'}完了!")
        if not args.verify_only:
            print(f"\n💡 次のステップ:")
            print(f"   1. Cloud Runの環境変数にGCSバケット名を設定:")
            print(f"      GCS_BUCKET_NAME={args.bucket}")
            print(f"   2. Cloud RunサービスにGCS読み書き権限を付与")
            print(f"   3. アプリケーションをデプロイ")
    else:
        print(f"\n❌ {'検証' if args.verify_only else 'デプロイ'}に失敗しました")


if __name__ == "__main__":
    main()