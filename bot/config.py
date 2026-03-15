import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    telegram_bot_token: str
    gemini_api_key: str
    ai_model: str
    whisper_model: str
    poll_interval_seconds: int
    admin_user_id: int
    groq_api_key: str | None
    transcriber_backend: str
    summarizer_model: str
    chat_model: str
    corrector_model: str
    prompt_engineer_model: str
    condenser_model: str

    @classmethod
    def from_env(cls) -> "Settings":
        missing = []
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        gemini_key = os.getenv("GEMINI_API_KEY")
        admin_user_id = os.getenv("ADMIN_USER_ID")

        if not token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not gemini_key:
            missing.append("GEMINI_API_KEY")
        if not admin_user_id:
            missing.append("ADMIN_USER_ID")

        if missing:
            raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")

        groq_api_key = os.getenv("GROQ_API_KEY")
        transcriber_backend = os.getenv("TRANSCRIBER", "whisper").lower()

        if transcriber_backend not in ("whisper", "groq"):
            raise RuntimeError(f"Invalid TRANSCRIBER value '{transcriber_backend}': must be 'whisper' or 'groq'")
        if transcriber_backend == "groq" and not groq_api_key:
            raise RuntimeError("GROQ_API_KEY is required when TRANSCRIBER=groq")

        base = os.getenv("AI_MODEL", "google-gla:gemini-flash-lite-latest")
        return cls(
            telegram_bot_token=token,
            gemini_api_key=gemini_key,
            ai_model=base,
            whisper_model=os.getenv("WHISPER_MODEL", "base"),
            poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "21600")),
            admin_user_id=int(admin_user_id),
            groq_api_key=groq_api_key,
            transcriber_backend=transcriber_backend,
            summarizer_model=os.getenv("SUMMARIZER_MODEL", base),
            chat_model=os.getenv("CHAT_MODEL", base),
            corrector_model=os.getenv("CORRECTOR_MODEL", base),
            prompt_engineer_model=os.getenv("PROMPT_ENGINEER_MODEL", base),
            condenser_model=os.getenv("CONDENSER_MODEL", base),
        )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings
