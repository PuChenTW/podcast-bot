import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from bot import database as db
from bot.feed import fetch_feed, parse_podcast_title, resolve_rss_url

logger = logging.getLogger(__name__)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Podcast Bot\n\n"
        "/subscribe — subscribe to a podcast\n"
        "/unsubscribe — remove a subscription\n"
        "/list — show your subscriptions\n"
        "/digest — get a summary of a specific episode\n"
        "/setprompt — customize summarization style per podcast"
    )


async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("setprompt", None)
    context.user_data["subscribe"] = {"awaiting_url": True}
    await update.message.reply_text("請輸入 RSS feed 網址或 Apple Podcasts 連結：")


async def subscribe_message_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    state = context.user_data.get("subscribe")
    if not state or not state.get("awaiting_url"):
        return

    raw_url = update.message.text.strip()
    context.user_data.pop("subscribe", None)

    user = update.effective_user
    chat_id = update.effective_chat.id

    msg = await update.message.reply_text("Fetching feed...")

    try:
        rss_url = await resolve_rss_url(raw_url)
    except ValueError as exc:
        await msg.edit_text(str(exc))
        raise ApplicationHandlerStop

    try:
        parsed = await fetch_feed(rss_url)
    except Exception as exc:
        logger.error("Feed fetch error: %s", exc)
        await msg.edit_text("Could not fetch feed. Check the URL and try again.")
        raise ApplicationHandlerStop

    if parsed.bozo and not parsed.entries:
        await msg.edit_text("Invalid RSS feed. Check the URL and try again.")
        raise ApplicationHandlerStop

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
    raise ApplicationHandlerStop


async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = await db.get_or_create_user(user.id, update.effective_chat.id)
    subs = await db.get_subscriptions(user_id)

    if not subs:
        await update.message.reply_text("No subscriptions yet.")
        return

    buttons = [
        [InlineKeyboardButton(s.podcast_title, callback_data=f"unsub:{s.id}")]
        for s in subs
    ]
    buttons.append(
        [InlineKeyboardButton("取消", callback_data="unsub:cancel")]
    )
    await update.message.reply_text(
        "選擇要取消訂閱的 podcast：",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def unsubscribe_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":", 1)
    target = parts[1]

    if target == "cancel":
        await query.edit_message_text("已取消。")
        return

    sub = await db.get_subscription_by_id(target)
    if sub is None:
        await query.edit_message_text("Subscription not found.")
        return

    await db.remove_subscription_by_id(target)
    await query.edit_message_text(f'已取消訂閱「{sub.podcast_title}」。')


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = await db.get_or_create_user(user.id, update.effective_chat.id)
    subs = await db.get_subscriptions(user_id)

    if not subs:
        await update.message.reply_text(
            "No subscriptions yet. Use /subscribe."
        )
        return

    lines = [f"{i + 1}. {s.podcast_title}" for i, s in enumerate(subs)]
    await update.message.reply_text("Your subscriptions:\n" + "\n".join(lines))
