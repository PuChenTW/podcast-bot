from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot import database as db
from bot.feed import get_episode_content
from bot.i18n import gettext

_PAGE_SIZE = 5


def build_episode_keyboard(
    entries: list,
    offset: int,
    subscription_id: str,
    lang: str,
    ep_callback_cls,
    nav_callback_cls,
) -> InlineKeyboardMarkup:
    page = entries[offset : offset + _PAGE_SIZE]
    buttons = [
        [
            InlineKeyboardButton(
                ep["title"][:60],
                callback_data=ep_callback_cls(
                    subscription_id=subscription_id, index=offset + i
                ).serialize(),
            )
        ]
        for i, ep in enumerate(page)
    ]
    nav_row = []
    if offset > 0:
        nav_row.append(
            InlineKeyboardButton(
                gettext(lang, "nav_prev"),
                callback_data=nav_callback_cls(
                    subscription_id=subscription_id, offset=offset - _PAGE_SIZE
                ).serialize(),
            )
        )
    if offset + _PAGE_SIZE < len(entries):
        nav_row.append(
            InlineKeyboardButton(
                gettext(lang, "nav_next"),
                callback_data=nav_callback_cls(
                    subscription_id=subscription_id, offset=offset + _PAGE_SIZE
                ).serialize(),
            )
        )
    if nav_row:
        buttons.append(nav_row)
    buttons.append(
        [
            InlineKeyboardButton(
                gettext(lang, "cancel_btn"),
                callback_data=ep_callback_cls(subscription_id=None).serialize(),
            )
        ]
    )
    return InlineKeyboardMarkup(buttons)


async def get_or_fetch_transcript(
    podcast_id: str,
    guid: str,
    entry: dict,
    transcriber,
    podcast_title: str,
    corrector,
) -> str | None:
    existing = await db.get_episode_transcript(podcast_id, guid)
    if existing:
        return existing
    return await get_episode_content(
        entry,
        transcriber,
        podcast_title=podcast_title,
        corrector=corrector,
    )
