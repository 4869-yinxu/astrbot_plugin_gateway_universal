# AstrBot OpenClaw Bridge 插件

AstrBot 与 OpenClaw 的桥接插件，允许管理员通过 QQ 消息直接与 OpenClaw AI Agent 交互，执行系统管理、文档生成等任务。

## 功能特性

- 🔐 **管理员专属**：仅管理员可使用，确保安全
- 🔄 **模式切换**：通过指令在 AstrBot 和 OpenClaw 模式间切换
- 💬 **会话隔离**：每个用户在每个群组/私聊都有独立会话
- 🛠️ **工具执行**：支持 OpenClaw 的工具调用（如执行系统命令）
- 📡 **流式响应**：使用 SSE 流式传输，确保获取完整的工具执行结果
- 📊 **状态可视化**：支持命令查看当前模式、会话与关键配置
- 🧪 **初始化自检**：一键检查配置完整性与 Gateway 连通性

## 安装

将插件目录复制到 AstrBot 的 `data/plugins/` 目录下，重启 AstrBot 即可。

```bash
# 如果使用 Docker
docker restart astrbot
```

## 配置

在 AstrBot 管理面板中配置插件，或直接编辑配置文件。

### 配置项说明

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `clawdbot_gateway_url` | string | `http://host.docker.internal:18789` | OpenClaw Gateway 地址 |
| `clawdbot_agent_id` | string | `clawdbotbot` | OpenClaw Agent ID |
| `gateway_auth_token` | string | `""` | Gateway 认证 Token（如果启用了认证） |
| `switch_commands` | list | `["/clawd", "/管理", "/clawdbot"]` | 切换到 OpenClaw 模式的命令 |
| `exit_commands` | list | `["/exit", "/退出", "/返回"]` | 退出 OpenClaw 模式的命令 |
| `timeout` | int | `60` | API 请求超时时间（秒），建议设为 300 |
| `default_session` | string | `main` | 默认会话名称 |
| `share_with_webui` | bool | `false` | 是否与 OpenClaw WebUI 共享会话 |

### 配置示例

```json
{
  "clawdbot_gateway_url": "http://host.docker.internal:18789",
  "clawdbot_agent_id": "clawdbotbot",
  "gateway_auth_token": "your-token-here",
  "switch_commands": ["/clawd", "/管理", "/clawdbot"],
  "exit_commands": ["/exit", "/退出", "/返回"],
  "timeout": 300,
  "default_session": "main",
  "share_with_webui": true
}
```

### 注意事项

- **Docker 环境**：如果 AstrBot 运行在 Docker 中，Gateway URL 应使用 `host.docker.internal` 而非 `localhost`
- **超时设置**：如果 Agent 需要执行耗时操作（如系统命令），建议将 `timeout` 设为 300 秒
- **认证 Token**：需要与 OpenClaw Gateway 配置的 `gateway.auth.token` 一致
- **会话共享**：
  - 启用 `share_with_webui: true` 后，QQ 和 WebUI 将共享同一个会话
  - 所有管理员在 QQ 中会共享同一个对话历史
  - 适合单人使用或团队协作场景
  - 如果需要每个用户独立的会话，保持 `share_with_webui: false`

## 使用方法

### 切换到 OpenClaw 模式

```
/clawd 帮我检查系统状态
```

或先切换模式，再发送消息：

```
/clawd
```

之后发送的所有消息都会转发给 OpenClaw，直到退出。

### 会话管理

OpenClaw 支持多个独立的对话会话，每个会话有独立的上下文：

**切换到指定会话：**
```
/clawd session work
```

**查看当前会话：**
```
/clawd session
```

**使用场景示例：**
- `work` 会话：处理工作相关任务
- `home` 会话：处理个人事务
- `dev` 会话：开发调试专用

每个会话的对话历史相互独立，互不干扰。

### 状态与配置查看

**查看运行状态：**
```
/clawd status
```

**查看生效配置（敏感字段脱敏）：**
```
/clawd config
```

**执行初始化检查（配置 + 网关连通性）：**
```
/clawd init
```

### 退出 OpenClaw 模式

```
/退出
```

或

```
/返回
```

## 前置要求

1. **OpenClaw Gateway** 已运行并监听指定端口
2. **AstrBot** 已配置管理员 ID（在 `cmd_config.json` 的 `admins_id` 中）
3. 如果 Gateway 启用了认证，需要配置正确的 Token

## 常见问题

### 响应不完整

如果只收到初始回复而没有工具执行结果：
- 检查 `timeout` 配置是否足够长（建议 300 秒）
- 确认 OpenClaw Gateway 版本支持流式响应

### 认证失败

如果日志显示 `401 Unauthorized`：
- 检查 `gateway_auth_token` 是否正确
- 确认 Gateway 的认证配置

### 连接失败

如果无法连接到 Gateway：
- 检查 Gateway 是否正在运行
- 检查 URL 配置（Docker 环境使用 `host.docker.internal`）

## 许可证

MIT License
