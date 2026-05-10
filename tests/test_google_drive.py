from unittest.mock import MagicMock, patch

import pytest

import core.config as _config
from core.config import Settings
from core.google_drive import upload_episode


def _make_settings(token_path=None, folder_id=None):
    return Settings(
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
        google_drive_token_path=token_path,
        google_drive_folder_id=folder_id,
    )


def test_settings_drive_fields_optional():
    s = _make_settings()
    assert s.google_drive_token_path is None
    assert s.google_drive_folder_id is None


@pytest.mark.asyncio
async def test_upload_returns_none_when_not_configured(monkeypatch):
    monkeypatch.setattr(_config, "_settings", _make_settings(token_path=None, folder_id=None))
    result = await upload_episode("Pod", "Ep", "2024-01-01", "summary text", "transcript text")
    assert result is None


@pytest.mark.asyncio
async def test_upload_calls_drive_api(monkeypatch):
    monkeypatch.setattr(_config, "_settings", _make_settings(token_path="/fake/token.json", folder_id="folder123"))

    fake_file_id = "file-abc-123"
    mock_service = MagicMock()
    mock_service.files.return_value.create.return_value.execute.return_value = {"id": fake_file_id}

    import core.google_drive as gd_module

    monkeypatch.setattr(gd_module, "_drive_service", None)

    with patch("core.google_drive._build_service", return_value=mock_service):
        result = await upload_episode("Pod", "Ep1", "2024-01-01", "sum", "trans")

    assert result == fake_file_id
    create_kwargs = mock_service.files.return_value.create.call_args.kwargs
    assert create_kwargs["body"]["name"] == "Pod_Ep1.md"
    assert create_kwargs["body"]["parents"] == ["folder123"]
