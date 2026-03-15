import html as _html
import logging
from functools import partial

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
)

from bot import database as db
from bot.ai.corrector import correct_transcript
from bot.ai.summarizer import summarize_episode
from bot.config import settings
from bot.feed import fetch_feed_entries
from bot.formatting import format_summary, send_html
from bot.handlers.callbacks import (
    DigestEpCallback,
    DigestNavCallback,
    DigestPodCallback,
)
from bot.handlers.episode_picker import build_episode_keyboard, get_or_fetch_transcript
from bot.i18n import gettext

logger = logging.getLogger(__name__)

DIGEST_CHOOSE_POD = 0
DIGEST_CHOOSE_EP = 1


async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
                callback_data=DigestPodCallback(subscription_id=sub.id).serialize(),
            )
        ]
        for sub in subscriptions
    ]
    buttons.append(
        [
            InlineKeyboardButton(
                gettext(lang, "cancel_btn"),
                callback_data=DigestPodCallback(subscription_id=None).serialize(),
            )
        ]
    )
    await update.message.reply_text(gettext(lang, "select_podcast"), reply_markup=InlineKeyboardMarkup(buttons))
    return DIGEST_CHOOSE_POD


async def digest_pod_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = await db.get_user_language(user.id)
    subscription_id = DigestPodCallback.parse(query.data).subscription_id

    if subscription_id is None:
        await query.edit_message_text(gettext(lang, "canceled"))
        return ConversationHandler.END

    sub = await db.get_subscription_by_id(subscription_id)
    if sub is None:
        await query.edit_message_text(gettext(lang, "sub_not_found"))
        return ConversationHandler.END

    try:
        entries = await fetch_feed_entries(sub.rss_url, limit=50)
    except Exception as exc:
        logger.error("RSS fetch failed for %s: %s", sub.rss_url, exc)
        entries = []

    if not entries:
        cached = await db.get_episodes_by_podcast(sub.podcast_id, limit=50)
        if not cached:
            await query.edit_message_text(gettext(lang, "rss_unavailable"))
            return ConversationHandler.END
        entries = [
            {"title": ep["title"] or "Untitled", "id": ep["episode_guid"], "enclosures": [], "links": [], "summary": ""}
            for ep in cached
        ]

    context.user_data["digest_eps"] = [
        {
            "title": e.get("title") or "Untitled",
            "entry": {**dict(e), "enclosures": list(e.get("enclosures", []))},
            "podcast_title": sub.podcast_title,
            "custom_prompt": sub.custom_prompt,
        }
        for e in entries
    ]
    context.user_data["digest_offset"] = 0
    keyboard = build_episode_keyboard(
        context.user_data["digest_eps"],
        0,
        subscription_id,
        lang,
        DigestEpCallback,
        DigestNavCallback,
    )
    await query.edit_message_text(
        gettext(lang, "choose_episode", title=f"<b>{_html.escape(sub.podcast_title)}</b>"),
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    return DIGEST_CHOOSE_EP


async def digest_nav(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = await db.get_user_language(user.id)
    cb = DigestNavCallback.parse(query.data)

    ep_data = context.user_data.get("digest_eps", [])
    if not ep_data:
        await query.edit_message_text(gettext(lang, "ep_data_expired"))
        return ConversationHandler.END

    context.user_data["digest_offset"] = cb.offset
    keyboard = build_episode_keyboard(ep_data, cb.offset, cb.subscription_id, lang, DigestEpCallback, DigestNavCallback)
    await query.edit_message_reply_markup(reply_markup=keyboard)
    return DIGEST_CHOOSE_EP


async def digest_ep_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = await db.get_user_language(user.id)
    cb = DigestEpCallback.parse(query.data)

    if cb.subscription_id is None:
        if "digest_eps" in context.user_data:
            del context.user_data["digest_eps"]
        await query.edit_message_text(gettext(lang, "canceled"))
        return ConversationHandler.END

    subscription_id = cb.subscription_id
    episode_index = cb.index
    ep_data = context.user_data.get("digest_eps", [])

    if not ep_data or episode_index >= len(ep_data):
        await query.edit_message_text(gettext(lang, "ep_data_expired"))
        return ConversationHandler.END

    sub = await db.get_subscription_by_id(subscription_id)
    user_id = await db.get_or_create_user(user.id, update.effective_chat.id)
    ep = ep_data[episode_index]
    guid = ep["entry"].get("id") or ep["entry"].get("link") or ep["entry"].get("title", "")
    has_transcript = bool(await db.get_episode_transcript(sub.podcast_id, guid))
    state_msg = gettext(lang, "summarizing") if has_transcript else gettext(lang, "transcribing")
    await query.edit_message_text(
        f"{state_msg} <i>{_html.escape(ep['title'])}</i>…",
        parse_mode="HTML",
    )

    try:
        corrector = partial(correct_transcript, settings.gemini_model)
        transcriber = context.bot_data["transcriber"]
        content = await get_or_fetch_transcript(sub.podcast_id, guid, ep["entry"], transcriber, ep["podcast_title"], corrector)
        summary = await summarize_episode(
            ep["title"],
            content,
            settings.gemini_model,
            custom_prompt=ep.get("custom_prompt"),
        )
        published_at = ep["entry"].get("published")
        await db.mark_episode_seen(
            user_id,
            sub.podcast_id,
            guid,
            title=ep["title"],
            published_at=published_at,
            summary=summary,
            transcript=content,
        )
        text = format_summary(ep["podcast_title"], ep["title"], summary)
        await send_html(query.message.reply_text, text)
    except Exception as exc:
        logger.error("digest summarize error: %s", exc)
        await query.message.reply_text(gettext(lang, "error_generating"))

    return ConversationHandler.END


digest_conv = ConversationHandler(
    entry_points=[CommandHandler("digest", cmd_digest)],
    states={
        DIGEST_CHOOSE_POD: [
            CallbackQueryHandler(digest_pod_selected, pattern=r"^digest:pod:"),
        ],
        DIGEST_CHOOSE_EP: [
            CallbackQueryHandler(digest_nav, pattern=r"^digest:nav:"),
            CallbackQueryHandler(digest_ep_selected, pattern=r"^digest:ep:"),
        ],
    },
    fallbacks=[CommandHandler("digest", cmd_digest)],
    per_message=False,
    per_user=True,
    per_chat=True,
    allow_reentry=True,
)
