from core.config import Settings


def test_settings_drive_fields_optional():
    s = Settings(
        telegram_bot_token="t",
        gemini_api_key="g",
        ai_model="m",
        whisper_model="base",
        poll_interval_seconds=21600,
        admin_user_id=1,
        groq_api_key=None,
        transcriber_backend="whisper",
        summarizer_model="m",
        chat_model="m",
        corrector_model="m",
        prompt_engineer_model="m",
        condenser_model="m",
        database_url="postgresql://x",
        google_service_account_json=None,
        google_drive_folder_id=None,
    )
    assert s.google_service_account_json is None
    assert s.google_drive_folder_id is None
