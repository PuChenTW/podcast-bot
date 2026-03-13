import html as _html
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
from bot.handlers.callbacks import SetpromptActionCallback, SetpromptPodCallback
from bot.config import settings
from bot.i18n import gettext
from bot.summarizer import generate_prompt_from_description, refine_prompt

logger = logging.getLogger(__name__)

SETPROMPT_CHOOSE_POD = 0
SETPROMPT_CHOOSE_MODE = 1
SETPROMPT_MANUAL_INPUT = 2
SETPROMPT_AUTO_INPUT = 3
SETPROMPT_AUTO_REVIEW = 4
SETPROMPT_REFINE = 5


def _regen_buttons(subscription_id: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    gettext(lang, "action_accept"), callback_data=SetpromptActionCallback(action="confirm", subscription_id=subscription_id).serialize()
                )
            ],
            [
                InlineKeyboardButton(
                    gettext(lang, "action_refine"), callback_data=SetpromptActionCallback(action="refine", subscription_id=subscription_id).serialize()
                )
            ],
            [
                InlineKeyboardButton(
                    gettext(lang, "action_retry"), callback_data=SetpromptActionCallback(action="regen", subscription_id=subscription_id).serialize()
                )
            ],
            [
                InlineKeyboardButton(
                    gettext(lang, "cancel_btn"), callback_data=SetpromptActionCallback(action="cancel", subscription_id=subscription_id).serialize()
                )
            ],
        ]
    )


def _refine_review_buttons(subscription_id: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    gettext(lang, "action_refine_save"), callback_data=SetpromptActionCallback(action="refine_save", subscription_id=subscription_id).serialize()
                )
            ],
            [
                InlineKeyboardButton(
                    gettext(lang, "action_refine_more"), callback_data=SetpromptActionCallback(action="refine_more", subscription_id=subscription_id).serialize()
                )
            ],
            [
                InlineKeyboardButton(
                    gettext(lang, "cancel_btn"), callback_data=SetpromptActionCallback(action="cancel", subscription_id=subscription_id).serialize()
                )
            ],
        ]
    )


