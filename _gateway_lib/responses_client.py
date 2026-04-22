"""
与 OpenResponses 兼容的 Gateway HTTP 客户端（通用，不限定 OpenClaw / Hermes 品牌）。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import aiohttp

from astrbot.api import logger

from .response_parser import ResponseParser


class ResponsesGatewayClient:
    """对 ``/v1/responses`` 类端点发送 ``model`` + ``input`` + ``user`` 的请求。"""

    def __init__(
        self,
        gateway_url: str,
        agent_id: str,
        auth_token: str = "",
        timeout: int = 300,
        *,
        model_template: str = "openclaw:{agent_id}",
        send_openclaw_headers: bool = True,
        responses_path: str = "/v1/responses",
        log_prefix: str = "[gateway]",
    ) -> None:
        self.gateway_url = gateway_url.rstrip("/")
        self.agent_id = agent_id
        self.auth_token = auth_token
        self.timeout = timeout
        self.model_template = model_template
        self.send_openclaw_headers = send_openclaw_headers
        self.responses_path = responses_path if responses_path.startswith("/") else f"/{responses_path}"
        self.log_prefix = log_prefix
        self.parser = ResponseParser()

    def _model_id(self) -> str:
        return (
            self.model_template.replace("{agent_id}", self.agent_id)
            if "{agent_id}" in self.model_template
            else self.model_template
        )

    def _build_headers(self, session_key: str) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.send_openclaw_headers:
            headers["x-openclaw-agent-id"] = self.agent_id
            headers["x-openclaw-session-key"] = session_key
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers

    def _build_payload(
        self, message: str, session_key: str, stream: bool = True
    ) -> dict[str, Any]:
        return {
            "model": self._model_id(),
            "input": message,
            "user": session_key,
            "stream": stream,
        }

    async def send_message(self, message: str, session_key: str) -> str | None:
        if not message or not message.strip():
            logger.warning("%s 消息为空，拒绝发送", self.log_prefix)
            return "❌ 消息不能为空"

        url = f"{self.gateway_url}{self.responses_path}"
        headers = self._build_headers(session_key)
        payload = self._build_payload(message, session_key, stream=True)

        logger.info("%s 📤 POST %s", self.log_prefix, url)
        logger.debug(
            "%s 请求体: %s",
            self.log_prefix,
            json.dumps(payload, ensure_ascii=False),
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
            logger.error("%s 请求超时 (%ss)", self.log_prefix, self.timeout)
            return f"⏱️ 请求超时（{self.timeout}秒），请稍后重试"
        except aiohttp.ClientError as e:
            logger.error("%s 连接错误: %s", self.log_prefix, e)
            return f"❌ 无法连接到 Gateway ({self.gateway_url})"
        except Exception as e:
            logger.error("%s 未知错误: %s", self.log_prefix, e, exc_info=True)
            return f"❌ 发生错误: {str(e)}"

    async def probe_gateway(self, timeout: int = 5) -> dict[str, Any]:
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
        logger.info("%s 📥 响应状态: %s", self.log_prefix, response.status)
        content_type = response.headers.get("Content-Type", "")

        if response.status == 200:
            if content_type.startswith("text/event-stream"):
                return await self._handle_sse_response(response)
            return await self._handle_json_response(response)
        if response.status == 401:
            logger.error("%s 认证失败", self.log_prefix)
            return "❌ Gateway 认证失败，请检查配置"
        if response.status == 404:
            logger.error("%s Agent %s 不存在", self.log_prefix, self.agent_id)
            return f"❌ Agent {self.agent_id} 不存在或未启用"
        error_text = await response.text()
        logger.error(
            "%s API 错误: %s - %s",
            self.log_prefix,
            response.status,
            error_text,
        )
        return f"❌ Gateway 错误 ({response.status}): {error_text[:200]}"

    async def _handle_sse_response(
        self, response: aiohttp.ClientResponse
    ) -> str | None:
        logger.info("%s 🔄 处理 SSE 流式响应", self.log_prefix)

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
                    logger.info("%s 收到 SSE 结束标记", self.log_prefix)
                    done_received = True
                    break

                if line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        event_count += 1

                        result = self.parser.parse_sse_event(data)
                        logger.debug(
                            "%s SSE 事件 #%s: %s",
                            self.log_prefix,
                            event_count,
                            result["type"],
                        )

                        if result["is_error"]:
                            return f"❌ Gateway 错误: {result['error_message']}"

                        if result["text"]:
                            if result["type"] == "response.output_text.delta":
                                accumulated_text += result["text"]
                            elif result["type"] == "response.completed":
                                final_response_text = result["text"] or ""
                            elif result["type"] == "response.output_text.done":
                                if len(result["text"] or "") >= len(accumulated_text):
                                    accumulated_text = result["text"] or ""

                    except json.JSONDecodeError as e:
                        logger.warning("%s 解析 SSE 失败: %s", self.log_prefix, e)
                        continue
            if done_received:
                break

        logger.info(
            "%s SSE 完成: 事件数=%s, 累计=%s, 最终=%s",
            self.log_prefix,
            event_count,
            len(accumulated_text),
            len(final_response_text),
        )

        result_text = final_response_text if final_response_text else accumulated_text

        if result_text:
            logger.info("%s ✅ 成功获取响应 (长度: %s)", self.log_prefix, len(result_text))
            return result_text
        logger.warning("%s ⚠️ 未收集到文本内容", self.log_prefix)
        return "✅ 命令已执行完成（无文本输出）"

    async def _handle_json_response(
        self, response: aiohttp.ClientResponse
    ) -> str | None:
        logger.info("%s 📋 处理 JSON 响应", self.log_prefix)

        result = await response.json()
        logger.debug(
            "%s 响应: %s",
            self.log_prefix,
            json.dumps(result, ensure_ascii=False)[:500],
        )

        text = self.parser.parse_json_response(result)

        if text:
            logger.info("%s ✅ 成功获取响应 (长度: %s)", self.log_prefix, len(text))
            return text

        if result.get("status") == "completed":
            return "✅ 命令已执行完成"

        logger.warning(
            "%s ⚠️ 未知响应格式: %s",
            self.log_prefix,
            json.dumps(result, ensure_ascii=False)[:200],
        )
        return None
