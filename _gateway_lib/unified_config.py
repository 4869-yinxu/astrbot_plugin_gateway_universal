"""
L1 统一网关连接文件（gateway_bridges.json）解析与合并到 L2 插件配置 dict。

不依赖 AstrBot；调用方传入绝对路径。缺文件、缺绑定、坏 JSON 时返回 L2 副本且不抛异常。
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)

SUPPORTED_VERSIONS = {1}

# AstrBot Star 注册名（与 @register 首参一致）→ L1 profile 中通用字段 → L2 键
_L1_FIELD_ALIASES: dict[str, dict[str, list[str]]] = {
    "hermes_bridge": {
        "gateway_url": ["hermes_gateway_url", "clawdbot_gateway_url"],
        "agent_id": ["hermes_agent_id", "clawdbot_agent_id"],
        "backup_agent_id": ["hermes_backup_agent_id", "clawdbot_backup_agent_id"],
        "gateway_auth_token": ["hermes_gateway_auth_token", "gateway_auth_token"],
        "gateway_model_template": ["gateway_model_template"],
        "gateway_send_openclaw_headers": [
            "gateway_send_openclaw_headers",
            "gateway_send_hermes_headers",
        ],
        "timeout": ["timeout"],
    },
    "clawdbot_bridge": {
        "gateway_url": ["clawdbot_gateway_url"],
        "agent_id": ["clawdbot_agent_id"],
        "backup_agent_id": ["clawdbot_backup_agent_id"],
        "gateway_auth_token": ["gateway_auth_token"],
        "gateway_model_template": ["gateway_model_template"],
        "gateway_send_openclaw_headers": ["gateway_send_openclaw_headers"],
        "timeout": ["timeout"],
    },
}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        _LOG.debug("[gateway_l1] cannot read %s: %s", path, e)
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        _LOG.error("[gateway_l1] invalid JSON in %s: %s", path, e)
        return None
    if not isinstance(data, dict):
        _LOG.error("[gateway_l1] root must be object: %s", path)
        return None
    return data


def _resolve_profile_id(
    data: dict[str, Any],
    registry_plugin_id: str,
    l2: dict[str, Any],
    *,
    profiles: dict[str, Any],
) -> tuple[str, str] | None:
    """选用哪个 profile 完全由用户在 L1/L2 中书写决定，优先级如下。

    1. L2 ``gateway_profile_id`` 或 ``active_gateway_profile``（插件 JSON，便于按实例指定）
    2. L1 ``active_profile_by_plugin[plugin_id]``
    3. L1 ``default_profile``

    若某步给出的 id 在 ``profiles`` 中不存在，则打 warning 并尝试下一步。

    Returns:
        ``(profile_id, source_label)`` 或 ``None``。
    """

    def _exists(pid: str) -> bool:
        return bool(pid) and isinstance(profiles.get(pid), dict)

    candidates: list[tuple[str, str]] = []
    for l2_key in ("gateway_profile_id", "active_gateway_profile"):
        raw = l2.get(l2_key)
        if isinstance(raw, str) and raw.strip():
            candidates.append((f"L2.{l2_key}", raw.strip()))
    by_plugin = data.get("active_profile_by_plugin")
    if isinstance(by_plugin, dict):
        pid = by_plugin.get(registry_plugin_id)
        if isinstance(pid, str) and pid.strip():
            candidates.append(("L1.active_profile_by_plugin", pid.strip()))
    fallback = data.get("default_profile")
    if isinstance(fallback, str) and fallback.strip():
        candidates.append(("L1.default_profile", fallback.strip()))

    for source, pid in candidates:
        if _exists(pid):
            return (pid, source)
        _LOG.warning(
            "[gateway_l1] profile id %r from %s not in profiles, try next rule",
            pid,
            source,
        )
    return None


def _profile_to_l2_overlay(plugin_id: str, profile: dict[str, Any]) -> dict[str, Any]:
    mapping = _L1_FIELD_ALIASES.get(plugin_id)
    if not mapping:
        _LOG.warning("[gateway_l1] unknown plugin_id %r, skip overlay", plugin_id)
        return {}

    overlay: dict[str, Any] = {}
    for l1_key, l2_keys in mapping.items():
        if l1_key not in profile:
            continue
        val = profile[l1_key]
        if val is None:
            continue
        if l1_key == "gateway_auth_token" and isinstance(val, str) and not val.strip():
            continue
        for lk in l2_keys:
            overlay[lk] = val
    return overlay


def merge_gateway_l1_into_l2(
    l2: dict[str, Any],
    *,
    unified_file: Path,
    registry_plugin_id: str,
    mapping_plugin_id: str,
) -> dict[str, Any]:
    """将 L1 中解析到的 profile 连接字段合并进 L2 副本（覆盖同名连接键）。

    选用哪个 profile：见 ``_resolve_profile_id``（L2 可写 ``gateway_profile_id`` 覆盖 L1 表）。

    registry_plugin_id:
        在 L1 ``active_profile_by_plugin`` 中查找绑定所用的键（如 ``hermes_bridge``、
        ``gateway_universal``）。
    mapping_plugin_id:
        将 profile 字段映射到 L2 连接键时使用的内置表（``hermes_bridge`` 或 ``clawdbot_bridge``）。
    unified_file: L1 JSON 绝对路径；不存在则返回 ``l2`` 的深拷贝。

    若 ``l2`` 已含 ``_gateway_l1_merge_applied: true``，则直接返回副本（避免 ClawdbotBridge 二次合并）。
    """
    out = deepcopy(l2)
    if out.get("_gateway_l1_merge_applied"):
        return out
    if not unified_file.is_file():
        _LOG.debug("[gateway_l1] file missing, skip: %s", unified_file)
        return out

    data = _read_json(unified_file)
    if data is None:
        return out

    ver = data.get("version", 1)
    if isinstance(ver, str) and ver.isdigit():
        ver = int(ver)
    if ver not in SUPPORTED_VERSIONS:
        _LOG.error("[gateway_l1] unsupported version %r in %s", ver, unified_file)
        return out

    profiles = data.get("profiles")
    if not isinstance(profiles, dict):
        _LOG.error("[gateway_l1] missing or invalid profiles in %s", unified_file)
        return out

    resolved = _resolve_profile_id(
        data, registry_plugin_id, l2, profiles=profiles
    )
    if not resolved:
        _LOG.info(
            "[gateway_l1] no usable profile for registry_plugin_id=%r (check L2 "
            "gateway_profile_id or L1 active_profile_by_plugin / default_profile): %s",
            registry_plugin_id,
            unified_file,
        )
        return out

    profile_id, pick_source = resolved
    profile = profiles.get(profile_id)
    if not isinstance(profile, dict):
        _LOG.error(
            "[gateway_l1] profile %r not found or not object in %s",
            profile_id,
            unified_file,
        )
        return out

    overlay = _profile_to_l2_overlay(mapping_plugin_id, profile)
    if not overlay:
        return out

    out.update(overlay)
    _LOG.info(
        "[gateway_l1] merged profile %r (%s) registry=%r mapping=%r from %s",
        profile_id,
        pick_source,
        registry_plugin_id,
        mapping_plugin_id,
        unified_file,
    )
    return out
