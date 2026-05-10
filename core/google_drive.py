import asyncio
import io
import logging
import re
import threading

from core.config import get_settings

logger = logging.getLogger(__name__)

_drive_service = None
_lock = threading.Lock()
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _safe_filename(podcast: str, episode: str) -> str:
    def _clean(s: str) -> str:
        return _UNSAFE.sub("", s).strip().replace(" ", "_")[:50]

    return f"{_clean(podcast)}_{_clean(episode)}.md"


def _build_markdown(podcast_title: str, episode_title: str, published_at: str | None, summary: str | None, transcript: str | None) -> str:
    summary_section = summary or "(not yet generated)"
    transcript_section = transcript or "(not available)"
    return f"# {episode_title}\n**Podcast:** {podcast_title}\n**Published:** {published_at or 'Unknown'}\n\n## Summary\n{summary_section}\n\n## Transcript\n{transcript_section}\n"


def _build_service(token_path: str):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(token_path, _SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    return build("drive", "v3", credentials=creds)


def _get_service():
    global _drive_service
    settings = get_settings()
    with _lock:
        if _drive_service is None and settings.google_drive_token_path:
            _drive_service = _build_service(settings.google_drive_token_path)
    return _drive_service


async def upload_episode(
    podcast_title: str,
    episode_title: str,
    published_at: str | None,
    summary: str | None,
    transcript: str | None,
) -> str | None:
    settings = get_settings()
    if not settings.google_drive_token_path or not settings.google_drive_folder_id:
        return None

    filename = _safe_filename(podcast_title, episode_title)
    content = _build_markdown(podcast_title, episode_title, published_at, summary, transcript)

    def _upload() -> str:
        service = _get_service()
        from googleapiclient.http import MediaIoBaseUpload

        media = MediaIoBaseUpload(
            io.BytesIO(content.encode("utf-8")),
            mimetype="text/markdown",
            resumable=False,
        )
        file_meta = {
            "name": filename,
            "parents": [settings.google_drive_folder_id],
            "mimeType": "text/markdown",
        }
        result = service.files().create(body=file_meta, media_body=media, fields="id").execute()
        return result["id"]

    try:
        file_id = await asyncio.get_running_loop().run_in_executor(None, _upload)
        logger.info("Uploaded %s to Drive: %s", filename, file_id)
        return file_id
    except Exception as exc:
        logger.error("Drive upload failed for %s/%s: %s", podcast_title, episode_title, exc)
        return None
