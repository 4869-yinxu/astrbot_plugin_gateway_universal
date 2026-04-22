#!/usr/bin/env python3
"""
通用网关桥接插件：通过配置 ``gateway_backend`` 选择 hermes 或 openclaw 行为；
内置 ``_bridge_runtime``（OpenClaw 桥运行时）与 ``_gateway_lib``（L1 合并、``/v1/responses`` 客户端），
不依赖 ``astrbot_plugin_hermes_bridge`` / ``astrbot_plugin_clawdbot_bridge`` 目录。
L1 统一配置见 ``data/config/gateway_bridges.json``，``active_profile_by_plugin`` 建议使用键 ``gateway_universal``。
Hermes / OpenClaw 独立插件若仍启用，其 L1 合并与 HTTP 客户端亦从本目录 ``_gateway_lib`` 引用，请一并部署本插件目录。
"""

from __future__ import annotations

import importlib.util
import inspect
import os
from pathlib import Path
import sys
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

import astrbot.api.star as _astrbot_star
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, register
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.message_type import MessageType
from astrbot.core.star.star_handler import star_handlers_registry
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from data.plugins.astrbot_plugin_gateway_universal._gateway_lib import (
    ResponsesGatewayClient as _ResponsesGatewayClient,
    merge_gateway_l1_into_l2,
)

GATEWAY_UNIVERSAL_ID = "gateway_universal"


def _noop_plugin_register(*_args, **_kwargs):
    def _decorator(cls):
        return cls

    return _decorator


try:
    _bridge_dir = Path(__file__).resolve().parent / "_bridge_runtime"
    _bridge_file = _bridge_dir / "main.py"
    _pkg_name = "_astrbot_gateway_universal_bridge_runtime"
    _spec = importlib.util.spec_from_file_location(
        _pkg_name,
        _bridge_file,
        submodule_search_locations=[str(_bridge_dir)],
    )
    if _spec is None or _spec.loader is None:
        raise RuntimeError(f"Invalid spec for bridge: {_bridge_file}")
    _bridge_mod = importlib.util.module_from_spec(_spec)
    sys.modules[_pkg_name] = _bridge_mod
    _saved_register = _astrbot_star.register
    _astrbot_star.register = _noop_plugin_register
    try:
        _spec.loader.exec_module(_bridge_mod)
    finally:
        _astrbot_star.register = _saved_register
    _BaseBridge = _bridge_mod.ClawdbotBridge
    _Filter = _bridge_mod.filter
    _EventMessageType = _bridge_mod.EventMessageType
    _MAX_PRIORITY = _bridge_mod.sys.maxsize
    logger.info("[gateway_universal] 已加载内置桥接运行时: %s", _bridge_dir)
except Exception as e:  # pragma: no cover
    raise RuntimeError(
        "gateway_universal: failed to load _bridge_runtime (copy from clawdbot bundle)."
    ) from e

