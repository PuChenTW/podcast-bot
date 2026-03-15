import logging
import os

from telegram.ext import (
    Application,
    CommandHandler,
)

from bot.config import get_settings
from bot.handlers import (
    chat_conv,
    cmd_list,
    cmd_reload,
    cmd_start,
    digest_conv,
    language_callback_handler,
    language_handler,
    orphaned_callback_handler,
    setprompt_conv,
    start_lang_handler,
    subscribe_conv,
    transcript_conv,
    unsubscribe_conv,
)
from bot.scheduler import start_scheduler, stop_scheduler
from bot.transcribers import AudioPipeline, GroqTranscriber, Transcriber, TranscriberPipeline, WhisperTranscriber
from shared.database import init_db

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("google_genai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def _build_transcriber(s) -> Transcriber:
    if s.transcriber_backend == "groq":
        return TranscriberPipeline([AudioPipeline(GroqTranscriber(s.groq_api_key)), AudioPipeline(WhisperTranscriber(s.whisper_model))])
    return AudioPipeline(WhisperTranscriber(s.whisper_model))


async def post_init(app: Application) -> None:
    await init_db()
    app.bot_data["transcriber"] = _build_transcriber(get_settings())
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
            ("language", "Set language preference"),
            ("reload", "Pull latest code and restart"),
        ]
    )
    logger.info("Bot initialized and ready.")


async def post_shutdown(app: Application) -> None:
    await stop_scheduler()


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
    app.add_handler(language_handler)
    app.add_handler(language_callback_handler)
    app.add_handler(CommandHandler("reload", cmd_reload))
    app.add_handler(orphaned_callback_handler)  # catch-all: dismiss stale inline keyboard callbacks

    logger.info("Starting bot polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
