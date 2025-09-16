from typing import List, Dict, Optional, Union
import json
import time
import random
import threading
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
import asyncio
import concurrent.futures
from google import genai
from google.genai import types


@dataclass
class ConversationMessage:
    """会話メッセージ"""
    role: str  # "user" or "model"
    content: str
    timestamp: datetime


@dataclass
class TaskInfo:
    """タスク情報"""
    title: str
    task_type: Optional[str] = None
    urgency: Optional[str] = None
    due_date: Optional[str] = None
    current_description: Optional[str] = None


@dataclass
class AIAnalysisResult:
    """AI分析結果"""
    status: str  # "insufficient_info" or "ready_to_format"
    message: str
    suggestions: Optional[List[str]] = None
    formatted_content: Optional[str] = None


class ConversationHistory:
    """会話履歴管理"""

    def __init__(self, storage_path: Optional[Union[str, Path]] = None):
        self.lock = threading.Lock()
        self.storage_path = Path(storage_path) if storage_path else Path(".ai_conversations.json")
        self.conversations: Dict[str, List[ConversationMessage]] = {}
        self._load_from_disk()

    def _load_from_disk(self):
        try:
            if self.storage_path.exists():
                data = json.loads(self.storage_path.read_text(encoding="utf-8"))
                for sid, msgs in data.items():
                    self.conversations[sid] = [
                        ConversationMessage(
                            role=m.get("role", "user"),
                            content=m.get("content", ""),
                            timestamp=datetime.fromisoformat(m.get("timestamp"))
                            if m.get("timestamp")
                            else datetime.now(),
                        )
                        for m in msgs
                    ]
        except Exception:
            # 読み込み失敗時は空として扱う（壊れたファイルでも稼働を止めない）
            self.conversations = {}

    def _flush_to_disk(self):
        try:
            payload = {
                sid: [
                    {
                        "role": m.role,
                        "content": m.content,
                        "timestamp": m.timestamp.isoformat(),
                    }
                    for m in msgs
                ]
                for sid, msgs in self.conversations.items()
            }
            tmp_path = self.storage_path.with_suffix(self.storage_path.suffix + ".tmp")
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp_path.replace(self.storage_path)
        except Exception:
            # 書き込み失敗は致命的ではないため握りつぶす（ログは標準出力側に任せる）
            pass


class InMemoryConversationHistory:
    """メモリ内のみで管理する会話履歴（一時的なセッション用）"""

    def __init__(self):
        self.lock = threading.Lock()
        self.conversations: Dict[str, List[ConversationMessage]] = {}

    def add_message(self, session_id: str, role: str, content: str):
        """メッセージを追加"""
        with self.lock:
            if session_id not in self.conversations:
                self.conversations[session_id] = []
            message = ConversationMessage(role=role, content=content, timestamp=datetime.now())
            self.conversations[session_id].append(message)
            # メモリ内なので、ディスクフラッシュは不要（空実装）

    def get_conversation(self, session_id: str) -> List[ConversationMessage]:
        """会話履歴を取得"""
        with self.lock:
            return list(self.conversations.get(session_id, []))

    def clear_conversation(self, session_id: str):
        """会話履歴をクリア"""
        with self.lock:
            if session_id in self.conversations:
                del self.conversations[session_id]

    def start_new_session(self, session_id: str):
        """新しいセッションを開始（既存の会話をクリア）"""
        with self.lock:
            self.conversations[session_id] = []

    def _flush_to_disk(self):
        """メモリ内クラスなので何もしない（互換性のため）"""
        pass


