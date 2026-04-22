"""
OpenClaw Gateway HTTP 客户端

负责与 OpenClaw Gateway 的 HTTP 通信
"""

import asyncio
import json
import time
from typing import Any

import aiohttp

from astrbot.api import logger

from .response_parser import ResponseParser


class OpenClawClient:
    """OpenClaw Gateway HTTP 客户端"""

    def __init__(
        self,
        gateway_url: str,
        agent_id: str,
        auth_token: str = "",
        timeout: int = 300,
    ):
        """初始化客户端

        Args:
            gateway_url: Gateway URL（不含尾部斜杠）
            agent_id: Agent ID
            auth_token: 认证 Token（可选）
            timeout: 请求超时时间（秒）
        """
        self.gateway_url = gateway_url.rstrip("/")
        self.agent_id = agent_id
        self.auth_token = auth_token
        self.timeout = timeout
        self.parser = ResponseParser()

    def _build_headers(self, session_key: str) -> dict[str, str]:
        """构建请求头"""
        headers = {
            "Content-Type": "application/json",
            "x-openclaw-agent-id": self.agent_id,
            "x-openclaw-session-key": session_key,
        }
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers

    def _build_payload(
        self, message: str, session_key: str, stream: bool = True
    ) -> dict[str, Any]:
        """构建请求体"""
        return {
            "model": f"openclaw:{self.agent_id}",
            "input": message,
            "user": session_key,
            "stream": stream,
        }

    async def send_message(self, message: str, session_key: str) -> str | None:
        """发送消息到 OpenClaw Gateway

        使用流式响应以获取完整的工具执行结果

        Args:
            message: 用户消息
            session_key: 会话标识符

        Returns:
            OpenClaw 返回的文本内容，失败时返回错误提示
        """
        # 验证消息不为空
        if not message or not message.strip():
            logger.warning("[OpenClawClient] 消息为空，拒绝发送")
            return "❌ 消息不能为空"

        url = f"{self.gateway_url}/v1/responses"
        headers = self._build_headers(session_key)
        payload = self._build_payload(message, session_key, stream=True)

        logger.info(f"[OpenClawClient] 📤 发送请求: {url}")
        logger.debug(
            f"[OpenClawClient] 请求体: {json.dumps(payload, ensure_ascii=False)}"
        )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as response:
                    return await self._handle_response(response)

        except asyncio.TimeoutError:
            logger.error(f"[OpenClawClient] 请求超时 ({self.timeout}s)")
            return f"⏱️ 请求超时（{self.timeout}秒），请稍后重试"
        except aiohttp.ClientError as e:
            logger.error(f"[OpenClawClient] 连接错误: {e}")
            return f"❌ 无法连接到 Gateway ({self.gateway_url})"
        except Exception as e:
            logger.error(f"[OpenClawClient] 未知错误: {e}", exc_info=True)
            return f"❌ 发生错误: {str(e)}"

    async def probe_gateway(self, timeout: int = 5) -> dict[str, Any]:
        """探测 Gateway 连通性

        Returns:
            包含连通性、状态码、延迟、错误信息的字典
        """
        probe_url = self.gateway_url
        start_time = time.perf_counter()
        result: dict[str, Any] = {
            "ok": False,
            "url": probe_url,
            "status": None,
            "latency_ms": None,
            "error": "",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    probe_url,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    allow_redirects=True,
                ) as response:
                    latency_ms = int((time.perf_counter() - start_time) * 1000)
                    result["status"] = response.status
                    result["latency_ms"] = latency_ms
                    result["ok"] = True
                    return result
        except asyncio.TimeoutError:
            result["error"] = f"请求超时（{timeout}秒）"
            return result
        except aiohttp.ClientError as e:
            result["error"] = f"连接失败: {str(e)}"
            return result
        except Exception as e:
            result["error"] = f"未知错误: {str(e)}"
            return result

    async def _handle_response(self, response: aiohttp.ClientResponse) -> str | None:
        """处理 HTTP 响应"""
        logger.info(f"[OpenClawClient] 📥 响应状态: {response.status}")
        content_type = response.headers.get("Content-Type", "")

        if response.status == 200:
            if content_type.startswith("text/event-stream"):
                return await self._handle_sse_response(response)
            else:
                return await self._handle_json_response(response)
        elif response.status == 401:
            logger.error("[OpenClawClient] 认证失败")
            return "❌ Gateway 认证失败，请检查配置"
        elif response.status == 404:
            logger.error(f"[OpenClawClient] Agent {self.agent_id} 不存在")
            return f"❌ Agent {self.agent_id} 不存在或未启用"
        else:
            error_text = await response.text()
            logger.error(f"[OpenClawClient] API 错误: {response.status} - {error_text}")
            return f"❌ Gateway 错误 ({response.status}): {error_text[:200]}"

    async def _handle_sse_response(
        self, response: aiohttp.ClientResponse
    ) -> str | None:
        """处理 SSE 流式响应"""
        logger.info("[OpenClawClient] 🔄 处理 SSE 流式响应")

        accumulated_text = ""
        final_response_text = ""
        buffer = ""
        event_count = 0
        done_received = False

        async for chunk in response.content.iter_any():
            if not chunk:
                continue

            chunk_str = chunk.decode("utf-8", errors="ignore")
            buffer += chunk_str

            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()

                if not line or line.startswith("event:"):
                    continue

                if line == "data: [DONE]":
                    logger.info("[OpenClawClient] 收到 SSE 结束标记")
                    done_received = True
                    break

                if line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        event_count += 1

                        result = self.parser.parse_sse_event(data)
                        logger.debug(
                            f"[OpenClawClient] SSE 事件 #{event_count}: {result['type']}"
                        )

                        if result["is_error"]:
                            return f"❌ OpenClaw 错误: {result['error_message']}"

                        if result["text"]:
                            if result["type"] == "response.output_text.delta":
                                accumulated_text += result["text"]
                            elif result["type"] == "response.completed":
                                final_response_text = result["text"]
                            elif result["type"] == "response.output_text.done":
                                if len(result["text"]) >= len(accumulated_text):
                                    accumulated_text = result["text"]

                    except json.JSONDecodeError as e:
                        logger.warning(f"[OpenClawClient] 解析 SSE 失败: {e}")
                        continue
            if done_received:
                break

        logger.info(
            f"[OpenClawClient] SSE 完成: 事件数={event_count}, 累计={len(accumulated_text)}, 最终={len(final_response_text)}"
        )

        # 优先使用 response.completed 中的最终文本
        result_text = final_response_text if final_response_text else accumulated_text

        if result_text:
            logger.info(f"[OpenClawClient] ✅ 成功获取响应 (长度: {len(result_text)})")
            return result_text
        else:
            logger.warning("[OpenClawClient] ⚠️ 未收集到文本内容")
            return "✅ 命令已执行完成（无文本输出）"

    async def _handle_json_response(
        self, response: aiohttp.ClientResponse
    ) -> str | None:
        """处理非流式 JSON 响应"""
        logger.info("[OpenClawClient] 📋 处理 JSON 响应")

        result = await response.json()
        logger.debug(
            f"[OpenClawClient] 响应: {json.dumps(result, ensure_ascii=False)[:500]}"
        )

        text = self.parser.parse_json_response(result)

        if text:
            logger.info(f"[OpenClawClient] ✅ 成功获取响应 (长度: {len(text)})")
            return text

        # 如果响应状态是 completed，即使没有文本也返回提示
        if result.get("status") == "completed":
            return "✅ 命令已执行完成"

        logger.warning(
            f"[OpenClawClient] ⚠️ 未知响应格式: {json.dumps(result, ensure_ascii=False)[:200]}"
        )
        return None
