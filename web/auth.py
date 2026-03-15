import os

from fastapi import Request

from shared import database as db


async def get_current_user(request: Request) -> str:
    """Phase 1: always returns the user identified by WEB_USER_TELEGRAM_ID.
    Phase 2: replace body with Telegram Login Widget token verification.
    Signature (Request → str user_id ULID) must not change.

    chat_id=0 is a sentinel for web-originated users with no Telegram chat context.
    The bot scheduler skips delivery for rows where chat_id=0.
    """
    telegram_id = int(os.environ["WEB_USER_TELEGRAM_ID"])
    return await db.get_or_create_user(telegram_id, chat_id=0)
