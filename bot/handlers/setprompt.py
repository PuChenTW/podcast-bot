import html as _html
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot import database as db
from bot.config import settings
from bot.summarizer import generate_prompt_from_description

logger = logging.getLogger(__name__)


async def cmd_setprompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = await db.get_or_create_user(user.id, update.effective_chat.id)
    subs = await db.get_subscriptions(user_id)

    if not subs:
        await update.message.reply_text(
            "No subscriptions yet. Use /subscribe <RSS URL>."
        )
        return

    buttons = [
        [
            InlineKeyboardButton(
                s.podcast_title, callback_data=f"setprompt:pod:{s.id}"
            )
        ]
        for s in subs
    ]
    await update.message.reply_text(
        "Which podcast do you want to customize?",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


def _regen_buttons(subscription_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "確認儲存", callback_data=f"setprompt:confirm:{subscription_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "重新生成", callback_data=f"setprompt:regen:{subscription_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "取消", callback_data=f"setprompt:cancel:{subscription_id}"
                )
            ],
        ]
    )


async def setprompt_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":", 2)
    stage = parts[1]

    if stage == "pod":
        subscription_id = parts[2]
        sub = await db.get_subscription_by_id(subscription_id)
        if sub is None:
            await query.edit_message_text("Subscription not found.")
            return
        current = sub.custom_prompt
        status = (
            f"目前自定義 prompt：\n<code>{_html.escape(current[:80])}...</code>"
            if current
            else "目前使用預設 prompt"
        )
        buttons = [
            [
                InlineKeyboardButton(
                    "手動輸入", callback_data=f"setprompt:manual:{subscription_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "自動生成", callback_data=f"setprompt:auto:{subscription_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "清除自定義 prompt",
                    callback_data=f"setprompt:clear:{subscription_id}",
                )
            ],
        ]
        await query.edit_message_text(
            f"<b>{_html.escape(sub.podcast_title)}</b>\n{status}\n\n選擇操作：",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML",
        )

    elif stage == "manual":
        subscription_id = parts[2]
        context.user_data["setprompt"] = {
            "subscription_id": subscription_id,
            "mode": "manual",
        }
        await query.edit_message_text("請輸入這個 podcast 的 summarize prompt：")

    elif stage == "auto":
        subscription_id = parts[2]
        context.user_data["setprompt"] = {
            "subscription_id": subscription_id,
            "mode": "auto",
        }
        await query.edit_message_text(
            "請簡短描述這個 podcast 的風格或你想要的摘要重點："
        )

    elif stage == "confirm":
        subscription_id = parts[2]
        state = context.user_data.get("setprompt", {})
        prompt = state.get("generated_prompt")
        if not prompt:
            await query.edit_message_text(
                "找不到待確認的 prompt，請重新執行 /setprompt。"
            )
            return
        await db.set_subscription_prompt(subscription_id, prompt)
        context.user_data.pop("setprompt", None)
        await query.edit_message_text("已儲存 ✓")

    elif stage == "regen":
        subscription_id = parts[2]
        state = context.user_data.get("setprompt", {})
        description = state.get("description")
        if not description:
            await query.edit_message_text("找不到描述，請重新執行 /setprompt。")
            return
        await query.edit_message_text("重新生成中...")
        generated = await generate_prompt_from_description(
            description, settings.gemini_model
        )
        context.user_data["setprompt"]["generated_prompt"] = generated
        await query.edit_message_text(
            f"生成的 prompt 草稿：\n\n<code>{_html.escape(generated)}</code>",
            reply_markup=_regen_buttons(subscription_id),
            parse_mode="HTML",
        )

    elif stage == "clear":
        subscription_id = parts[2]
        await db.set_subscription_prompt(subscription_id, None)
        await query.edit_message_text("已還原為預設 prompt ✓")

    elif stage == "cancel":
        context.user_data.pop("setprompt", None)
        await query.edit_message_text("已取消。")


async def setprompt_message_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    state = context.user_data.get("setprompt")
    if state is None:
        return  # not in a setprompt flow

    text = update.message.text.strip()
    subscription_id = state["subscription_id"]
    mode = state["mode"]

    if mode == "manual":
        await db.set_subscription_prompt(subscription_id, text)
        context.user_data.pop("setprompt", None)
        await update.message.reply_text("已儲存 ✓")

    elif mode == "auto":
        state["description"] = text
        msg = await update.message.reply_text("生成中...")
        generated = await generate_prompt_from_description(text, settings.gemini_model)
        state["generated_prompt"] = generated
        await msg.edit_text(
            f"生成的 prompt 草稿：\n\n<code>{_html.escape(generated)}</code>",
            reply_markup=_regen_buttons(subscription_id),
            parse_mode="HTML",
        )
