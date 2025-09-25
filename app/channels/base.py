from __future__ import annotations

import abc
import os
from typing import Any, Dict, Optional, Type

from app.models import NotificationRequest


class ChannelError(Exception):
    """Base channel error."""


class TransientChannelError(ChannelError):
    """Retryable/transient error (timeouts, 5xx, etc.)."""


class PermanentChannelError(ChannelError):
    """Non-retryable error (validation, 4xx, bad recipient)."""


class BaseChannel(abc.ABC):
    """
    Abstract base for channels.
    Implementations must provide async send() that returns a dict with delivery metadata.
    """

    name: str = "base"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}

    @abc.abstractmethod
    async def send(self, req: NotificationRequest, rendered: Dict[str, Optional[str]]) -> Dict[str, Any]:
        """
        Perform the send operation.
        req: NotificationRequest
        rendered: dict with keys like subject, body (already rendered with variables)
        Returns metadata dict (e.g., provider message id)
        Raises TransientChannelError for retryable failures; PermanentChannelError for non-retryable.
        """
        raise NotImplementedError


# --------------------------
# Channel registry
# --------------------------

_CHANNELS: Dict[str, Type[BaseChannel]] = {}


def register_channel(channel_name: str):
    def decorator(cls: Type[BaseChannel]) -> Type[BaseChannel]:
        _CHANNELS[channel_name] = cls
        cls.name = channel_name
        return cls
    return decorator


def get_channel(channel_name: str, config: Optional[Dict[str, Any]] = None) -> BaseChannel:
    cls = _CHANNELS.get(channel_name)
    if not cls:
        raise PermanentChannelError(f"Channel not supported: {channel_name}")
    return cls(config=config)
