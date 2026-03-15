import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from bot.handlers.callbacks import LangCallback
from bot.i18n import gettext
from shared import database as db

logger = logging.getLogger(__name__)


async def cmd_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    lang = await db.get_user_language(user.id)

    # Check if they exist in DB, if not create them
    await db.get_or_create_user(user.id, update.effective_chat.id)

    msg = gettext(lang, "language_prompt")

    buttons = [
        [
            InlineKeyboardButton("English", callback_data=LangCallback(lang="en").serialize()),
            InlineKeyboardButton("繁體中文", callback_data=LangCallback(lang="zh-tw").serialize()),
        ]
    ]

    await update.message.reply_text(
        msg,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def lang_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    selected_lang = LangCallback.parse(query.data).lang
    user = update.effective_user

    await db.set_user_language(user.id, selected_lang)

    msg = gettext(selected_lang, "language_set")
    await query.edit_message_text(msg)


language_handler = CommandHandler("language", cmd_language)
language_callback_handler = CallbackQueryHandler(lang_selected, pattern=r"^lang:(en|zh-tw)$")