def _unwrap(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def _unified_gateway_bridges_path(cfg: dict[str, Any]) -> Path:
    custom = _unwrap(cfg.get("unified_gateway_config_path"))
    if isinstance(custom, str) and custom.strip():
        return Path(custom.strip())
    return Path(get_astrbot_data_path()) / "config" / "gateway_bridges.json"


def _set_cfg(cfg: dict[str, Any], key: str, value: Any) -> None:
    if key in cfg and isinstance(cfg[key], dict) and "value" in cfg[key]:
        cfg[key]["value"] = value
    else:
        cfg[key] = value


def _is_url_reachable(base_url: str, timeout: float = 1.5) -> bool:
    checks = ["/health", "/"]
    normalized = base_url.rstrip("/")
    for path in checks:
        try:
            req = Request(f"{normalized}{path}", method="GET")
            with urlopen(req, timeout=timeout) as resp:  # nosec: B310
                if 200 <= int(getattr(resp, "status", 0)) < 500:
                    return True
        except (URLError, TimeoutError, ValueError):
            continue
    return False


def _with_port(url: str, port: int) -> str:
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return url
    netloc = f"{host}:{port}"
    if parsed.username:
        auth = parsed.username
        if parsed.password:
            auth = f"{auth}:{parsed.password}"
        netloc = f"{auth}@{netloc}"
    return urlunparse(
        (
            parsed.scheme or "http",
            netloc,
            parsed.path or "",
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def _resolve_gateway_url(preferred_url: str) -> str:
    if _is_url_reachable(preferred_url):
        return preferred_url
    parsed = urlparse(preferred_url)
    current_port = parsed.port
    candidates: list[str] = []
    for port in (8642, 18789):
        if port != current_port:
            candidates.append(_with_port(preferred_url, port))
    for candidate in candidates:
        if _is_url_reachable(candidate):
            return candidate
    return preferred_url


def _disable_conflicting_gateway_handlers(this_module: str) -> None:
    """关闭 hermes_bridge、clawdbot_bridge 及重复 runtime 的 handler，仅保留本插件。"""
    for handler in list(star_handlers_registry):
        if handler.handler_name not in {"handle_message", "on_study_group_message"}:
            continue
        if handler.handler_module_path == this_module:
            continue
        mod_path = getattr(handler, "handler_module_path", "") or ""
        qualname = getattr(handler.handler, "__qualname__", "")
        mp = mod_path.replace("\\", "/")
        if "_astrbot_plugin_clawdbot_bridge_runtime" in mod_path:
            handler.enabled = False
            continue
        if "_astrbot_gateway_universal_bridge_runtime" in mod_path:
            handler.enabled = False
            continue
        if qualname.startswith("ClawdbotBridge."):
            handler.enabled = False
            continue
        if "astrbot_plugin_hermes_bridge" in mp:
            handler.enabled = False
            continue
        if "astrbot_plugin_clawdbot_bridge" in mp:
            handler.enabled = False
            continue
        if "astrbot_plugin_gateway_universal" in mp and this_module not in mp:
            handler.enabled = False


@register(
    GATEWAY_UNIVERSAL_ID,
    "a4869",
    "通用网关桥（hermes / openclaw），内置运行时，单配置文件可选 L1",
    "1.0.0",
)
class GatewayUniversalBridge(_BaseBridge):
    """gateway_backend=hermes 时对齐 hermes_bridge；openclaw 时对齐 clawdbot_bridge。"""

    def __init__(self, context: Context, config: dict | None = None):
        cfg: dict[str, Any] = {str(k): _unwrap(v) for k, v in dict(config or {}).items()}
        raw_backend = str(_unwrap(cfg.get("gateway_backend")) or "hermes").strip().lower()
        if raw_backend not in ("hermes", "openclaw"):
            raw_backend = "hermes"
        self._gateway_backend = raw_backend
        mapping = "hermes_bridge" if raw_backend == "hermes" else "clawdbot_bridge"

        if not cfg.get("_gateway_l1_merge_applied"):
            cfg = merge_gateway_l1_into_l2(
                cfg,
                unified_file=_unified_gateway_bridges_path(cfg),
                registry_plugin_id=GATEWAY_UNIVERSAL_ID,
                mapping_plugin_id=mapping,
            )
            cfg["_gateway_l1_merge_applied"] = True

        if raw_backend == "hermes":
            hermes_gateway_url = (
                _unwrap(cfg.get("hermes_gateway_url"))
                or _unwrap(cfg.get("clawdbot_gateway_url"))
                or "http://host.docker.internal:18789"
            )
            hermes_agent_id = _unwrap(cfg.get("hermes_agent_id"))
            hermes_backup_agent_id = _unwrap(cfg.get("hermes_backup_agent_id"))
            hermes_gateway_auth_token = _unwrap(cfg.get("hermes_gateway_auth_token"))
            if isinstance(hermes_gateway_auth_token, str):
                hermes_gateway_auth_token = hermes_gateway_auth_token.strip()
            else:
                hermes_gateway_auth_token = hermes_gateway_auth_token or ""
            if not hermes_gateway_auth_token:
                hermes_gateway_auth_token = (
                    os.environ.get("HERMES_GATEWAY_AUTH_TOKEN", "").strip()
                    or os.environ.get("API_SERVER_KEY", "").strip()
                )
            gateway_send_hermes_headers = _unwrap(cfg.get("gateway_send_hermes_headers"))
            resolved_url = _resolve_gateway_url(str(hermes_gateway_url))
            _set_cfg(cfg, "clawdbot_gateway_url", resolved_url)
            _set_cfg(cfg, "hermes_gateway_url", resolved_url)
            if hermes_agent_id:
                _set_cfg(cfg, "clawdbot_agent_id", hermes_agent_id)
            if hermes_backup_agent_id:
                _set_cfg(cfg, "clawdbot_backup_agent_id", hermes_backup_agent_id)
            if hermes_gateway_auth_token:
                _set_cfg(cfg, "gateway_auth_token", str(hermes_gateway_auth_token).strip())
            if gateway_send_hermes_headers is not None:
                _set_cfg(
                    cfg,
                    "gateway_send_openclaw_headers",
                    bool(gateway_send_hermes_headers),
                )
            if not _unwrap(cfg.get("gateway_model_template")):
                _set_cfg(cfg, "gateway_model_template", "hermes:{agent_id}")
        else:
            if not _unwrap(cfg.get("gateway_model_template")):
                _set_cfg(cfg, "gateway_model_template", "openclaw:{agent_id}")
            tok = _unwrap(cfg.get("gateway_auth_token"))
            if not (isinstance(tok, str) and tok.strip()):
                env_t = (
                    os.environ.get("HERMES_GATEWAY_AUTH_TOKEN", "").strip()
                    or os.environ.get("API_SERVER_KEY", "").strip()
                )
                if env_t:
                    _set_cfg(cfg, "gateway_auth_token", env_t)

        super().__init__(context, cfg)

        if raw_backend == "hermes":
            _tok = str(
                _unwrap(cfg.get("hermes_gateway_auth_token"))
                or _unwrap(cfg.get("gateway_auth_token"))
                or ""
            ).strip()
            if not _tok:
                _tok = (
                    os.environ.get("HERMES_GATEWAY_AUTH_TOKEN", "").strip()
                    or os.environ.get("API_SERVER_KEY", "").strip()
                )
            if _tok:
                self.gateway_auth_token = _tok
                _mt = self._get_config("gateway_model_template", "hermes:{agent_id}")
                _send_h = bool(self._get_config("gateway_send_openclaw_headers", True))
                if _ResponsesGatewayClient is not None:
                    self.client = _ResponsesGatewayClient(
                        gateway_url=self.gateway_url,
                        agent_id=self.agent_id,
                        auth_token=_tok,
                        timeout=int(self.timeout),
                        model_template=str(_mt or "hermes:{agent_id}"),
                        send_openclaw_headers=_send_h,
                        log_prefix="[gateway_universal]",
                    )
                else:
                    self.client = _bridge_mod.OpenClawClient(
                        gateway_url=self.gateway_url,
                        agent_id=self.agent_id,
                        auth_token=_tok,
                        timeout=int(self.timeout),
                    )

            admin_id_cfg = _unwrap(cfg.get("admin_qq_id"))
            admin_ids_cfg = _unwrap(cfg.get("admin_qq_ids"))
            if isinstance(admin_ids_cfg, str):
                try:
                    import json as _json

                    admin_ids_cfg = _json.loads(admin_ids_cfg)
                except Exception:
                    admin_ids_cfg = []
            if not isinstance(admin_ids_cfg, list):
                admin_ids_cfg = []
            if admin_id_cfg and str(admin_id_cfg) not in [str(x) for x in admin_ids_cfg]:
                admin_ids_cfg.append(str(admin_id_cfg))
            self._forced_admin_ids = [str(x) for x in admin_ids_cfg if str(x).strip()]
            if self._forced_admin_ids:
                self.admin_qq_ids = list(self._forced_admin_ids)
                self.admin_qq_id = self._forced_admin_ids[0]

            sw = self.command_handler.switch_commands
            if not isinstance(sw, list) or not sw:
                sw = ["/gateway", "/hermes", "/管理", "/clawdbot"]
            else:
                sw = list(sw)
                bases = {str(c).lstrip("/").lower() for c in sw}
                if "gateway" not in bases and "hermes" not in bases:
                    sw.insert(0, "/gateway")
            ex = self.command_handler.exit_commands
            if not isinstance(ex, list) or not ex:
                ex = list(
                    getattr(
                        _bridge_mod,
                        "DEFAULT_EXIT_COMMANDS",
                        ["/exit", "/退出", "/返回"],
                    )
                )
            self.command_handler = _bridge_mod.CommandHandler(
                switch_commands=sw,
                exit_commands=ex,
            )

        _disable_conflicting_gateway_handlers(__name__)

    @property
    def _user_brand_display(self) -> str:
        custom = _unwrap(getattr(self, "config", None) or {})
        if isinstance(self.config, dict):
            custom = _unwrap(self.config.get("user_brand_display"))
        else:
            custom = _unwrap(getattr(self.config, "user_brand_display", ""))
        if isinstance(custom, str) and custom.strip():
            return custom.strip()
        return "Hermes" if self._gateway_backend == "hermes" else "OpenClaw"

    _AUTH_401_HINT = (
        "\n\n提示：网关已校验 API 密钥。请在插件配置填写 token（与网关 API_SERVER_KEY 一致），"
        "或设置环境变量 HERMES_GATEWAY_AUTH_TOKEN / API_SERVER_KEY。"
    )

    def _brand_user_facing_text(self, text: str) -> str:
        if self._gateway_backend != "hermes":
            return text
        if not text:
            return text
        out = text.replace("OpenClaw", self._user_brand_display)
        if "invalid_api_key" in out and "hermes_gateway_auth_token" not in out:
            out = out + self._AUTH_401_HINT
        return out

    def _brand_message_result(self, result: Any) -> Any:
        if self._gateway_backend != "hermes":
            return result
        if result is None:
            return result
        chain = getattr(result, "chain", None)
        if not chain:
            return result
        for comp in chain:
            raw = getattr(comp, "text", None)
            if isinstance(raw, str) and raw:
                comp.text = self._brand_user_facing_text(raw)
        return result

    async def _send_response(
        self, event: AstrMessageEvent, response_text: str, is_study_group: bool
    ):
        if self._gateway_backend != "hermes":
            result = _BaseBridge._send_response(self, event, response_text, is_study_group)
            if inspect.isasyncgen(result):
                async for r in result:
                    yield r
            return
        response_text = self._brand_user_facing_text(response_text)
        if is_study_group and self.admin_qq_id:
            logger.info(
                "[gateway_universal] 学习群响应，私信管理员 %s",
                self.admin_qq_id,
            )
            group_id = str(event.group_id) if hasattr(event, "group_id") else "未知"
            sender_id = event.get_sender_id()
            message = event.message_str.strip()
            admin_message = (
                f"[学习群 {self._user_brand_display}]\n群号: {group_id}\n发送者: {sender_id}\n"
                f"原消息: {message[:100]}\n\n{response_text}"
            )
            try:
                session = MessageSession(
                    platform_name=event.get_platform_id(),
                    message_type=MessageType.FRIEND_MESSAGE,
                    session_id=self.admin_qq_id,
                )
                await self.context.send_message(
                    session=session,
                    message_chain=MessageChain([Plain(admin_message)]),
                )
            except Exception as e:
                logger.error("[gateway_universal] 发送私信失败: %s", e)
        else:
            result = event.plain_result(response_text)
            event.set_result(result)
            yield result

    def _is_admin(self, event) -> bool:
        sender_id = str(event.get_sender_id())
        if getattr(self, "_forced_admin_ids", None):
            return sender_id in self._forced_admin_ids
        return super()._is_admin(event)

    if hasattr(_BaseBridge, "_process_openclaw_message"):

        async def _process_openclaw_message(
            self, event, session_id, session_key, message, is_study_group
        ):
            if self._gateway_backend != "hermes":
                async for resp in super()._process_openclaw_message(
                    event, session_id, session_key, message, is_study_group
                ):
                    yield resp
                return
            async for resp in super()._process_openclaw_message(
                event, session_id, session_key, message, is_study_group
            ):
                yield self._brand_message_result(resp)

    @_Filter.event_message_type(_EventMessageType.ALL, priority=_MAX_PRIORITY)
    async def handle_message(self, event, *args, **kwargs):
        result = _BaseBridge.handle_message(self, event, *args, **kwargs)
        if self._gateway_backend != "hermes":
            if inspect.isasyncgen(result):
                async for resp in result:
                    yield resp
                return
            if inspect.isawaitable(result):
                awaited = await result
                if awaited is not None:
                    yield awaited
                return
            return
        if inspect.isasyncgen(result):
            async for resp in result:
                yield self._brand_message_result(resp)
            return
        if inspect.isawaitable(result):
            awaited = await result
            if awaited is not None:
                yield self._brand_message_result(awaited)
            return

    if hasattr(_BaseBridge, "on_study_group_message"):

        @_Filter.event_message_type(
            _EventMessageType.GROUP_MESSAGE, priority=_MAX_PRIORITY - 1
        )
        async def on_study_group_message(self, event, *args, **kwargs):
            result = _BaseBridge.on_study_group_message(self, event, *args, **kwargs)
            if self._gateway_backend != "hermes":
                if inspect.isasyncgen(result):
                    async for resp in result:
                        yield resp
                    return
                if inspect.isawaitable(result):
                    awaited = await result
                    if awaited is not None:
                        yield awaited
                    return
                return
            if inspect.isasyncgen(result):
                async for resp in result:
                    yield self._brand_message_result(resp)
                return
            if inspect.isawaitable(result):
                awaited = await result
                if awaited is not None:
                    yield self._brand_message_result(awaited)
                return
