import html as _html
import io
import logging
import re

from telegram import InputFile, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler, ContextTypes

from bot import database as db
from bot.config import settings
from bot.feed import fetch_feed_entries, get_episode_content
from bot.i18n import gettext

logger = logging.getLogger(__name__)

TRANSCRIPT_CHOOSE_POD = 0
TRANSCRIPT_CHOOSE_EP = 1

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_filename(podcast: str, episode: str) -> str:
    def _clean(s: str) -> str:
        return _UNSAFE.sub('', s).strip().replace(' ', '_')[:50]
    return f"{_clean(podcast)}_{_clean(episode)}.md"


def _build_markdown(podcast_title: str, episode_title: str, published_at: str | None, summary: str | None, transcript: str) -> str:
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
                sub.podcast_title, callback_data=f"transcript:pod:{sub.id}"
            )
        ]
        for sub in subscriptions
    ]
    buttons.append([InlineKeyboardButton(gettext(lang, "cancel_btn"), callback_data="transcript:pod:cancel")])
    await update.message.reply_text(
        gettext(lang, "select_podcast"), reply_markup=InlineKeyboardMarkup(buttons)
    )
    return TRANSCRIPT_CHOOSE_POD


async def transcript_pod_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = await db.get_user_language(user.id)
    subscription_id = query.data.split(":")[2]

    if subscription_id == "cancel":
        await query.edit_message_text(gettext(lang, "canceled"))
        return ConversationHandler.END

    sub = await db.get_subscription_by_id(subscription_id)
    if sub is None:
        await query.edit_message_text(gettext(lang, "sub_not_found"))
        return ConversationHandler.END

    entries = await fetch_feed_entries(sub.rss_url, limit=5)
    if not entries:
        await query.edit_message_text(gettext(lang, "no_episodes_found"))
        return ConversationHandler.END

    buttons = [
        [
            InlineKeyboardButton(
                (e.get("title") or "Untitled")[:60],
                callback_data=f"transcript:ep:{subscription_id}:{i}",
            )
        ]
        for i, e in enumerate(entries)
    ]
    context.user_data["transcript_eps"] = [
        {
            "title": e.get("title") or "Untitled",
            "entry": {**dict(e), "enclosures": list(e.get("enclosures", []))},
            "podcast_title": sub.podcast_title,
            "subscription_id": sub.id,
        }
        for e in entries
    ]
    buttons.append([InlineKeyboardButton(gettext(lang, "cancel_btn"), callback_data="transcript:ep:cancel:0")])
    await query.edit_message_text(
        gettext(lang, "choose_episode", title=f"<b>{_html.escape(sub.podcast_title)}</b>"),
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )
    return TRANSCRIPT_CHOOSE_EP


async def transcript_ep_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = await db.get_user_language(user.id)
    parts = query.data.split(":")

    if parts[2] == "cancel":
        if "transcript_eps" in context.user_data:
            del context.user_data["transcript_eps"]
        await query.edit_message_text(gettext(lang, "canceled"))
        return ConversationHandler.END

    subscription_id = parts[2]
    episode_index = int(parts[3])
    ep_data = context.user_data.get("transcript_eps", [])

    if not ep_data or episode_index >= len(ep_data):
        await query.edit_message_text(gettext(lang, "transcript_ep_data_expired"))
        return ConversationHandler.END

    ep = ep_data[episode_index]
    guid = (
        ep["entry"].get("id")
        or ep["entry"].get("link")
        or ep["entry"].get("title", "")
    )
    existing = await db.get_episode_transcript(subscription_id, guid)

    await query.edit_message_text(
        gettext(lang, "transcript_fetching", title=_html.escape(ep["title"])),
        parse_mode="HTML",
    )

    try:
        if existing:
            transcript = existing
        else:
            transcript = await get_episode_content(
                ep["entry"],
                settings.whisper_model,
                podcast_title=ep["podcast_title"],
                corrector=None,
            )
            published_at = ep["entry"].get("published")
            await db.mark_episode_seen(
                subscription_id,
                guid,
                title=ep["title"],
                published_at=published_at,
                transcript=transcript,
            )

        summary = await db.get_episode_summary(subscription_id, guid)
        published_at = ep["entry"].get("published")
        content = _build_markdown(ep["podcast_title"], ep["title"], published_at, summary, transcript)
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
            CallbackQueryHandler(transcript_ep_selected, pattern=r"^transcript:ep:"),
        ],
    },
    fallbacks=[CommandHandler("transcript", cmd_transcript)],
    per_message=False,
    per_user=True,
    per_chat=True,
    allow_reentry=True,
)
