import logging
import os

from telegram.ext import (
    Application,
    CommandHandler,
)

from bot.config import settings
from bot.database import init_db
from bot.handlers import (
    cmd_list,
    cmd_start,
    digest_conv,
    setprompt_conv,
    subscribe_conv,
    unsubscribe_conv,
)
from bot.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def post_init(app: Application) -> None:
    await init_db()
    await start_scheduler(app.bot)
    await app.bot.set_my_commands([
        ("start", "Show available commands"),
        ("subscribe", "Subscribe to a podcast RSS feed"),
        ("unsubscribe", "Remove a subscription"),
        ("list", "List your subscriptions"),
        ("digest", "Get a summary of a specific episode"),
        ("setprompt", "Customize summarization style per podcast"),
    ])
    logger.info("Bot initialized and ready.")


async def post_shutdown(app: Application) -> None:
    await stop_scheduler()


def main() -> None:
    # Set Gemini API key for pydantic-ai
    os.environ["GEMINI_API_KEY"] = settings.gemini_api_key

    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(subscribe_conv)
    app.add_handler(unsubscribe_conv)
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(digest_conv)
    app.add_handler(setprompt_conv)

    logger.info("Starting bot polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
