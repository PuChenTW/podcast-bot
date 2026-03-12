import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot import database as db
from bot.feed import fetch_feed, parse_podcast_title

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

    lines = [f"{i + 1}. {s.podcast_title}" for i, s in enumerate(subs)]
    await update.message.reply_text("Your subscriptions:\n" + "\n".join(lines))
