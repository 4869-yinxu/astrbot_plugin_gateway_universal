"""
会话管理器

负责管理用户会话状态和会话隔离
"""

from dataclasses import dataclass

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from .utils import extract_user_id


@dataclass
class Session:
    """会话数据"""

    mode: str  # "clawdbot" 或 "astrbot"
    session_key: str  # OpenClaw Gateway 的会话标识
    session_name: str = "default"  # 会话名称


class SessionManager:
    """会话管理器

    管理用户会话状态，确保会话隔离：
    - 每个用户在每个群组/私聊都有独立的会话
    - 管理员在群组 A 的操作不影响群组 B
    """

    MODE_CLAWDBOT = "clawdbot"
    MODE_ASTRBOT = "astrbot"

    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def get_session_id(self, event: AstrMessageEvent) -> str:
        """获取会话 ID

        格式: platform_user_id_group_id (群组) 或 platform_user_id_private (私聊)
        """
        platform = event.get_platform_name()
        group_id = event.get_group_id() or ""
        user_id = extract_user_id(event, group_id)

        if group_id:
            session_id = f"{platform}_{user_id}_{group_id}"
        else:
            session_id = f"{platform}_{user_id}_private"

        logger.debug(f"[SessionManager] 会话 ID: {session_id}")
        return session_id

    def get_gateway_session_key(
        self, event: AstrMessageEvent, session_name: str = "default"
    ) -> str:
        """获取 OpenClaw Gateway 的会话标识

        Args:
            event: AstrBot 消息事件
            session_name: 会话名称，用于区分不同的对话上下文

        Returns:
            会话标识字符串
        """
        platform = event.get_platform_name()
        group_id = event.get_group_id() or ""
        user_id = extract_user_id(event, group_id)

        if group_id:
            return f"astrbot_{platform}_{user_id}_{group_id}_{session_name}"
        else:
            return f"astrbot_{platform}_{user_id}_private_{session_name}"

    def get_shared_session_key(self, agent_id: str, session_name: str) -> str:
        """获取与 OpenClaw WebUI 共享的会话标识

        Args:
            agent_id: Agent ID
            session_name: 会话名称

        Returns:
            格式: agent:{agent_id}:{session_name}
        """
        return f"agent:{agent_id}:{session_name}"

    def is_in_clawdbot_mode(self, session_id: str) -> bool:
        """检查会话是否在 OpenClaw 模式"""
        session = self._sessions.get(session_id)
        return session is not None and session.mode == self.MODE_CLAWDBOT

    def enter_clawdbot_mode(
        self, session_id: str, session_key: str, session_name: str = "default"
    ) -> None:
        """进入 OpenClaw 模式

        Args:
            session_id: 会话 ID
            session_key: Gateway 会话标识
            session_name: 会话名称
        """
        self._sessions[session_id] = Session(
            mode=self.MODE_CLAWDBOT, session_key=session_key, session_name=session_name
        )
        logger.info(
            f"[SessionManager] ✅ 进入 OpenClaw 模式: {session_id} (会话: {session_name})"
        )

    def exit_clawdbot_mode(self, session_id: str) -> bool:
        """退出 OpenClaw 模式

        Returns:
            是否成功退出（如果本来就不在 OpenClaw 模式则返回 False）
        """
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info(f"[SessionManager] ✅ 退出 OpenClaw 模式: {session_id}")
            return True
        return False

    def get_session_key(self, session_id: str) -> str | None:
        """获取会话的 Gateway session key"""
        session = self._sessions.get(session_id)
        return session.session_key if session else None

    def get_session_name(self, session_id: str) -> str | None:
        """获取会话名称"""
        session = self._sessions.get(session_id)
        return session.session_name if session else None

    def set_session_name(
        self,
        session_id: str,
        session_name: str,
        event: "AstrMessageEvent",
        agent_id: str = None,
        share_with_webui: bool = False,
    ) -> bool:
        """设置会话名称并更新 session_key

        Args:
            session_id: 会话 ID
            session_name: 新的会话名称
            event: 消息事件（用于生成新的 session_key）
            agent_id: Agent ID（共享模式需要）
            share_with_webui: 是否与 WebUI 共享会话

        Returns:
            是否成功设置
        """
        session = self._sessions.get(session_id)
        if session:
            # 生成新的 session_key
            if share_with_webui and agent_id:
                new_session_key = self.get_shared_session_key(agent_id, session_name)
            else:
                new_session_key = self.get_gateway_session_key(event, session_name)

            session.session_name = session_name
            session.session_key = new_session_key
            logger.info(f"[SessionManager] ✅ 切换会话: {session_id} -> {session_name}")
            return True
        return False

    def clear_all(self) -> int:
        """清理所有会话

        Returns:
            清理的会话数量
        """
        count = len(self._sessions)
        self._sessions.clear()
        logger.info(f"[SessionManager] 已清理 {count} 个会话")
        return count
