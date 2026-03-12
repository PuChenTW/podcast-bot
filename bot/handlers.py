import html as _html
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot import database as db
from bot.config import settings
from bot.feed import (
    fetch_feed,
    fetch_feed_entries,
    get_episode_content,
    parse_podcast_title,
)
from bot.scheduler import _format_summary, send_html
from bot.summarizer import generate_prompt_from_description, summarize_episode

logger = logging.getLogger(__name__)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Podcast Bot\n\n"
        "/subscribe <RSS URL> — subscribe to a podcast\n"
        "/unsubscribe <name> — remove a subscription\n"
        "/list — show your subscriptions\n"
        "/digest — get a summary of a specific episode\n"
        "/setprompt — customize summarization style per podcast"
    )


async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /subscribe <RSS URL>")
        return

    rss_url = context.args[0].strip()
    user = update.effective_user
    chat_id = update.effective_chat.id

    msg = await update.message.reply_text("Fetching feed...")

    try:
        parsed = await fetch_feed(rss_url)
    except Exception as exc:
        logger.error("Feed fetch error: %s", exc)
        await msg.edit_text("Could not fetch feed. Check the URL and try again.")
        return

    if parsed.bozo and not parsed.entries:
        await msg.edit_text("Invalid RSS feed. Check the URL and try again.")
        return

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

    await msg.edit_text(f'Subscribed to "{title}". Future episodes will be summarized.')


async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /unsubscribe <podcast name>")
        return

    name = " ".join(context.args).strip()
    user = update.effective_user
    user_id = await db.get_or_create_user(user.id, update.effective_chat.id)

    removed = await db.remove_subscription(user_id, name)
    if removed:
        await update.message.reply_text(f'Unsubscribed from "{name}".')
    else:
        await update.message.reply_text(f'No subscription matching "{name}" found.')


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = await db.get_or_create_user(user.id, update.effective_chat.id)
    subs = await db.get_subscriptions(user_id)

    if not subs:
        await update.message.reply_text(
            "No subscriptions yet. Use /subscribe <RSS URL>."
        )
        return

    lines = [f"{i + 1}. {s['podcast_title']}" for i, s in enumerate(subs)]
    await update.message.reply_text("Your subscriptions:\n" + "\n".join(lines))


async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = update.effective_chat.id
    db_user_id = await db.get_or_create_user(user.id, chat_id)
    subscriptions = await db.get_subscriptions(db_user_id)

    if not subscriptions:
        await update.message.reply_text(
            "No subscriptions yet. Use /subscribe <rss_url>."
        )
        return

    buttons = [
        [
            InlineKeyboardButton(
                sub["podcast_title"], callback_data=f"digest:pod:{sub['id']}"
            )
        ]
        for sub in subscriptions
    ]
    await update.message.reply_text(
        "Which podcast?", reply_markup=InlineKeyboardMarkup(buttons)
    )


async def digest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    parts = data.split(":")
    stage = parts[1]

    if stage == "pod":
        subscription_id = parts[2]
        sub = await db.get_subscription_by_id(subscription_id)
        if sub is None:
            await query.edit_message_text("Subscription not found.")
            return

        entries = await fetch_feed_entries(sub["rss_url"], limit=5)
        if not entries:
            await query.edit_message_text("No episodes found in this feed.")
            return

        buttons = [
            [
                InlineKeyboardButton(
                    (e.get("title") or "Untitled")[:60],
                    callback_data=f"digest:ep:{subscription_id}:{i}",
                )
            ]
            for i, e in enumerate(entries)
        ]
        context.bot_data[f"digest_eps_{subscription_id}"] = [
            {
                "title": e.get("title") or "Untitled",
                "entry": {**dict(e), "enclosures": list(e.get("enclosures", []))},
                "podcast_title": sub["podcast_title"],
                "custom_prompt": sub.get("custom_prompt"),
            }
            for e in entries
        ]
        await query.edit_message_text(
            f"<b>{_html.escape(sub['podcast_title'])}</b> — pick an episode:",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML",
        )

    elif stage == "ep":
        subscription_id = parts[2]
        episode_index = int(parts[3])
        ep_data = context.bot_data.get(f"digest_eps_{subscription_id}", [])

        if not ep_data or episode_index >= len(ep_data):
            await query.edit_message_text("Episode data expired. Run /digest again.")
            return

        ep = ep_data[episode_index]
        guid = (
            ep["entry"].get("id")
            or ep["entry"].get("link")
            or ep["entry"].get("title", "")
        )
        existing_transcript = await db.get_episode_transcript(subscription_id, guid)

        await query.edit_message_text(
            f"{'Summarizing' if existing_transcript else 'Transcribing &amp; summarizing'} <i>{_html.escape(ep['title'])}</i>…",
            parse_mode="HTML",
        )

        try:
            if existing_transcript:
                content = existing_transcript
            else:
                content = await get_episode_content(
                    ep["entry"],
                    settings.whisper_model,
                    podcast_title=ep["podcast_title"],
                    gemini_model=settings.gemini_model,
                )
            summary = await summarize_episode(
                ep["title"],
                content,
                settings.gemini_model,
                custom_prompt=ep.get("custom_prompt"),
            )
            published_at = ep["entry"].get("published")
            await db.mark_episode_seen(
                subscription_id,
                guid,
                title=ep["title"],
                published_at=published_at,
                summary=summary,
                transcript=content,
            )
            text = _format_summary(ep["podcast_title"], ep["title"], summary)
            await send_html(query.message.reply_text, text)
        except Exception as exc:
            logger.error("digest summarize error: %s", exc)
            await query.message.reply_text(
                "Error generating summary. Please try again."
            )


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
                s["podcast_title"], callback_data=f"setprompt:pod:{s['id']}"
            )
        ]
        for s in subs
    ]
    await update.message.reply_text(
        "Which podcast do you want to customize?",
        reply_markup=InlineKeyboardMarkup(buttons),
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
        current = sub.get("custom_prompt")
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
            f"<b>{_html.escape(sub['podcast_title'])}</b>\n{status}\n\n選擇操作：",
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
        buttons = [
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
        await query.edit_message_text(
            f"生成的 prompt 草稿：\n\n<code>{_html.escape(generated)}</code>",
            reply_markup=InlineKeyboardMarkup(buttons),
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
        buttons = [
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
        await msg.edit_text(
            f"生成的 prompt 草稿：\n\n<code>{_html.escape(generated)}</code>",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML",
        )
