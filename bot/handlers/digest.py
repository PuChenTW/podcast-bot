import html as _html
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot import database as db
from bot.config import settings
from bot.feed import fetch_feed_entries, get_episode_content
from bot.formatting import format_summary, send_html
from bot.summarizer import summarize_episode

logger = logging.getLogger(__name__)


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
                sub.podcast_title, callback_data=f"digest:pod:{sub.id}"
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

        entries = await fetch_feed_entries(sub.rss_url, limit=5)
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
                "podcast_title": sub.podcast_title,
                "custom_prompt": sub.custom_prompt,
            }
            for e in entries
        ]
        await query.edit_message_text(
            f"<b>{_html.escape(sub.podcast_title)}</b> — pick an episode:",
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
            text = format_summary(ep["podcast_title"], ep["title"], summary)
            await send_html(query.message.reply_text, text)
        except Exception as exc:
            logger.error("digest summarize error: %s", exc)
            await query.message.reply_text(
                "Error generating summary. Please try again."
            )
