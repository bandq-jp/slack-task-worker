from typing import Union, Dict, Any


def convert_rich_text_to_plain_text(rich_text_data: Union[str, Dict[str, Any], None]) -> str:
    """
    Slackリッチテキストオブジェクトをプレーンテキストに変換
    
    Args:
        rich_text_data: Slackのリッチテキストオブジェクト、文字列、またはNone
    
    Returns:
        プレーンテキスト文字列
    """
    if not rich_text_data:
        return ""
    
    if isinstance(rich_text_data, str):
        return rich_text_data
    
    if not isinstance(rich_text_data, dict):
        return str(rich_text_data)
    
    try:
        text_parts = []
        
        if "elements" in rich_text_data:
            for element in rich_text_data["elements"]:
                if element.get("type") == "rich_text_section":
                    # テキストセクション
                    for item in element.get("elements", []):
                        if item.get("type") == "text":
                            text_parts.append(item.get("text", ""))
                        elif item.get("type") == "link":
                            text_parts.append(item.get("text", item.get("url", "")))
                
                elif element.get("type") == "rich_text_list":
                    # リスト要素
                    style = element.get("style", "bulleted")
                    list_items = []
                    
                    for i, list_item in enumerate(element.get("elements", []), 1):
                        if list_item.get("type") == "rich_text_section":
                            item_text = ""
                            for item in list_item.get("elements", []):
                                if item.get("type") == "text":
                                    item_text += item.get("text", "")
                            
                            if item_text.strip():  # 空でない場合のみ追加
                                if style == "ordered":
                                    list_items.append(f"{i}. {item_text}")
                                else:
                                    list_items.append(f"• {item_text}")
                    
                    if list_items:
                        text_parts.append("\n" + "\n".join(list_items))
                
                elif element.get("type") == "rich_text_preformatted":
                    # コードブロック
                    code_text = ""
                    for item in element.get("elements", []):
                        if item.get("type") == "text":
                            code_text += item.get("text", "")
                    text_parts.append(f"```\n{code_text}\n```")
                
                elif element.get("type") == "rich_text_quote":
                    # 引用
                    quote_text = ""
                    for item in element.get("elements", []):
                        if item.get("type") == "text":
                            quote_text += item.get("text", "")
                    text_parts.append(f"> {quote_text}")
        
        result = "".join(text_parts).strip()
        return result if result else ""
        
    except Exception as e:
        print(f"❌ リッチテキスト変換エラー: {e}")
        # フォールバック: 辞書を文字列表現で返す
        return str(rich_text_data)