from __future__ import annotations
from typing import Optional
from notifications.services.discord.service import DiscordService
from notifications.services.email.service import EmailService
from notifications.services.default.service import DefaultService
from notifications.services.base import BaseService


def get_service(scheme: str) -> BaseService:
    sk = (scheme or "").lower()
    if sk.startswith("discord"):
        return DiscordService()
    if sk.startswith("email") or sk.startswith("mail"):
        return EmailService()
    return DefaultService()

