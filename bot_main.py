import logging
import os

from telegram.ext import (
    Application,
    CommandHandler,
)

from bot.handlers import (
    chat_conv,
    cmd_list,
    cmd_start,
    digest_conv,
    language_callback_handler,
    language_handler,
    notify_conv,
    orphaned_callback_handler,
    setprompt_conv,
    start_lang_handler,
    subscribe_conv,
    transcript_conv,
    unsubscribe_conv,
)
from bot.scheduler import start_scheduler, stop_scheduler
from core.audio_workspace import cleanup_stale_audio_workspaces
from core.config import get_settings
from core.database import close_db, init_db
from core.transcribers import build_transcriber

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("google_genai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def post_init(app: Application) -> None:
    cleanup_stale_audio_workspaces()
    await init_db()
    app.bot_data["transcriber"] = build_transcriber(get_settings())
    await start_scheduler(app)
    await app.bot.set_my_commands(
        [
            ("start", "Show available commands"),
            ("subscribe", "Subscribe to a podcast RSS feed"),
            ("unsubscribe", "Remove a subscription"),
            ("list", "List your subscriptions"),
            ("digest", "Get a summary of a specific episode"),
            ("transcript", "Download raw transcript of an episode"),
            ("chat", "Discuss an episode with AI"),
            ("setprompt", "Customize summarization style per podcast"),
            ("notify", "Toggle Telegram delivery per podcast"),
            ("language", "Set language preference"),
        ]
    )
    logger.info("Bot initialized and ready.")


async def post_shutdown(app: Application) -> None:
    await stop_scheduler()
    await close_db()


def main() -> None:
    # Set Gemini API key for pydantic-ai
    os.environ["GEMINI_API_KEY"] = get_settings().gemini_api_key

    app = Application.builder().token(get_settings().telegram_bot_token).post_init(post_init).post_shutdown(post_shutdown).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(start_lang_handler)
    app.add_handler(subscribe_conv)
    app.add_handler(unsubscribe_conv)
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(digest_conv)
    app.add_handler(transcript_conv)
    app.add_handler(chat_conv)
    app.add_handler(setprompt_conv)
    app.add_handler(notify_conv)
    app.add_handler(language_handler)
    app.add_handler(language_callback_handler)
    app.add_handler(orphaned_callback_handler)  # catch-all: dismiss stale inline keyboard callbacks

    logger.info("Starting bot polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