class TaskAIService:
    """タスクコンテンツAI拡張サービス"""

    def __init__(self, api_key: str, timeout_seconds: float = 30.0, model_name: str = "gemini-2.5-flash", history_storage_path: Optional[str] = None):
        self.client = genai.Client(api_key=api_key)
        # メモリ内のみで会話履歴を管理（フォーム入力時のみの一時的な使用）
        self.history = InMemoryConversationHistory()
        self.timeout_seconds = timeout_seconds
        self.model_name = model_name
        self.max_retries = 3
        
        # システム指示（簡潔かつ構造化応答を強制）
        self.system_instruction = """あなたはタスク管理の補助AIです。提供された情報をもとに、実行可能なタスク提案を行います。

必ず次のルールに従ってください：
- 返答はJSONのみ。前後に説明やコードブロック、コメントは付与しない。
- スキーマに準拠：statusは"insufficient_info"または"ready_to_format"。
- insufficientの場合、reasonと具体的なquestions配列（簡潔な日本語の質問文）を返す。
- readyの場合、suggestion.descriptionにマークダウン形式で以下の順序で記述する（必ず各セクション間に改行\\nを入れる）：
  ## 目的・背景\\n（目的や背景を記述）\\n\\n## 作業内容\\n1. （具体的な手順1）\\n2. （具体的な手順2）\\n\\n## 完了条件\\n（完了の判断基準）\\n\\n## 注意点\\n（重要な注意事項）
  可能ならtitle, category, urgency, due_date_isoも補完する（不明なら省略可）。

分類の指針（参考）：
- 社内タスク / 技術調査 / 顧客対応 / 営業連絡 / 要件定義 / 資料作成 / その他

簡潔で、すぐ実行可能な形に整えてください。"""

        # デフォルトのモデル名（上位から注入される想定）
        if not hasattr(self, "model_name"):
            self.model_name = "gemini-2.5-flash"
    
    def _response_schema(self) -> types.Schema:
        """Geminiの構造化出力スキーマを定義"""
        return types.Schema(
            type=types.Type.OBJECT,
            properties={
                "status": types.Schema(type=types.Type.STRING, enum=["insufficient_info", "ready_to_format"]),
                "reason": types.Schema(type=types.Type.STRING),
                "questions": types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(type=types.Type.STRING),
                ),
                "suggestion": types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "title": types.Schema(type=types.Type.STRING),
                        "category": types.Schema(type=types.Type.STRING),
                        "urgency": types.Schema(type=types.Type.STRING),
                        "due_date_iso": types.Schema(type=types.Type.STRING),
                        "description": types.Schema(type=types.Type.STRING),
                    },
                ),
            },
        )

    def _build_contents(self, session_id: str, user_text: Optional[str] = None) -> List[types.Content]:
        """履歴 + 直近ユーザー指示からContentsを作る"""
        contents: List[types.Content] = []
        conversation = self.history.get_conversation(session_id)

        print(f"🔍 [_build_contents] セッション {session_id}: 履歴数={len(conversation)}")

        for i, msg in enumerate(conversation):
            role = "user" if msg.role == "user" else "model"
            print(f"  履歴[{i}] {role}: {msg.content[:100]}...")
            contents.append(
                types.Content(role=role, parts=[types.Part.from_text(text=msg.content)])
            )

        if user_text:
            print(f"  新規ユーザー入力: {user_text[:100]}...")
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_text)]))

        print(f"🔍 [_build_contents] 最終的なcontents数: {len(contents)}")
        return contents

    def _call_ai_with_timeout(self, contents: Union[str, List[types.Content]], timeout: Optional[float] = None) -> str:
        """タイムアウト + リトライ付きでAIを呼び出す"""
        effective_timeout = timeout or self.timeout_seconds
        def call_ai():
            attempts = self.max_retries
            last_err: Optional[Exception] = None
            for i in range(attempts):
                try:
                    response = self.client.models.generate_content(
                        model=self.model_name,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            thinking_config=types.ThinkingConfig(thinking_budget=0),
                            max_output_tokens=1000,
                            temperature=0.2,
                            system_instruction=self.system_instruction,
                            response_mime_type="application/json",
                            response_schema=self._response_schema(),
                        ),
                    )
                    return response.text
                except Exception as e:
                    msg = str(e).lower()
                    retryable = any(k in msg for k in [
                        "unavailable", "overloaded", "please try again", "deadline", "temporarily", "resource exhausted", "rate"
                    ])
                    last_err = e
                    if retryable and i < attempts - 1:
                        # 指数バックオフ + ジッタ
                        sleep_s = (0.6 * (2 ** i)) + random.uniform(0, 0.3)
                        time.sleep(sleep_s)
                        continue
                    raise

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(call_ai)
            try:
                return future.result(timeout=effective_timeout)
            except concurrent.futures.TimeoutError:
                raise Exception("AI processing timeout - 処理時間が長すぎます")
    
    async def _call_ai_with_timeout_async(self, contents: Union[str, List[types.Content]], timeout: Optional[float] = None) -> str:
        """非同期でタイムアウト + リトライ付きでAIを呼び出す"""
        import asyncio
        effective_timeout = timeout or self.timeout_seconds
        
        def call_ai():
            attempts = self.max_retries
            last_err: Optional[Exception] = None
            for i in range(attempts):
                try:
                    response = self.client.models.generate_content(
                        model=self.model_name,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            thinking_config=types.ThinkingConfig(thinking_budget=0),
                            max_output_tokens=1000,
                            temperature=0.2,
                            system_instruction=self.system_instruction,
                            response_mime_type="application/json",
                            response_schema=self._response_schema(),
                        ),
                    )
                    return response.text
                except Exception as e:
                    last_err = e
                    print(f"❌ AI call attempt {i+1}/{attempts} failed: {e}")
                    if i < attempts - 1:
                        time.sleep(2 ** i)  # 指数バックオフ
            raise last_err or Exception("All attempts failed")
        
        # 別スレッドで実行して非ブロッキング化
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, call_ai)
        except asyncio.TimeoutError:
            raise Exception("AI processing timeout - 処理時間が長すぎます")
    
    async def analyze_task_info(self, session_id: str, task_info: TaskInfo) -> AIAnalysisResult:
        """タスク情報を分析"""
        try:
            print(f"🤖 AI分析開始: session_id={session_id}")
            # 現在のタスク情報をプロンプトに整理
            prompt = self._build_analysis_prompt(task_info)
            print(f"🔍 プロンプト作成完了: {len(prompt)}文字")
            # 履歴にユーザー発話を追加し、履歴込みのcontentsを構築
            self.history.add_message(session_id, "user", prompt)
            contents = self._build_contents(session_id)
            print(f"🔍 コンテンツ構築完了: {len(str(contents))}文字")
            # タイムアウト（設定値）付きでGemini APIに送信（構造化JSONを期待）
            print("🔍 Gemini API呼び出し開始...")
            response_text = await self._call_ai_with_timeout_async(contents)
            print(f"✅ Gemini API呼び出し完了: {len(response_text)}文字")
            
            # レスポンスを会話履歴に追加
            self.history.add_message(session_id, "model", response_text)
            
            # レスポンスを解析
            print("🔍 レスポンス解析中...")
            result = self._parse_ai_response(response_text)
            print(f"✅ AI分析完了: status={result.status}")
            return result
            
        except Exception as e:
            print(f"❌ AI analysis error: {e}")
            return AIAnalysisResult(
                status="error",
                message=f"AI分析でエラーが発生しました: {str(e)}"
            )
    
    async def refine_content(self, session_id: str, feedback: str) -> AIAnalysisResult:
        """ユーザーフィードバックを基にコンテンツを改良"""
        try:
            print(f"🔄 AI改良開始: session_id={session_id}")
            user_turn = f"以下のフィードバックを反映して改善してください。必要なら不足点も質問してください。\n{feedback}"
            # 履歴にユーザー発話を追加し、履歴込みのcontentsを構築
            self.history.add_message(session_id, "user", user_turn)
            contents = self._build_contents(session_id)
            # タイムアウト（設定値）付きでGemini APIに送信（構造化JSONを期待）
            print("🔍 Gemini API呼び出し開始（改良）...")
            response_text = await self._call_ai_with_timeout_async(contents)
            print(f"✅ Gemini API呼び出し完了（改良）: {len(response_text)}文字")
            
            # レスポンスを会話履歴に追加
            self.history.add_message(session_id, "model", response_text)
            
            result = self._parse_ai_response(response_text)
            print(f"✅ AI改良完了: status={result.status}")
            return result
            
        except Exception as e:
            print(f"❌ AI refinement error: {e}")
            return AIAnalysisResult(
                status="error", 
                message=f"AI改良でエラーが発生しました: {str(e)}"
            )
    
    def clear_session(self, session_id: str):
        """セッションをクリア"""
        self.history.clear_conversation(session_id)
    
    def _build_analysis_prompt(self, task_info: TaskInfo) -> str:
        """分析用プロンプトを構築"""
        prompt_parts = [
            "以下のタスク情報を分析してください：",
            "",
            f"タイトル: {task_info.title}"
        ]
        
        if task_info.task_type:
            prompt_parts.append(f"タスク種類: {task_info.task_type}")
        if task_info.urgency:
            prompt_parts.append(f"緊急度: {task_info.urgency}")
        if task_info.due_date:
            prompt_parts.append(f"納期: {task_info.due_date}")
        if task_info.current_description:
            prompt_parts.append(f"現在の内容: {task_info.current_description}")
        
        return "\n".join(prompt_parts)
    
    def _parse_ai_response(self, response_text: str) -> AIAnalysisResult:
        """AIレスポンスを解析（JSON優先、失敗時はフォールバック）"""
        # 1) まずJSONとして解釈
        try:
            data = json.loads(response_text)
            status = data.get("status")

            if status == "insufficient_info":
                reason = data.get("reason") or "追加情報が必要です。"
                questions = data.get("questions") or []
                # 文字列で来ることも考慮
                if isinstance(questions, str):
                    questions = [questions]
                return AIAnalysisResult(
                    status="insufficient_info",
                    message=reason,
                    suggestions=questions,
                )

            if status in ("ready_to_format", "ready"):
                suggestion = data.get("suggestion") or {}
                desc = suggestion.get("description")
                if not desc:
                    # 最低限の整形を行う
                    title = suggestion.get("title") or "タスク"
                    category = suggestion.get("category")
                    urgency = suggestion.get("urgency")
                    due = suggestion.get("due_date_iso")
                    meta = []
                    if category:
                        meta.append(f"カテゴリ: {category}")
                    if urgency:
                        meta.append(f"緊急度: {urgency}")
                    if due:
                        meta.append(f"納期: {due}")
                    meta_text = ("\n" + " / ".join(meta)) if meta else ""
                    desc = f"【{title}】{meta_text}\n\n## 目的・背景\n不明確な点はありません。\n\n## 作業内容\n1. 必要な手順を実施してください。\n\n## 完了条件\n合意済みの受け入れ基準を満たすこと。\n\n## 注意点\n関係者との認識合わせを行ってください。"

                return AIAnalysisResult(
                    status="ready_to_format",
                    message="生成に成功しました",
                    formatted_content=desc.strip(),
                )
        except Exception:
            pass

        # 2) フォールバック：キーワードベース
        try:
            lines = response_text.split("\n")
            if any(keyword in response_text.lower() for keyword in ["不足", "足りない", "必要です", "教えて", "どの"]):
                suggestions = []
                for line in lines:
                    if "?" in line or "？" in line or line.strip().startswith("-"):
                        suggestions.append(line.strip())
                if not suggestions:
                    suggestions = ["追加の情報を教えてください。"]
                return AIAnalysisResult(
                    status="insufficient_info",
                    message=response_text,
                    suggestions=suggestions,
                )
            # それ以外は完成コンテンツとして扱う
            return AIAnalysisResult(
                status="ready_to_format",
                message="生成に成功しました",
                formatted_content=response_text.strip(),
            )
        except Exception as e:
            print(f"❌ Response parsing error: {e}")
            return AIAnalysisResult(status="error", message=f"レスポンス解析エラー: {str(e)}")
