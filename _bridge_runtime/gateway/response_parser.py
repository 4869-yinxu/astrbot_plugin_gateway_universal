"""
OpenClaw Gateway 响应解析器

负责解析 OpenResponses API 的各种响应格式
"""

from typing import Any


class ResponseParser:
    """OpenResponses 响应解析器"""

    @staticmethod
    def extract_text_from_output(output: list[dict[str, Any]]) -> str | None:
        """从 output 数组中提取文本内容

        支持多种格式：
        - { "type": "text", "content": "..." }
        - { "type": "message", "content": [{ "type": "output_text", "text": "..." }] }
        - 直接字符串

        Args:
            output: OpenResponses 的 output 数组

        Returns:
            提取的文本内容，如果没有则返回 None
        """
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
        """从单个 output 项中提取文本"""
        if isinstance(item, str):
            return item

        if not isinstance(item, dict):
            return None

        item_type = item.get("type", "")

        # 格式1: { "type": "text", "content": "..." }
        if item_type == "text" and "content" in item:
            return item["content"]

        # 格式2: { "type": "message", "content": [...] }
        if item_type == "message" and "content" in item:
            return ResponseParser._extract_text_from_content(item["content"])

        # 格式3: 尝试其他可能的文本字段
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
        """从 content 字段中提取文本"""
        if isinstance(content, str):
            return content

        if not isinstance(content, list):
            return None

        texts = []
        for content_item in content:
            if isinstance(content_item, str):
                texts.append(content_item)
            elif isinstance(content_item, dict):
                # output_text 类型
                if content_item.get("type") == "output_text" and "text" in content_item:
                    text = content_item["text"]
                    if text:
                        texts.append(text)
                # 其他包含 text 字段的类型
                elif "text" in content_item:
                    text = content_item["text"]
                    if text:
                        texts.append(text)

        return "\n".join(texts) if texts else None

    @staticmethod
    def parse_sse_event(data: dict[str, Any]) -> dict[str, Any]:
        """解析 SSE 事件

        Args:
            data: SSE 事件数据

        Returns:
            解析结果，包含 type, text, is_done, error 等字段
        """
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
        """解析非流式 JSON 响应

        Args:
            result: API 响应 JSON

        Returns:
            提取的文本内容
        """
        # OpenResponses 格式
        if "output" in result and isinstance(result["output"], list):
            text = ResponseParser.extract_text_from_output(result["output"])
            if text:
                return text

        # OpenAI 兼容格式
        if "choices" in result and len(result["choices"]) > 0:
            content = result["choices"][0].get("message", {}).get("content", "")
            if content:
                return content

        # 直接 content 字段
        if "content" in result:
            return result["content"]

        return None
