from typing import List, Dict, Optional
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
    
    def __init__(self, api_key: str, timeout_seconds: float = 30.0):
        self.client = genai.Client(api_key=api_key)
        self.history = ConversationHistory()
        self.timeout_seconds = timeout_seconds
        
        # システム指示（高速化のため簡潔に）
        self.system_instruction = """タスク管理AI：提供情報から実行可能なタスクを作成

**判定基準:**
- 十分な情報があれば → "ready_to_format" で詳細タスクを作成
- 情報不足なら → "insufficient_info" で必要な質問を提示

**出力形式（充足時）:**
目的・背景 → 作業内容（ステップ別） → 完了条件 → 注意点

**考慮事項（タスク種類別）:**
フリーランス：契約・納期・仕様 / 技術：要件・テスト / 社内：関係者・プロセス / 営業：ターゲット・提案

簡潔で実行可能なタスクを作成してください。"""
    
    def _call_ai_with_timeout(self, prompt: str, timeout: Optional[float] = None) -> str:
        """タイムアウト付きでAIを呼び出す"""
        effective_timeout = timeout or self.timeout_seconds
        def call_ai():
            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    # thinking機能を無効にして高速化
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                    # 出力トークン数制限
                    max_output_tokens=800,
                    # 温度設定（一貫性を重視）
                    temperature=0.2
                )
            )
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
            
            # タイムアウト（設定値）付きでGemini APIに送信
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
            
            # タイムアウト（設定値）付きでGemini APIに送信
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
        """AIレスポンスを解析"""
        try:
            # 簡単なパターンマッチングでレスポンスを解析
            lines = response_text.split('\n')
            
            # デフォルト値
            status = "ready_to_format"
            message = response_text
            suggestions = None
            formatted_content = None
            
            # キーワードベースの判定
            if any(keyword in response_text.lower() for keyword in ["不足", "足りない", "必要です", "教えて", "どの"]):
                status = "insufficient_info"
                # 質問部分を抽出（簡易版）
                suggestions = []
                for line in lines:
                    if "?" in line or "？" in line or line.strip().startswith("-"):
                        suggestions.append(line.strip())
                if not suggestions:
                    suggestions = ["追加の情報を教えてください。"]
            else:
                # 整形されたコンテンツとして扱う
                formatted_content = response_text.strip()
            
            return AIAnalysisResult(
                status=status,
                message=message,
                suggestions=suggestions,
                formatted_content=formatted_content
            )
            
        except Exception as e:
            print(f"❌ Response parsing error: {e}")
            return AIAnalysisResult(
                status="error",
                message=f"レスポンス解析エラー: {str(e)}"
            )
