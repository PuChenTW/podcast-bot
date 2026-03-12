import asyncio
import html as _html
import logging
import re

from apscheduler import AsyncScheduler
from apscheduler.triggers.interval import IntervalTrigger
from telegram import Bot

from bot import database as db
from bot.config import settings
from bot.feed import fetch_new_episodes
from bot.summarizer import summarize_episode

logger = logging.getLogger(__name__)

_scheduler: AsyncScheduler | None = None


def markdown_to_html(text: str) -> str:
    """Convert Gemini-emitted Markdown to Telegram HTML."""
    # 1. Escape HTML special chars first, before inserting any tags
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 2. Fenced code blocks (``` ... ```) — before inline `code`
    text = re.sub(
        r"```(?:\w+\n)?(.*?)```",
        lambda m: f"<pre>{m.group(1).strip()}</pre>",
        text,
        flags=re.DOTALL,
    )

    # 3. Inline code
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)

    # 4. Bold (**text**) — before italic so ** isn't consumed as two *
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

    # 5. Italic (*text* or _text_)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<i>\1</i>", text)

    # 6. ATX headers (# through ######) → <b>
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # 7. Horizontal rules — strip entirely
    text = re.sub(r"^\s*---+\s*$", "", text, flags=re.MULTILINE)

    # 8. Leading - or * bullets → •
    text = re.sub(r"^[ \t]*[-*]\s+", "• ", text, flags=re.MULTILINE)

    # Clean up excess blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def _format_summary(podcast_title: str, episode_title: str, summary: str) -> str:
    title_safe = _html.escape(podcast_title)
    ep_safe = _html.escape(episode_title)
    body = markdown_to_html(summary)
    return f"<b>{title_safe}</b>\n<i>{ep_safe}</i>\n\n{body}"


async def send_html(send_fn, text: str, **kwargs) -> None:
    """Send a Telegram message with HTML parse mode."""
    await send_fn(text, parse_mode="HTML", **kwargs)


async def poll_all_feeds(bot: Bot) -> None:
    logger.info("Polling all feeds...")
    subscriptions = await db.get_all_subscriptions()

    for sub in subscriptions:
        try:
            new_episodes = await fetch_new_episodes(
                sub["id"],
                sub["rss_url"],
                db.is_episode_seen,
                whisper_model=settings.whisper_model,
                podcast_title=sub["podcast_title"],
                gemini_model=settings.gemini_model,
            )
        except Exception as exc:
            logger.error("Error fetching feed %s: %s", sub["rss_url"], exc)
            continue

        for episode in new_episodes:
            try:
                summary = await summarize_episode(
                    episode.title,
                    episode.content,
                    settings.gemini_model,
                    custom_prompt=sub.get("custom_prompt"),
                )
                text = _format_summary(sub["podcast_title"], episode.title, summary)
                await send_html(
                    lambda t, **kw: bot.send_message(
                        chat_id=sub["chat_id"], text=t, **kw
                    ),
                    text,
                )
                await db.mark_episode_seen(
                    sub["id"],
                    episode.guid,
                    title=episode.title,
                    published_at=episode.published,
                    summary=summary,
                    transcript=episode.content,
                )
            except Exception as exc:
                logger.error("Error processing episode %s: %s", episode.title, exc)
                # Still mark as seen to avoid retrying broken episodes indefinitely
                await db.mark_episode_seen(sub["id"], episode.guid, title=episode.title)

            await asyncio.sleep(1)  # Telegram rate limit


async def start_scheduler(bot: Bot) -> None:
    global _scheduler
    _scheduler = AsyncScheduler()
    await _scheduler.__aenter__()
    await _scheduler.add_schedule(
        poll_all_feeds,
        IntervalTrigger(seconds=settings.poll_interval_seconds),
        kwargs={"bot": bot},
        id="poll_feeds",
    )
    await _scheduler.start_in_background()
    logger.info("Scheduler started, interval=%ds", settings.poll_interval_seconds)
