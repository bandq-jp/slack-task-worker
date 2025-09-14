from typing import List, Dict, Optional
import json
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
    
    def __init__(self):
        self.conversations: Dict[str, List[ConversationMessage]] = {}
    
    def add_message(self, session_id: str, role: str, content: str):
        """メッセージを追加"""
        if session_id not in self.conversations:
            self.conversations[session_id] = []
        
        message = ConversationMessage(
            role=role,
            content=content,
            timestamp=datetime.now()
        )
        self.conversations[session_id].append(message)
    
    def get_conversation(self, session_id: str) -> List[ConversationMessage]:
        """会話履歴を取得"""
        return self.conversations.get(session_id, [])
    
    def clear_conversation(self, session_id: str):
        """会話履歴をクリア"""
        if session_id in self.conversations:
            del self.conversations[session_id]
    


class TaskAIService:
    """タスクコンテンツAI拡張サービス"""
    
    def __init__(self, api_key: str, timeout_seconds: float = 30.0, model_name: str = "gemini-2.5-flash"):
        self.client = genai.Client(api_key=api_key)
        self.history = ConversationHistory()
        self.timeout_seconds = timeout_seconds
        self.model_name = model_name
        
        # システム指示（簡潔かつ構造化応答を強制）
        self.system_instruction = """あなたはタスク管理の補助AIです。提供された情報をもとに、実行可能なタスク提案を行います。

必ず次のルールに従ってください：
- 返答はJSONのみ。前後に説明やコードブロック、コメントは付与しない。
- スキーマに準拠：statusは"insufficient_info"または"ready_to_format"。
- insufficientの場合、reasonと具体的なquestions配列（簡潔な日本語の質問文）を返す。
- readyの場合、suggestion.descriptionに日本語で以下の順序で記述する：
  1) 目的・背景\n 2) 作業内容（番号付き手順）\n 3) 完了条件\n 4) 注意点
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

    def _call_ai_with_timeout(self, prompt: str, timeout: Optional[float] = None) -> str:
        """タイムアウト付きでAIを呼び出す"""
        effective_timeout = timeout or self.timeout_seconds
        def call_ai():
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                    max_output_tokens=800,
                    temperature=0.2,
                    # 構造化出力を要求
                    response_mime_type="application/json",
                    response_schema=self._response_schema(),
                ),
            )
            # google.genaiは構造化設定時も.textにJSONが入る
            return response.text
        
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(call_ai)
            try:
                return future.result(timeout=effective_timeout)
            except concurrent.futures.TimeoutError:
                raise Exception("AI processing timeout - 処理時間が長すぎます")
    
    def analyze_task_info(self, session_id: str, task_info: TaskInfo) -> AIAnalysisResult:
        """タスク情報を分析"""
        try:
            # 現在のタスク情報をプロンプトに整理
            prompt = self._build_analysis_prompt(task_info)
            
            # 会話履歴に追加
            self.history.add_message(session_id, "user", prompt)
            
            # システム指示とユーザープロンプトを組み合わせ
            full_prompt = f"{self.system_instruction}\n\n{prompt}"
            
            # タイムアウト（設定値）付きでGemini APIに送信（構造化JSONを期待）
            response_text = self._call_ai_with_timeout(full_prompt)
            
            # レスポンスを会話履歴に追加
            self.history.add_message(session_id, "model", response_text)
            
            # レスポンスを解析
            return self._parse_ai_response(response_text)
            
        except Exception as e:
            print(f"❌ AI analysis error: {e}")
            return AIAnalysisResult(
                status="error",
                message=f"AI分析でエラーが発生しました: {str(e)}"
            )
    
    def refine_content(self, session_id: str, feedback: str) -> AIAnalysisResult:
        """ユーザーフィードバックを基にコンテンツを改良"""
        try:
            prompt = f"前回の提案について以下のフィードバックがありました。改良してください：\n{feedback}"
            
            # 会話履歴に追加
            self.history.add_message(session_id, "user", prompt)
            
            # 会話履歴を構築
            conversation_history = self.history.get_conversation(session_id)
            
            # システム指示と会話履歴を組み合わせ
            full_context = f"{self.system_instruction}\n\n"
            for msg in conversation_history:
                role_label = "ユーザー" if msg.role == "user" else "アシスタント"
                full_context += f"{role_label}: {msg.content}\n"
            
            # タイムアウト（設定値）付きでGemini APIに送信（構造化JSONを期待）
            response_text = self._call_ai_with_timeout(full_context)
            
            # レスポンスを会話履歴に追加
            self.history.add_message(session_id, "model", response_text)
            
            return self._parse_ai_response(response_text)
            
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
                    desc = f"【{title}】{meta_text}\n\n1) 目的・背景\n- 不明確な点はありません。\n\n2) 作業内容\n- 必要な手順を実施してください。\n\n3) 完了条件\n- 合意済みの受け入れ基準を満たすこと。\n\n4) 注意点\n- 関係者との認識合わせを行ってください。"

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
