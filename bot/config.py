import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    telegram_bot_token: str
    telegram_chat_id: int
    gemini_api_key: str
    gemini_model: str
    whisper_model: str
    poll_interval_seconds: int
    admin_user_id: int

    @classmethod
    def from_env(cls) -> "Settings":
        missing = []
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        gemini_key = os.getenv("GEMINI_API_KEY")
        admin_user_id = os.getenv("ADMIN_USER_ID")

        if not token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not chat_id:
            missing.append("TELEGRAM_CHAT_ID")
        if not gemini_key:
            missing.append("GEMINI_API_KEY")
        if not admin_user_id:
            missing.append("ADMIN_USER_ID")

        if missing:
            raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")

        return cls(
            telegram_bot_token=token,
            telegram_chat_id=int(chat_id),
            gemini_api_key=gemini_key,
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
            whisper_model=os.getenv("WHISPER_MODEL", "base"),
            poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "21600")),
            admin_user_id=int(admin_user_id),
        )


settings = Settings.from_env()