async def cmd_setprompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    lang = await db.get_user_language(user.id)
    user_id = await db.get_or_create_user(user.id, update.effective_chat.id)
    subs = await db.get_subscriptions(user_id)

    if not subs:
        await update.message.reply_text(gettext(lang, "no_subs_please_subscribe"))
        return ConversationHandler.END

    buttons = [
        [
            InlineKeyboardButton(
                s.podcast_title, callback_data=SetpromptPodCallback(subscription_id=s.id).serialize()
            )
        ]
        for s in subs
    ]
    await update.message.reply_text(
        gettext(lang, "setprompt_intro"),
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return SETPROMPT_CHOOSE_POD


async def setprompt_pod_selected(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = await db.get_user_language(user.id)
    subscription_id = SetpromptPodCallback.parse(query.data).subscription_id

    sub = await db.get_subscription_by_id(subscription_id)
    if sub is None:
        await query.edit_message_text(gettext(lang, "sub_not_found"))
        return ConversationHandler.END

    current = sub.custom_prompt
    status = (
        gettext(lang, "setprompt_choose_action", title=sub.podcast_title, prompt=_html.escape(current[:80]) + "...")
        if current
        else gettext(lang, "setprompt_no_prompt", title=sub.podcast_title)
    )
    buttons = [
        [
            InlineKeyboardButton(
                gettext(lang, "action_manual"), callback_data=SetpromptActionCallback(action="manual", subscription_id=subscription_id).serialize()
            )
        ],
        [
            InlineKeyboardButton(
                gettext(lang, "action_auto"), callback_data=SetpromptActionCallback(action="auto", subscription_id=subscription_id).serialize()
            )
        ],
    ]
    if current:
        buttons.append([
            InlineKeyboardButton(
                gettext(lang, "action_refine_existing"), callback_data=SetpromptActionCallback(action="refine", subscription_id=subscription_id).serialize()
            )
        ])
    buttons.append([
        InlineKeyboardButton(
            gettext(lang, "action_reset"), callback_data=SetpromptActionCallback(action="clear", subscription_id=subscription_id).serialize(),
        )
    ])
    await query.edit_message_text(
        f"<b>{_html.escape(sub.podcast_title)}</b>\n{status}",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )
    return SETPROMPT_CHOOSE_MODE


async def setprompt_mode_manual(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = await db.get_user_language(user.id)
    subscription_id = SetpromptActionCallback.parse(query.data).subscription_id

    context.user_data["setprompt"] = {"subscription_id": subscription_id}
    await query.edit_message_text(gettext(lang, "prompt_input_request"))
    return SETPROMPT_MANUAL_INPUT


async def setprompt_mode_auto(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = await db.get_user_language(user.id)
    subscription_id = SetpromptActionCallback.parse(query.data).subscription_id

    context.user_data["setprompt"] = {"subscription_id": subscription_id}
    await query.edit_message_text(gettext(lang, "prompt_auto_request"))
    return SETPROMPT_AUTO_INPUT


async def setprompt_clear(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = await db.get_user_language(user.id)
    subscription_id = SetpromptActionCallback.parse(query.data).subscription_id

    await db.set_subscription_prompt(subscription_id, None)
    await query.edit_message_text(gettext(lang, "prompt_reset"))
    return ConversationHandler.END


async def setprompt_enter_refine(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = await db.get_user_language(user.id)
    subscription_id = SetpromptActionCallback.parse(query.data).subscription_id

    # Prefer in-flight generated_prompt (coming from AUTO_REVIEW); fall back to DB
    current_prompt = context.user_data.get("setprompt", {}).get("generated_prompt")
    if not current_prompt:
        sub = await db.get_subscription_by_id(subscription_id)
        if sub is None or not sub.custom_prompt:
            await query.edit_message_text(gettext(lang, "sub_not_found"))
            return ConversationHandler.END
        current_prompt = sub.custom_prompt

    context.user_data.setdefault("setprompt", {}).update({
        "subscription_id": subscription_id,
        "generated_prompt": current_prompt,
    })
    await query.edit_message_text(
        gettext(lang, "refine_enter", prompt=_html.escape(current_prompt)),
        parse_mode="HTML",
    )
    return SETPROMPT_REFINE


async def setprompt_refine_apply(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    lang = await db.get_user_language(user.id)
    instruction = update.message.text.strip()
    if not instruction:
        await update.message.reply_text(gettext(lang, "prompt_input_request"))
        return SETPROMPT_REFINE
    setprompt_data = context.user_data.get("setprompt", {})
    current_prompt = setprompt_data.get("generated_prompt")
    subscription_id = setprompt_data.get("subscription_id")

    if not current_prompt or not subscription_id:
        await update.message.reply_text(gettext(lang, "prompt_not_found"))
        return ConversationHandler.END

    msg = await update.message.reply_text(gettext(lang, "refining"))
    refined = await refine_prompt(current_prompt, instruction, settings.gemini_model)
    context.user_data["setprompt"]["generated_prompt"] = refined

    await msg.edit_text(
        gettext(lang, "generated_preview", prompt=_html.escape(refined)),
        reply_markup=_refine_review_buttons(subscription_id, lang),
        parse_mode="HTML",
    )
    return SETPROMPT_REFINE


async def setprompt_refine_save(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = await db.get_user_language(user.id)
    subscription_id = SetpromptActionCallback.parse(query.data).subscription_id
    prompt = context.user_data.get("setprompt", {}).get("generated_prompt")

    if not prompt:
        await query.edit_message_text(gettext(lang, "prompt_not_found"))
        return ConversationHandler.END

    await db.set_subscription_prompt(subscription_id, prompt)
    context.user_data.pop("setprompt", None)
    await query.edit_message_text(gettext(lang, "prompt_saved"))
    return ConversationHandler.END


async def setprompt_refine_continue(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = await db.get_user_language(user.id)
    setprompt_data = context.user_data.get("setprompt", {})
    current_prompt = setprompt_data.get("generated_prompt")
    subscription_id = setprompt_data.get("subscription_id")

    if not current_prompt or not subscription_id:
        await query.edit_message_text(gettext(lang, "prompt_not_found"))
        return ConversationHandler.END

    await query.edit_message_text(
        gettext(lang, "refine_enter", prompt=_html.escape(current_prompt)),
        parse_mode="HTML",
    )
    return SETPROMPT_REFINE


async def setprompt_save_manual(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    lang = await db.get_user_language(user.id)
    text = update.message.text.strip()
    subscription_id = context.user_data["setprompt"]["subscription_id"]

    await db.set_subscription_prompt(subscription_id, text)
    context.user_data.pop("setprompt", None)
    await update.message.reply_text(gettext(lang, "prompt_saved"))
    return ConversationHandler.END


async def setprompt_generate_auto(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    lang = await db.get_user_language(user.id)
    text = update.message.text.strip()
    subscription_id = context.user_data["setprompt"]["subscription_id"]
    context.user_data["setprompt"]["description"] = text

    msg = await update.message.reply_text(gettext(lang, "generating"))
    generated = await generate_prompt_from_description(text, settings.gemini_model)
    context.user_data["setprompt"]["generated_prompt"] = generated

    await msg.edit_text(
        gettext(lang, "generated_preview", prompt=_html.escape(generated)),
        reply_markup=_regen_buttons(subscription_id, lang),
        parse_mode="HTML",
    )
    return SETPROMPT_AUTO_REVIEW


async def setprompt_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = await db.get_user_language(user.id)
    subscription_id = SetpromptActionCallback.parse(query.data).subscription_id
    prompt = context.user_data.get("setprompt", {}).get("generated_prompt")

    if not prompt:
        await query.edit_message_text(gettext(lang, "prompt_not_found"))
        return ConversationHandler.END

    await db.set_subscription_prompt(subscription_id, prompt)
    context.user_data.pop("setprompt", None)
    await query.edit_message_text(gettext(lang, "prompt_saved"))
    return ConversationHandler.END


async def setprompt_regen(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = await db.get_user_language(user.id)
    subscription_id = SetpromptActionCallback.parse(query.data).subscription_id
    description = context.user_data.get("setprompt", {}).get("description")

    if not description:
        await query.edit_message_text(gettext(lang, "generate_error"))
        return ConversationHandler.END

    await query.edit_message_text(gettext(lang, "regenerating"))
    generated = await generate_prompt_from_description(
        description, settings.gemini_model
    )
    context.user_data["setprompt"]["generated_prompt"] = generated

    await query.edit_message_text(
        gettext(lang, "generated_preview", prompt=_html.escape(generated)),
        reply_markup=_regen_buttons(subscription_id, lang),
        parse_mode="HTML",
    )
    return SETPROMPT_AUTO_REVIEW


async def setprompt_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = await db.get_user_language(user.id)
    context.user_data.pop("setprompt", None)
    await query.edit_message_text(gettext(lang, "canceled"))
    return ConversationHandler.END


setprompt_conv = ConversationHandler(
    entry_points=[CommandHandler("setprompt", cmd_setprompt)],
    per_message=False,
    states={
        SETPROMPT_CHOOSE_POD: [
            CallbackQueryHandler(setprompt_pod_selected, pattern=r"^setprompt:pod:"),
        ],
        SETPROMPT_CHOOSE_MODE: [
            CallbackQueryHandler(setprompt_mode_manual, pattern=r"^setprompt:manual:"),
            CallbackQueryHandler(setprompt_mode_auto, pattern=r"^setprompt:auto:"),
            CallbackQueryHandler(setprompt_clear, pattern=r"^setprompt:clear:"),
            CallbackQueryHandler(setprompt_enter_refine, pattern=r"^setprompt:refine:"),
        ],
        SETPROMPT_MANUAL_INPUT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, setprompt_save_manual),
        ],
        SETPROMPT_AUTO_INPUT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, setprompt_generate_auto),
        ],
        SETPROMPT_AUTO_REVIEW: [
            CallbackQueryHandler(setprompt_confirm, pattern=r"^setprompt:confirm:"),
            CallbackQueryHandler(setprompt_regen, pattern=r"^setprompt:regen:"),
            CallbackQueryHandler(setprompt_cancel, pattern=r"^setprompt:cancel:"),
            CallbackQueryHandler(setprompt_enter_refine, pattern=r"^setprompt:refine:"),
        ],
        SETPROMPT_REFINE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, setprompt_refine_apply),
            CallbackQueryHandler(setprompt_refine_save, pattern=r"^setprompt:refine_save:"),
            CallbackQueryHandler(setprompt_refine_continue, pattern=r"^setprompt:refine_more:"),
            CallbackQueryHandler(setprompt_cancel, pattern=r"^setprompt:cancel:"),
        ],
    },
    fallbacks=[
        CommandHandler("setprompt", cmd_setprompt),
        CallbackQueryHandler(setprompt_cancel, pattern=r"^setprompt:cancel:"),
    ],
    per_user=True,
    per_chat=True,
    allow_reentry=True,
)
