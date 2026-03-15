import html as _html
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot import database as db
from bot.ai.chat import chat_with_episode
from bot.config import get_settings
from bot.feed import fetch_feed_entries
from bot.formatting import markdown_to_html, send_html
from bot.handlers.callbacks import ChatEpCallback, ChatNavCallback, ChatPodCallback
from bot.handlers.episode_picker import build_episode_keyboard
from bot.i18n import gettext

logger = logging.getLogger(__name__)

CHAT_CHOOSE_POD = 0
CHAT_CHOOSE_EP = 1
CHAT_TALKING = 2

_END_BTN_ROW = lambda lang: [  # noqa: E731
    InlineKeyboardButton(gettext(lang, "chat_end_button"), callback_data="chat:end")
]


async def cmd_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    chat_id = update.effective_chat.id
    lang = await db.get_user_language(user.id)
    db_user_id = await db.get_or_create_user(user.id, chat_id)
    subscriptions = await db.get_subscriptions(db_user_id)

    if not subscriptions:
        await update.message.reply_text(gettext(lang, "no_subs_please_subscribe"))
        return ConversationHandler.END

    buttons = [[InlineKeyboardButton(sub.podcast_title, callback_data=ChatPodCallback(subscription_id=sub.id).serialize())] for sub in subscriptions]
    buttons.append([InlineKeyboardButton(gettext(lang, "cancel_btn"), callback_data=ChatPodCallback(subscription_id=None).serialize())])
    await update.message.reply_text(gettext(lang, "chat_choose_pod"), reply_markup=InlineKeyboardMarkup(buttons))
    return CHAT_CHOOSE_POD


async def chat_pod_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = await db.get_user_language(user.id)
    subscription_id = ChatPodCallback.parse(query.data).subscription_id

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

    context.user_data["chat_eps"] = [
        {
            "title": e.get("title") or "Untitled",
            "entry": {**dict(e), "enclosures": list(e.get("enclosures", []))},
            "podcast_title": sub.podcast_title,
            "subscription_id": sub.id,
            "podcast_id": sub.podcast_id,
        }
        for e in entries
    ]
    context.user_data["chat_offset"] = 0
    keyboard = build_episode_keyboard(context.user_data["chat_eps"], 0, subscription_id, lang, ChatEpCallback, ChatNavCallback)
    await query.edit_message_text(
        gettext(lang, "chat_choose_ep", title=f"<b>{_html.escape(sub.podcast_title)}</b>"),
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    return CHAT_CHOOSE_EP


async def chat_nav(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = await db.get_user_language(user.id)
    cb = ChatNavCallback.parse(query.data)

    ep_data = context.user_data.get("chat_eps", [])
    if not ep_data:
        await query.edit_message_text(gettext(lang, "chat_ep_data_expired"))
        return ConversationHandler.END

    context.user_data["chat_offset"] = cb.offset
    keyboard = build_episode_keyboard(ep_data, cb.offset, cb.subscription_id, lang, ChatEpCallback, ChatNavCallback)
    await query.edit_message_reply_markup(reply_markup=keyboard)
    return CHAT_CHOOSE_EP


async def chat_ep_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = await db.get_user_language(user.id)
    cb = ChatEpCallback.parse(query.data)

    if cb.subscription_id is None:
        context.user_data.pop("chat_eps", None)
        context.user_data.pop("chat_offset", None)
        await query.edit_message_text(gettext(lang, "canceled"))
        return ConversationHandler.END

    ep_data = context.user_data.get("chat_eps", [])
    if not ep_data or cb.index >= len(ep_data):
        await query.edit_message_text(gettext(lang, "chat_ep_data_expired"))
        return ConversationHandler.END

    ep = ep_data[cb.index]
    podcast_id = ep["podcast_id"]
    guid = ep["entry"].get("id") or ep["entry"].get("link") or ep["entry"].get("title", "")

    transcript = await db.get_episode_transcript(podcast_id, guid) or ""
    episode_id = await db.get_episode_id(podcast_id, guid)
    db_user_id = await db.get_or_create_user(user.id, update.effective_chat.id)
    summary = await db.get_episode_summary(db_user_id, episode_id) if episode_id else None

    context.user_data["chat_session"] = {
        "episode_title": ep["title"],
        "podcast_title": ep["podcast_title"],
        "transcript": transcript,
        "summary": summary,
        "history": [],
        "lang": lang,
    }
    context.user_data.pop("chat_eps", None)
    context.user_data.pop("chat_offset", None)

    if transcript and summary:
        context_note = gettext(lang, "chat_context_full")
    elif summary:
        context_note = gettext(lang, "chat_context_summary_only")
    else:
        context_note = gettext(lang, "chat_context_none")

    welcome = gettext(lang, "chat_welcome", episode=_html.escape(ep["title"]), podcast=_html.escape(ep["podcast_title"]), context_note=context_note)
    end_markup = InlineKeyboardMarkup([[InlineKeyboardButton(gettext(lang, "chat_end_button"), callback_data="chat:end")]])
    await query.edit_message_text(welcome, parse_mode="HTML", reply_markup=end_markup)
    return CHAT_TALKING


async def chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session = context.user_data.get("chat_session")
    lang = session["lang"] if session else "en"

    if not session:
        await update.message.reply_text(gettext(lang, "chat_session_expired"))
        return ConversationHandler.END

    thinking_msg = await update.message.reply_text(gettext(lang, "chat_thinking"))
    try:
        response, updated_history = await chat_with_episode(
            user_message=update.message.text,
            episode_title=session["episode_title"],
            podcast_title=session["podcast_title"],
            transcript=session["transcript"],
            summary=session["summary"],
            history=session["history"],
            lang=lang,
            model=get_settings().gemini_model,
        )
        session["history"] = updated_history
    except Exception as exc:
        logger.error("chat error: %s", exc)
        await thinking_msg.edit_text(gettext(lang, "chat_error"))
        return CHAT_TALKING

    await thinking_msg.delete()
    end_markup = InlineKeyboardMarkup([[InlineKeyboardButton(gettext(lang, "chat_end_button"), callback_data="chat:end")]])
    await send_html(update.message.reply_text, markdown_to_html(response), reply_markup=end_markup)
    return CHAT_TALKING


async def chat_end(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    session = context.user_data.pop("chat_session", None)
    lang = session["lang"] if session else "en"
    await query.edit_message_text(gettext(lang, "chat_ended"))
    return ConversationHandler.END


async def chat_end_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session = context.user_data.pop("chat_session", None)
    lang = session["lang"] if session else await db.get_user_language(update.effective_user.id)
    await update.message.reply_text(gettext(lang, "chat_ended"))
    return ConversationHandler.END


chat_conv = ConversationHandler(
    entry_points=[CommandHandler("chat", cmd_chat)],
    states={
        CHAT_CHOOSE_POD: [CallbackQueryHandler(chat_pod_selected, pattern=r"^chat:pod:")],
        CHAT_CHOOSE_EP: [
            CallbackQueryHandler(chat_nav, pattern=r"^chat:nav:"),
            CallbackQueryHandler(chat_ep_selected, pattern=r"^chat:ep:"),
        ],
        CHAT_TALKING: [
            CallbackQueryHandler(chat_end, pattern=r"^chat:end$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, chat_message),
        ],
    },
    fallbacks=[CommandHandler("end", chat_end_command), CommandHandler("chat", cmd_chat)],
    per_message=False,
    per_user=True,
    per_chat=True,
    allow_reentry=True,
)
