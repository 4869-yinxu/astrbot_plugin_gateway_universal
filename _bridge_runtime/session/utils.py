"""
会话工具函数
"""

from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent


def extract_user_id(event: AstrMessageEvent, group_id: str = "") -> str:
    """从事件中提取用户 ID

    尝试多种方法获取用户 ID，确保不会错误地使用群组 ID

    Args:
        event: AstrBot 消息事件
        group_id: 群组 ID（用于验证）

    Returns:
        用户 ID 字符串
    """
    sender_user_id = None

    # 方法1：从 message_obj.sender.user_id 获取
    if hasattr(event, "message_obj") and hasattr(event.message_obj, "sender"):
        try:
            raw_user_id = event.message_obj.sender.user_id
            sender_user_id = str(raw_user_id)
            if sender_user_id and sender_user_id != group_id:
                logger.debug(
                    f"[session] 从 message_obj.sender.user_id 获取: {sender_user_id}"
                )
                return sender_user_id
        except (AttributeError, KeyError):
            pass

    # 方法2：使用 get_sender_id()
    try:
        raw_user_id = event.get_sender_id()
        sender_user_id = str(raw_user_id)
        if sender_user_id and sender_user_id != group_id:
            logger.debug(f"[session] 从 get_sender_id() 获取: {sender_user_id}")
            return sender_user_id
    except (AttributeError, KeyError):
        pass

    # 方法3：从 session_id 解析
    if event.session_id:
        parts = str(event.session_id).split("_")
        if len(parts) >= 3:
            potential_user_id = parts[1]
            if potential_user_id and potential_user_id != group_id:
                logger.debug(f"[session] 从 session_id 解析: {potential_user_id}")
                return potential_user_id

    # 方法4：从 raw_message 提取（OneBot）
    if hasattr(event, "message_obj") and hasattr(event.message_obj, "raw_message"):
        try:
            raw_msg = event.message_obj.raw_message
            user_id = _extract_user_id_from_raw(raw_msg, group_id)
            if user_id:
                logger.debug(f"[session] 从 raw_message 获取: {user_id}")
                return user_id
        except Exception:
            pass

    # 回退：使用 session_id 的最后部分
    if event.session_id:
        parts = str(event.session_id).split("_")
        if parts:
            logger.warning("[session] 使用 session_id 最后部分作为用户 ID")
            return parts[-1]

    logger.error("[session] 无法获取用户 ID")
    return "unknown"


def _extract_user_id_from_raw(raw_msg: Any, group_id: str) -> str | None:
    """从 raw_message 中提取用户 ID"""
    # 检查 user_id 属性
    if hasattr(raw_msg, "user_id"):
        user_id = str(raw_msg.user_id)
        if user_id != group_id:
            return user_id

    # 检查字典格式
    if isinstance(raw_msg, dict):
        for key in ["user_id", "sender", "user", "from"]:
            if key in raw_msg:
                value = raw_msg[key]
                if isinstance(value, dict):
                    if "user_id" in value:
                        user_id = str(value["user_id"])
                    elif "id" in value:
                        user_id = str(value["id"])
                    else:
                        continue
                else:
                    user_id = str(value)

                if user_id and user_id != group_id:
                    return user_id

    return None
