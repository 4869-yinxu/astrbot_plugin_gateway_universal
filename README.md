# astrbot_plugin_gateway_universal

通用网关桥接插件（推荐入口）。  
一个插件里同时支持 `hermes` / `openclaw` 两种连接行为，通过配置切换，不需要再分别启用 `hermes_bridge` 和 `clawdbot_bridge`。

## 目录说明

- `main.py`: 插件主入口（`gateway_universal`）
- `_bridge_runtime/`: 内置桥接运行时
- `_gateway_lib/`: 公共能力（L1 合并、`/v1/responses` 客户端、解析器）
- `_conf_schema.json`: 配置字段定义

## 最小配置（Hermes）

配置文件路径：

- `AstrBot/data/config/astrbot_plugin_gateway_universal_config.json`

示例：

```json
{
  "gateway_backend": "hermes",
  "hermes_gateway_url": "http://host.docker.internal:8642",
  "hermes_agent_id": "clawdbotbot",
  "hermes_gateway_auth_token": "YOUR_API_SERVER_KEY",
  "admin_qq_id": "2337302325",
  "admin_qq_ids": ["2337302325"]
}
```

说明：

- `hermes_gateway_auth_token` 是 **Hermes 网关访问密钥**（通常对应 Hermes 的 `API_SERVER_KEY`）。
- 不是上游阿里云模型 `sk-...`。

## 切换后端

- `gateway_backend: "hermes"`：Hermes 行为
- `gateway_backend: "openclaw"`：OpenClaw 行为

## 常用命令

- 进入网关模式：默认 `"/hermes"`, `"/管理"`, `"/clawdbot"`
- 退出网关模式：默认 `"/exit"`, `"/退出"`, `"/返回"`

可在配置里通过 `switch_commands` / `exit_commands` 覆盖。

## L1 统一配置（可选）

如果你使用 `data/config/gateway_bridges.json`，可在本插件配置中指定：

- `unified_gateway_config_path`
- `gateway_profile_id`（或 `active_gateway_profile`）

优先级：

1. L2: `gateway_profile_id` / `active_gateway_profile`
2. L1: `active_profile_by_plugin["gateway_universal"]`
3. L1: `default_profile`

## 常见问题

### 1) 401 invalid_api_key

- AstrBot 传给 Hermes 的网关密钥错误（`hermes_gateway_auth_token` 不匹配）

### 2) 403 AllocationQuota.FreeTierOnly

- 上游模型账号免费额度耗尽或处于“仅免费模式”
- 需在模型平台开启付费/按量

### 3) 同时启用多个桥接插件

- 建议只启用 `gateway_universal`
- 与 `hermes_bridge` / `clawdbot_bridge` 同时启用可能产生重复处理或冲突

