import asyncio
import logging

from apscheduler import AsyncScheduler
from apscheduler.triggers.interval import IntervalTrigger
from telegram import Bot

from bot import database as db
from bot.config import settings
from bot.feed import fetch_new_episodes
from bot.formatting import format_summary
from bot.summarizer import summarize_episode

logger = logging.getLogger(__name__)

_scheduler: AsyncScheduler | None = None


async def poll_all_feeds(bot: Bot) -> None:
    logger.info("Polling all feeds...")
    subscriptions = await db.get_all_subscriptions()

    for sub in subscriptions:
        try:
            new_episodes = await fetch_new_episodes(
                sub.id,
                sub.rss_url,
                db.is_episode_seen,
                whisper_model=settings.whisper_model,
                podcast_title=sub.podcast_title,
                gemini_model=settings.gemini_model,
            )
        except Exception as exc:
            logger.error("Error fetching feed %s: %s", sub.rss_url, exc)
            continue

        chat_id = sub.chat_id  # capture before loop to avoid closure bug
        for episode in new_episodes:
            try:
                summary = await summarize_episode(
                    episode.title,
                    episode.content,
                    settings.gemini_model,
                    custom_prompt=sub.custom_prompt,
                )
                text = format_summary(sub.podcast_title, episode.title, summary)
                await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
                await db.mark_episode_seen(
                    sub.id,
                    episode.guid,
                    title=episode.title,
                    published_at=episode.published,
                    summary=summary,
                    transcript=episode.content,
                )
            except Exception as exc:
                logger.error("Error processing episode %s: %s", episode.title, exc)
                # Still mark as seen to avoid retrying broken episodes indefinitely
                await db.mark_episode_seen(sub.id, episode.guid, title=episode.title)

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


async def stop_scheduler() -> None:
    if _scheduler is not None:
        await _scheduler.stop()
