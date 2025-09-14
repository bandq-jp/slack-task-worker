#!/usr/bin/env python3
"""
Google Cloud Storage対応のユーザーマッピング管理
Cloud Run環境でファイルの永続化を実現
"""
import json
import os
from typing import Dict, Any, Optional
from datetime import datetime
from google.cloud import storage
import logging

logger = logging.getLogger(__name__)

class GCSUserMappingManager:
    """Google Cloud Storageを使用したユーザーマッピング管理"""

    def __init__(self, bucket_name: str, mapping_file_name: str = "user_mapping.json"):
        self.bucket_name = bucket_name
        self.mapping_file_name = mapping_file_name
        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket_name)
        self.blob = self.bucket.blob(mapping_file_name)
        self._local_cache = None
        self._cache_timestamp = None

    def _is_cache_valid(self, max_age_seconds: int = 300) -> bool:
        """キャッシュが有効かチェック（デフォルト5分）"""
        if not self._cache_timestamp:
            return False

        age = (datetime.now() - self._cache_timestamp).total_seconds()
        return age < max_age_seconds

    async def load_mapping(self, use_cache: bool = True) -> Dict[str, Dict[str, Any]]:
        """マッピングファイルをGCSから読み込み"""
        try:
            # キャッシュ使用可能な場合はキャッシュを返す
            if use_cache and self._local_cache and self._is_cache_valid():
                logger.info(f"✅ キャッシュからマッピング読み込み: {len(self._local_cache)}人")
                return self._local_cache

            # GCSからファイルを取得
            if self.blob.exists():
                mapping_json = self.blob.download_as_text()
                mapping_data = json.loads(mapping_json)

                email_mapping = mapping_data.get('email_to_notion_id', {})

                # キャッシュ更新
                self._local_cache = email_mapping
                self._cache_timestamp = datetime.now()

                logger.info(f"✅ GCSからマッピング読み込み: {len(email_mapping)}人")
                return email_mapping
            else:
                logger.warning("⚠️ GCSにマッピングファイルが存在しません")
                return {}

        except Exception as e:
            logger.error(f"❌ GCSマッピング読み込みエラー: {e}")
            # フォールバック: キャッシュがある場合はそれを使用
            if self._local_cache:
                logger.info("📦 フォールバック: キャッシュを使用")
                return self._local_cache
            return {}

    async def save_mapping(self, user_mapping: Dict[str, Dict[str, Any]]) -> bool:
        """マッピングファイルをGCSに保存"""
        try:
            mapping_data = {
                'version': '1.0',
                'created_at': datetime.now().isoformat(),
                'last_updated': datetime.now().isoformat(),
                'email_to_notion_id': user_mapping,
                'metadata': {
                    'total_users': len(user_mapping),
                    'environment': 'cloud_run',
                    'storage_type': 'gcs'
                }
            }

            # GCSにアップロード
            mapping_json = json.dumps(mapping_data, indent=2, ensure_ascii=False)
            self.blob.upload_from_string(mapping_json, content_type='application/json')

            # キャッシュ更新
            self._local_cache = user_mapping
            self._cache_timestamp = datetime.now()

            logger.info(f"✅ GCSにマッピング保存完了: {len(user_mapping)}人")
            return True

        except Exception as e:
            logger.error(f"❌ GCSマッピング保存エラー: {e}")
            return False

    async def add_user_to_mapping(self, email: str, user_data: Dict[str, Any]) -> bool:
        """新規ユーザーをマッピングに追加"""
        try:
            # 現在のマッピングを取得
            current_mapping = await self.load_mapping()

            # ユーザー追加
            email_lower = email.lower()
            current_mapping[email_lower] = {
                'id': user_data['id'],
                'name': user_data['name'],
                'email': email,
                'type': user_data.get('type', 'person'),
                'object': user_data.get('object', 'user'),
                'avatar_url': user_data.get('avatar_url'),
                'last_updated': datetime.now().isoformat(),
                'auto_discovered': True
            }

            # GCSに保存
            success = await self.save_mapping(current_mapping)

            if success:
                logger.info(f"✅ ユーザー自動追加: {user_data['name']} ({email})")

            return success

        except Exception as e:
            logger.error(f"❌ ユーザー追加エラー: {e}")
            return False

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """メールアドレスでユーザーを検索"""
        try:
            mapping = await self.load_mapping()
            user_data = mapping.get(email.lower())

            if user_data:
                # Notion User オブジェクト形式で返す
                return {
                    'id': user_data['id'],
                    'object': user_data.get('object', 'user'),
                    'type': user_data.get('type', 'person'),
                    'name': user_data['name'],
                    'avatar_url': user_data.get('avatar_url'),
                    'person': {'email': user_data['email']}
                }

            return None

        except Exception as e:
            logger.error(f"❌ ユーザー検索エラー: {e}")
            return None

    async def refresh_cache(self) -> bool:
        """キャッシュを強制更新"""
        try:
            self._local_cache = None
            self._cache_timestamp = None
            mapping = await self.load_mapping(use_cache=False)
            return len(mapping) > 0
        except Exception as e:
            logger.error(f"❌ キャッシュ更新エラー: {e}")
            return False