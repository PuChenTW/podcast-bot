"""`/notify` — toggle Telegram delivery per podcast.

Muting a subscription only stops the push: the scheduler keeps downloading,
transcribing and summarizing new episodes, which stay readable in the web UI.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler

from bot.handlers.callbacks import NotifyCallback
from bot.i18n import gettext
from core import database as db

NOTIFY_CHOOSE_POD = 0


def _build_keyboard(subs, lang: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                gettext(lang, "notify_on_label" if s.telegram_delivery else "notify_off_label", title=s.podcast_title),
                callback_data=NotifyCallback(subscription_id=s.id).serialize(),
            )
        ]
        for s in subs
    ]
    buttons.append(
        [
            InlineKeyboardButton(
                gettext(lang, "cancel_btn"),
                callback_data=NotifyCallback(subscription_id=None).serialize(),
            )
        ]
    )
    return InlineKeyboardMarkup(buttons)


async def cmd_notify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    lang = await db.get_user_language(user.id)
    user_id = await db.get_or_create_user(user.id, update.effective_chat.id)
    subs = await db.get_subscriptions(user_id)

    if not subs:
        await update.message.reply_text(gettext(lang, "no_subscriptions"))
        return ConversationHandler.END

    await update.message.reply_text(
        gettext(lang, "notify_choose"),
        reply_markup=_build_keyboard(subs, lang),
    )
    return NOTIFY_CHOOSE_POD


async def notify_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = await db.get_user_language(user.id)
    target = NotifyCallback.parse(query.data).subscription_id

    sub = await db.get_subscription_by_id(target)
    if sub is None:
        await query.edit_message_text(gettext(lang, "sub_not_found"))
        return ConversationHandler.END

    enabled = not sub.telegram_delivery
    await db.set_subscription_telegram_delivery(sub.id, enabled)

    user_id = await db.get_or_create_user(user.id, update.effective_chat.id)
    subs = await db.get_subscriptions(user_id)
    status = gettext(lang, "notify_enabled" if enabled else "notify_disabled", title=sub.podcast_title)
    await query.edit_message_text(
        f"{status}\n\n{gettext(lang, 'notify_choose')}",
        reply_markup=_build_keyboard(subs, lang),
    )
    return NOTIFY_CHOOSE_POD


async def notify_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    user = update.effective_user
    lang = await db.get_user_language(user.id)
    await query.answer()
    await query.edit_message_text(gettext(lang, "notify_done"))
    return ConversationHandler.END


notify_conv = ConversationHandler(
    entry_points=[CommandHandler("notify", cmd_notify)],
    states={
        NOTIFY_CHOOSE_POD: [
            CallbackQueryHandler(notify_selected, pattern=r"^notify:(?!cancel)"),
            CallbackQueryHandler(notify_cancel, pattern=r"^notify:cancel"),
        ],
    },
    fallbacks=[CommandHandler("notify", cmd_notify)],
    per_user=True,
    per_chat=True,
    allow_reentry=True,
)
