#!/usr/bin/env python3
"""手动/CI 轻量自测：不依赖 AstrBot。用法::

    python smoke_unified_config.py
    （在 ``_gateway_lib`` 目录下执行，或任意 cwd：脚本会把本目录加入 sys.path）
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from unified_config import merge_gateway_l1_into_l2


def _write(p: Path, obj: object) -> None:
    p.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        l1 = root / "gateway_bridges.json"
        _write(
            l1,
            {
                "version": 1,
                "active_profile_by_plugin": {
                    "hermes_bridge": "ph",
                    "clawdbot_bridge": "po",
                    "gateway_universal": "ph",
                },
                "profiles": {
                    "ph": {
                        "kind": "hermes",
                        "gateway_url": "http://hermes.test:1",
                        "agent_id": "agent-h",
                        "gateway_auth_token": "tok-h",
                        "gateway_model_template": "hermes:{agent_id}",
                        "gateway_send_openclaw_headers": False,
                        "timeout": 99,
                    },
                    "po": {
                        "kind": "openclaw",
                        "gateway_url": "http://openclaw.test:2",
                        "agent_id": "agent-o",
                        "gateway_auth_token": "tok-o",
                        "gateway_model_template": "openclaw:{agent_id}",
                        "gateway_send_openclaw_headers": True,
                        "timeout": 88,
                    },
                    "px": {
                        "kind": "hermes",
                        "gateway_url": "http://override.test:9",
                        "agent_id": "agent-x",
                        "gateway_auth_token": "tok-x",
                        "gateway_model_template": "hermes:{agent_id}",
                        "gateway_send_openclaw_headers": False,
                        "timeout": 77,
                    },
                },
            },
        )

        l2_h = {"admin_qq_id": "1", "clawdbot_gateway_url": "http://old"}
        out_h = merge_gateway_l1_into_l2(
            l2_h,
            unified_file=l1,
            registry_plugin_id="hermes_bridge",
            mapping_plugin_id="hermes_bridge",
        )
        assert out_h["clawdbot_gateway_url"] == "http://hermes.test:1"
        assert out_h["hermes_gateway_url"] == "http://hermes.test:1"
        assert out_h["admin_qq_id"] == "1"
        assert out_h["hermes_gateway_auth_token"] == "tok-h"
        assert out_h["timeout"] == 99

        l2_override = {
            "gateway_profile_id": "px",
            "clawdbot_gateway_url": "http://ignored",
        }
        out_ov = merge_gateway_l1_into_l2(
            l2_override,
            unified_file=l1,
            registry_plugin_id="hermes_bridge",
            mapping_plugin_id="hermes_bridge",
        )
        assert out_ov["clawdbot_gateway_url"] == "http://override.test:9"
        assert out_ov["hermes_gateway_auth_token"] == "tok-x"

        l2_o = {"study_groups": [], "clawdbot_gateway_url": "http://old2"}
        out_o = merge_gateway_l1_into_l2(
            l2_o,
            unified_file=l1,
            registry_plugin_id="clawdbot_bridge",
            mapping_plugin_id="clawdbot_bridge",
        )
        assert out_o["clawdbot_gateway_url"] == "http://openclaw.test:2"
        assert out_o["gateway_auth_token"] == "tok-o"
        assert out_o["timeout"] == 88

        l1_default = root / "only_default.json"
        _write(
            l1_default,
            {
                "version": 1,
                "default_profile": "ph",
                "profiles": {
                    "ph": {
                        "kind": "hermes",
                        "gateway_url": "http://default.only:3",
                        "agent_id": "a",
                        "gateway_auth_token": "",
                        "gateway_model_template": "hermes:{agent_id}",
                        "gateway_send_openclaw_headers": False,
                        "timeout": 10,
                    },
                },
            },
        )
        out_d = merge_gateway_l1_into_l2(
            {},
            unified_file=l1_default,
            registry_plugin_id="hermes_bridge",
            mapping_plugin_id="hermes_bridge",
        )
        assert out_d["clawdbot_gateway_url"] == "http://default.only:3"

        missing = root / "none.json"
        out_m = merge_gateway_l1_into_l2(
            l2_h,
            unified_file=missing,
            registry_plugin_id="hermes_bridge",
            mapping_plugin_id="hermes_bridge",
        )
        assert out_m == l2_h

        bad = root / "bad.json"
        bad.write_text("{", encoding="utf-8")
        out_b = merge_gateway_l1_into_l2(
            l2_h,
            unified_file=bad,
            registry_plugin_id="hermes_bridge",
            mapping_plugin_id="hermes_bridge",
        )
        assert out_b["clawdbot_gateway_url"] == l2_h["clawdbot_gateway_url"]

        out_gu = merge_gateway_l1_into_l2(
            {"clawdbot_gateway_url": "http://x"},
            unified_file=l1,
            registry_plugin_id="gateway_universal",
            mapping_plugin_id="hermes_bridge",
        )
        assert out_gu["clawdbot_gateway_url"] == "http://hermes.test:1"

    print("smoke_unified_config: OK")


if __name__ == "__main__":
    main()
