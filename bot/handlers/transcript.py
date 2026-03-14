import html as _html
import io
import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler

from bot import database as db
from bot.feed import fetch_feed_entries, get_episode_content
from bot.handlers.callbacks import (
    TranscriptEpCallback,
    TranscriptNavCallback,
    TranscriptPodCallback,
)
from bot.i18n import gettext

logger = logging.getLogger(__name__)

TRANSCRIPT_CHOOSE_POD = 0
TRANSCRIPT_CHOOSE_EP = 1

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_filename(podcast: str, episode: str) -> str:
    def _clean(s: str) -> str:
        return _UNSAFE.sub("", s).strip().replace(" ", "_")[:50]

    return f"{_clean(podcast)}_{_clean(episode)}.md"


def _build_markdown(
    podcast_title: str,
    episode_title: str,
    published_at: str | None,
    summary: str | None,
    transcript: str,
) -> str:
    summary_section = summary or "(not yet generated)"
    return (
        f"# {episode_title}\n"
        f"**Podcast:** {podcast_title}\n"
        f"**Published:** {published_at or 'Unknown'}\n\n"
        f"## Summary\n{summary_section}\n\n"
        f"## Transcript\n{transcript}\n"
    )


async def cmd_transcript(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    chat_id = update.effective_chat.id
    lang = await db.get_user_language(user.id)
    db_user_id = await db.get_or_create_user(user.id, chat_id)
    subscriptions = await db.get_subscriptions(db_user_id)

    if not subscriptions:
        await update.message.reply_text(gettext(lang, "no_subs_please_subscribe"))
        return ConversationHandler.END

    buttons = [
        [
            InlineKeyboardButton(
                sub.podcast_title,
                callback_data=TranscriptPodCallback(subscription_id=sub.id).serialize(),
            )
        ]
        for sub in subscriptions
    ]
    buttons.append(
        [
            InlineKeyboardButton(
                gettext(lang, "cancel_btn"),
                callback_data=TranscriptPodCallback(subscription_id=None).serialize(),
            )
        ]
    )
    await update.message.reply_text(
        gettext(lang, "select_podcast"), reply_markup=InlineKeyboardMarkup(buttons)
    )
    return TRANSCRIPT_CHOOSE_POD


_PAGE_SIZE = 5


def _build_episode_keyboard(
    entries: list,
    offset: int,
    subscription_id: str,
    lang: str,
) -> InlineKeyboardMarkup:
    page = entries[offset : offset + _PAGE_SIZE]
    buttons = [
        [
            InlineKeyboardButton(
                ep["title"][:60],
                callback_data=TranscriptEpCallback(
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
                callback_data=TranscriptNavCallback(
                    subscription_id=subscription_id, offset=offset - _PAGE_SIZE
                ).serialize(),
            )
        )
    if offset + _PAGE_SIZE < len(entries):
        nav_row.append(
            InlineKeyboardButton(
                gettext(lang, "nav_next"),
                callback_data=TranscriptNavCallback(
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
                callback_data=TranscriptEpCallback(subscription_id=None).serialize(),
            )
        ]
    )
    return InlineKeyboardMarkup(buttons)


async def transcript_pod_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = await db.get_user_language(user.id)
    subscription_id = TranscriptPodCallback.parse(query.data).subscription_id

    if subscription_id is None:
        await query.edit_message_text(gettext(lang, "canceled"))
        return ConversationHandler.END

    sub = await db.get_subscription_by_id(subscription_id)
    if sub is None:
        await query.edit_message_text(gettext(lang, "sub_not_found"))
        return ConversationHandler.END

    entries = await fetch_feed_entries(sub.rss_url, limit=50)
    if not entries:
        await query.edit_message_text(gettext(lang, "no_episodes_found"))
        return ConversationHandler.END

    context.user_data["transcript_eps"] = [
        {
            "title": e.get("title") or "Untitled",
            "entry": {**dict(e), "enclosures": list(e.get("enclosures", []))},
            "podcast_title": sub.podcast_title,
            "subscription_id": sub.id,
        }
        for e in entries
    ]
    context.user_data["transcript_offset"] = 0
    keyboard = _build_episode_keyboard(
        context.user_data["transcript_eps"], 0, subscription_id, lang
    )
    await query.edit_message_text(
        gettext(lang, "choose_episode", title=f"<b>{_html.escape(sub.podcast_title)}</b>"),
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    return TRANSCRIPT_CHOOSE_EP


async def transcript_nav(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = await db.get_user_language(user.id)
    cb = TranscriptNavCallback.parse(query.data)

    ep_data = context.user_data.get("transcript_eps", [])
    if not ep_data:
        await query.edit_message_text(gettext(lang, "transcript_ep_data_expired"))
        return ConversationHandler.END

    context.user_data["transcript_offset"] = cb.offset
    keyboard = _build_episode_keyboard(ep_data, cb.offset, cb.subscription_id, lang)
    await query.edit_message_reply_markup(reply_markup=keyboard)
    return TRANSCRIPT_CHOOSE_EP


async def transcript_ep_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = await db.get_user_language(user.id)
    cb = TranscriptEpCallback.parse(query.data)

    if cb.subscription_id is None:
        if "transcript_eps" in context.user_data:
            del context.user_data["transcript_eps"]
        await query.edit_message_text(gettext(lang, "canceled"))
        return ConversationHandler.END

    subscription_id = cb.subscription_id
    episode_index = cb.index
    ep_data = context.user_data.get("transcript_eps", [])

    if not ep_data or episode_index >= len(ep_data):
        await query.edit_message_text(gettext(lang, "transcript_ep_data_expired"))
        return ConversationHandler.END

    sub = await db.get_subscription_by_id(subscription_id)
    user_id = await db.get_or_create_user(user.id, update.effective_chat.id)
    ep = ep_data[episode_index]
    guid = ep["entry"].get("id") or ep["entry"].get("link") or ep["entry"].get("title", "")
    existing = await db.get_episode_transcript(sub.podcast_id, guid)

    await query.edit_message_text(
        gettext(lang, "transcript_fetching", title=_html.escape(ep["title"])),
        parse_mode="HTML",
    )

    try:
        if existing:
            transcript = existing
        else:
            transcriber = context.bot_data["transcriber"]
            transcript = await get_episode_content(
                ep["entry"],
                transcriber,
                podcast_title=ep["podcast_title"],
                corrector=None,
            )
            published_at = ep["entry"].get("published")
            await db.mark_episode_seen(
                user_id,
                sub.podcast_id,
                guid,
                title=ep["title"],
                published_at=published_at,
                transcript=transcript,
            )

        episode_id = await db.get_episode_id(sub.podcast_id, guid)
        summary = await db.get_episode_summary(user_id, episode_id) if episode_id else None
        published_at = ep["entry"].get("published")
        content = _build_markdown(
            ep["podcast_title"], ep["title"], published_at, summary, transcript
        )
        file_obj = io.BytesIO(content.encode("utf-8"))
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=InputFile(file_obj, filename=_safe_filename(ep["podcast_title"], ep["title"])),
            caption=gettext(lang, "transcript_caption", title=ep["title"]),
        )
    except Exception as exc:
        logger.error("transcript fetch error: %s", exc)
        await query.message.reply_text(gettext(lang, "transcript_error"))

    return ConversationHandler.END


transcript_conv = ConversationHandler(
    entry_points=[CommandHandler("transcript", cmd_transcript)],
    states={
        TRANSCRIPT_CHOOSE_POD: [
            CallbackQueryHandler(transcript_pod_selected, pattern=r"^transcript:pod:"),
        ],
        TRANSCRIPT_CHOOSE_EP: [
            CallbackQueryHandler(transcript_nav, pattern=r"^transcript:nav:"),
            CallbackQueryHandler(transcript_ep_selected, pattern=r"^transcript:ep:"),
        ],
    },
    fallbacks=[CommandHandler("transcript", cmd_transcript)],
    per_message=False,
    per_user=True,
    per_chat=True,
    allow_reentry=True,
)
