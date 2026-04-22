"""
解析 OpenResponses 兼容 API 的 SSE / JSON 响应（与具体品牌无关）。
"""

from typing import Any


class ResponseParser:
    """OpenResponses 风格响应解析器"""

    @staticmethod
    def extract_text_from_output(output: list[dict[str, Any]]) -> str | None:
        if not output or not isinstance(output, list):
            return None

        texts = []
        for item in output:
            text = ResponseParser._extract_text_from_item(item)
            if text:
                texts.append(text)

        return "\n".join(texts) if texts else None

    @staticmethod
    def _extract_text_from_item(item: Any) -> str | None:
        if isinstance(item, str):
            return item

        if not isinstance(item, dict):
            return None

        item_type = item.get("type", "")

        if item_type == "text" and "content" in item:
            return item["content"]

        if item_type == "message" and "content" in item:
            return ResponseParser._extract_text_from_content(item["content"])

        for key in ["text", "content", "message"]:
            if key in item:
                value = item[key]
                if isinstance(value, str) and value:
                    return value
                if isinstance(value, list):
                    text = ResponseParser._extract_text_from_content(value)
                    if text:
                        return text

        return None

    @staticmethod
    def _extract_text_from_content(content: Any) -> str | None:
        if isinstance(content, str):
            return content

        if not isinstance(content, list):
            return None

        texts = []
        for content_item in content:
            if isinstance(content_item, str):
                texts.append(content_item)
            elif isinstance(content_item, dict):
                if content_item.get("type") == "output_text" and "text" in content_item:
                    text = content_item["text"]
                    if text:
                        texts.append(text)
                elif "text" in content_item:
                    text = content_item["text"]
                    if text:
                        texts.append(text)

        return "\n".join(texts) if texts else None

    @staticmethod
    def parse_sse_event(data: dict[str, Any]) -> dict[str, Any]:
        event_type = data.get("type", "")
        result = {
            "type": event_type,
            "text": None,
            "is_done": False,
            "is_error": False,
            "error_message": None,
        }

        if event_type == "response.output_text.delta":
            result["text"] = data.get("delta", "")

        elif event_type == "response.output_text.done":
            result["text"] = data.get("text", "")
            result["is_done"] = True

        elif event_type == "response.completed":
            result["is_done"] = True
            response_obj = data.get("response", {})
            if response_obj:
                output = response_obj.get("output", [])
                result["text"] = ResponseParser.extract_text_from_output(output)
                result["status"] = response_obj.get("status", "")

        elif event_type == "response.failed":
            result["is_error"] = True
            result["is_done"] = True
            error_obj = data.get("response", {}).get("error", {})
            result["error_message"] = error_obj.get("message", "Unknown error")

        return result

    @staticmethod
    def parse_json_response(result: dict[str, Any]) -> str | None:
        if "output" in result and isinstance(result["output"], list):
            text = ResponseParser.extract_text_from_output(result["output"])
            if text:
                return text

        if "choices" in result and len(result["choices"]) > 0:
            content = result["choices"][0].get("message", {}).get("content", "")
            if content:
                return content

        if "content" in result:
            return result["content"]

        return None
