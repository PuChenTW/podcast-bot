import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot import database as db
from bot.feed import fetch_feed, parse_podcast_title, resolve_rss_url
from bot.i18n import gettext

logger = logging.getLogger(__name__)

SUBSCRIBE_WAITING_URL = 0


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    lang = await db.get_user_language(user.id)
    await update.message.reply_text(gettext(lang, "start_message"))


async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    lang = await db.get_user_language(user.id)
    await update.message.reply_text(gettext(lang, "subscribe_prompt"))
    return SUBSCRIBE_WAITING_URL


async def subscribe_url_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    raw_url = update.message.text.strip()
    user = update.effective_user
    chat_id = update.effective_chat.id
    lang = await db.get_user_language(user.id)

    msg = await update.message.reply_text(gettext(lang, "fetching_feed"))

    try:
        rss_url = await resolve_rss_url(raw_url)
    except ValueError as exc:
        await msg.edit_text(str(exc))
        return ConversationHandler.END

    try:
        parsed = await fetch_feed(rss_url)
    except Exception as exc:
        logger.error("Feed fetch error: %s", exc)
        await msg.edit_text(gettext(lang, "fetch_error"))
        return ConversationHandler.END

    if parsed.bozo and not parsed.entries:
        await msg.edit_text(gettext(lang, "invalid_feed"))
        return ConversationHandler.END

    title = parse_podcast_title(parsed)
    user_id = await db.get_or_create_user(user.id, chat_id)
    sub_id = await db.add_subscription(user_id, title, rss_url)

    # Mark all current episodes as seen — no backlog flood
    for entry in parsed.entries:
        guid = entry.get("id") or entry.get("link") or entry.get("title", "")
        if guid:
            await db.mark_episode_seen(
                sub_id,
                guid,
                title=entry.get("title"),
                published_at=entry.get("published"),
            )

    await msg.edit_text(gettext(lang, "subscribed", title=title))
    return ConversationHandler.END


UNSUB_CHOOSE_POD = 0


async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    lang = await db.get_user_language(user.id)
    user_id = await db.get_or_create_user(user.id, update.effective_chat.id)
    subs = await db.get_subscriptions(user_id)

    if not subs:
        await update.message.reply_text(gettext(lang, "no_subscriptions"))
        return ConversationHandler.END

    buttons = [
        [InlineKeyboardButton(s.podcast_title, callback_data=f"unsub:{s.id}")]
        for s in subs
    ]
    buttons.append(
        [InlineKeyboardButton(gettext(lang, "cancel_btn"), callback_data="unsub:cancel")]
    )
    await update.message.reply_text(
        gettext(lang, "unsub_choose"),
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return UNSUB_CHOOSE_POD


async def unsub_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = await db.get_user_language(user.id)
    target = query.data.split(":", 1)[1]
    
    sub = await db.get_subscription_by_id(target)
    if sub is None:
        await query.edit_message_text(gettext(lang, "sub_not_found"))
        return ConversationHandler.END

    await db.remove_subscription_by_id(target)
    await query.edit_message_text(gettext(lang, "unsub_success", title=sub.podcast_title))
    return ConversationHandler.END


async def unsub_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    user = update.effective_user
    lang = await db.get_user_language(user.id)
    await query.answer()
    await query.edit_message_text(gettext(lang, "canceled"))
    return ConversationHandler.END


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    lang = await db.get_user_language(user.id)
    user_id = await db.get_or_create_user(user.id, update.effective_chat.id)
    subs = await db.get_subscriptions(user_id)

    if not subs:
        await update.message.reply_text(gettext(lang, "no_subscriptions_use_subscribe"))
        return

    lines = [f"{i + 1}. {s.podcast_title}" for i, s in enumerate(subs)]
    await update.message.reply_text(f"{gettext(lang, 'your_subscriptions')}\n" + "\n".join(lines))


unsubscribe_conv = ConversationHandler(
    entry_points=[CommandHandler("unsubscribe", cmd_unsubscribe)],
    states={
        UNSUB_CHOOSE_POD: [
            CallbackQueryHandler(unsub_selected, pattern=r"^unsub:(?!cancel)"),
            CallbackQueryHandler(unsub_cancel, pattern=r"^unsub:cancel"),
        ],
    },
    fallbacks=[CommandHandler("unsubscribe", cmd_unsubscribe)],
    per_user=True,
    per_chat=True,
    allow_reentry=True,
)

subscribe_conv = ConversationHandler(
    entry_points=[CommandHandler("subscribe", cmd_subscribe)],
    states={
        SUBSCRIBE_WAITING_URL: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, subscribe_url_received),
        ],
    },
    fallbacks=[CommandHandler("subscribe", cmd_subscribe)],
    per_user=True,
    per_chat=True,
    allow_reentry=True,
)
