"""One-shot backfill: upload all existing episodes (with transcript or summary) to Google Drive."""

import asyncio
import logging

import asyncpg
from dotenv import load_dotenv

from core.config import get_settings
from core.google_drive import upload_episode

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    if not settings.google_service_account_json or not settings.google_drive_folder_id:
        print("ERROR: GOOGLE_SERVICE_ACCOUNT_JSON and GOOGLE_DRIVE_FOLDER_ID must be set in .env")
        return

    pool = await asyncpg.create_pool(settings.database_url)
    try:
        rows = await pool.fetch(
            """
            SELECT
                p.title        AS podcast_title,
                e.episode_guid AS guid,
                e.podcast_id,
                e.title        AS episode_title,
                e.published_at,
                e.transcript,
                ue.summary
            FROM episodes e
            JOIN podcasts p ON p.id = e.podcast_id
            LEFT JOIN user_episodes ue ON ue.episode_id = e.id
            WHERE e.transcript IS NOT NULL OR ue.summary IS NOT NULL
            ORDER BY e.published_at DESC NULLS LAST
            """
        )
    finally:
        await pool.close()

    total = len(rows)
    print(f"Found {total} episodes to upload.")

    uploaded = 0
    skipped = 0
    for row in rows:
        published = row["published_at"].isoformat() if row["published_at"] else None
        file_id = await upload_episode(
            podcast_title=row["podcast_title"],
            episode_title=row["episode_title"] or row["guid"],
            published_at=published,
            summary=row["summary"],
            transcript=row["transcript"],
        )
        if file_id:
            uploaded += 1
            print(f"  [{uploaded}/{total}] Uploaded: {row['podcast_title']} — {row['episode_title']}")
        else:
            skipped += 1
            print(f"  [skip] {row['podcast_title']} — {row['episode_title']}")

    print(f"\nDone. Uploaded: {uploaded}, Skipped/failed: {skipped}")


if __name__ == "__main__":
    asyncio.run(main())
