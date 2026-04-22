"""
命令处理器

负责识别和处理用户命令
"""


class CommandHandler:
    """命令处理器"""

    def __init__(
        self,
        switch_commands: list[str],
        exit_commands: list[str],
    ):
        """初始化命令处理器

        Args:
            switch_commands: 切换到 OpenClaw 模式的命令列表
            exit_commands: 退出 OpenClaw 模式的命令列表
        """
        self.switch_commands = switch_commands
        self.exit_commands = exit_commands

    def is_switch_command(self, message: str) -> bool:
        """检查是否为切换命令"""
        message = message.strip()
        for cmd in self.switch_commands:
            if message.startswith(cmd) or message.startswith(cmd.lstrip("/")):
                return True
        return False

    def is_exit_command(self, message: str) -> bool:
        """检查是否为退出命令"""
        message = message.strip()
        for cmd in self.exit_commands:
            if message == cmd or message.startswith(cmd + " "):
                return True
        return False

    def is_help_command(self, message: str) -> bool:
        """检查是否为帮助命令"""
        help_patterns = ["help", "帮助"]
        message_lower = message.strip().lower()

        for cmd in self.switch_commands:
            cmd_base = cmd.lstrip("/")
            for pattern in help_patterns:
                if message_lower in [f"{cmd} {pattern}", f"{cmd_base} {pattern}"]:
                    return True
        return False

    def is_status_command(self, message: str) -> bool:
        """检查是否为状态命令"""
        return self._match_subcommand(message, ["status", "状态"])

    def is_config_command(self, message: str) -> bool:
        """检查是否为配置查看命令"""
        return self._match_subcommand(message, ["config", "配置"])

    def is_init_command(self, message: str) -> bool:
        """检查是否为初始化自检命令"""
        return self._match_subcommand(message, ["init", "check", "检查"])

    def _match_subcommand(self, message: str, keywords: list[str]) -> bool:
        """检查是否匹配子命令"""
        message_lower = message.strip().lower()
        for cmd in self.switch_commands:
            cmd_base = cmd.lstrip("/").lower()
            for keyword in keywords:
                if message_lower in [f"{cmd} {keyword}", f"{cmd_base} {keyword}"]:
                    return True
        return False

    def extract_message(self, message: str) -> str:
        """从消息中提取实际内容（去除命令前缀）"""
        message = message.strip()
        for cmd in self.switch_commands:
            if message.startswith(cmd):
                return message[len(cmd) :].strip()
            cmd_no_slash = cmd.lstrip("/")
            if message.startswith(cmd_no_slash):
                return message[len(cmd_no_slash) :].strip()
        return message

    def is_session_command(self, message: str) -> bool:
        """检查是否为会话选择命令"""
        message = message.strip().lower()
        for cmd in self.switch_commands:
            cmd_base = cmd.lstrip("/").lower()
            if message.startswith(f"{cmd} session") or message.startswith(
                f"{cmd_base} session"
            ):
                return True
        return False

    def extract_session_name(self, message: str) -> str | None:
        """从消息中提取会话名称"""
        message = message.strip()
        for cmd in self.switch_commands:
            patterns = [f"{cmd} session ", f"{cmd.lstrip('/')} session "]
            for pattern in patterns:
                if message.lower().startswith(pattern.lower()):
                    return message[len(pattern) :].strip()
        return None

    def parse_command(self, message: str) -> tuple[str, str | None]:
        """解析命令

        Returns:
            (command_type, extracted_message)
            command_type: "switch", "exit", "help", "status", "config", "init", "session", "none"
            extracted_message: 提取的消息内容（对 switch/session 命令有效）
        """
        if self.is_help_command(message):
            return ("help", None)

        if self.is_status_command(message):
            return ("status", None)

        if self.is_config_command(message):
            return ("config", None)

        if self.is_init_command(message):
            return ("init", None)

        if self.is_exit_command(message):
            return ("exit", None)

        if self.is_session_command(message):
            session_name = self.extract_session_name(message)
            return ("session", session_name)

        if self.is_switch_command(message):
            extracted = self.extract_message(message)
            return ("switch", extracted if extracted else None)

        return ("none", None)

    @staticmethod
    def get_help_text() -> str:
        """获取帮助文本"""
        return """🤖 OpenClaw 桥接插件使用说明

📋 切换指令：
  /clawd <消息>  - 切换到 OpenClaw 模式并发送消息
  /管理 <消息>   - 同上（别名）

📋 状态与自检：
  /clawd status  - 查看当前模式、会话与连接配置
  /clawd config  - 查看当前生效配置（敏感信息脱敏）
  /clawd init    - 执行网关连通性初始化检查

📋 会话管理：
  /clawd session <名称> - 切换到指定会话
  /clawd session        - 查看当前会话

📋 退出指令：
  /退出 或 /返回 - 退出 OpenClaw 模式，返回 AstrBot

💡 使用示例：
  /clawd 帮我检查系统状态
  /clawd status
  /clawd init
  /clawd session work   - 切换到工作会话
  /clawd session home   - 切换到个人会话
  /退出

⚠️ 注意：
  - 仅管理员可使用此功能
  - 不同会话的对话历史相互独立
  - 确保 OpenClaw Gateway 正在运行
  - 长时间任务可能需要等待"""
