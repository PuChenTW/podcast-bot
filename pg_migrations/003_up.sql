ALTER TABLE episodes ADD COLUMN transcript_source TEXT CHECK (transcript_source IN ('feed', 'asr'));
ALTER TABLE episodes ADD COLUMN transcript_updated_at TIMESTAMPTZ;

WITH survivors AS (
    SELECT id, user_id, podcast_id
    FROM (
        SELECT id, user_id, podcast_id, ROW_NUMBER() OVER (PARTITION BY user_id, podcast_id ORDER BY created_at, id) AS position
        FROM subscriptions
    ) ranked
    WHERE position = 1
), latest_prompts AS (
    SELECT DISTINCT ON (user_id, podcast_id) user_id, podcast_id, custom_prompt
    FROM subscriptions
    WHERE custom_prompt IS NOT NULL
    ORDER BY user_id, podcast_id, created_at DESC, id DESC
)
UPDATE subscriptions survivor
SET custom_prompt = prompt.custom_prompt
FROM survivors, latest_prompts prompt
WHERE survivor.id = survivors.id
  AND prompt.user_id = survivors.user_id
  AND prompt.podcast_id = survivors.podcast_id;

WITH survivors AS (
    SELECT id, user_id, podcast_id
    FROM (
        SELECT id, user_id, podcast_id, ROW_NUMBER() OVER (PARTITION BY user_id, podcast_id ORDER BY created_at, id) AS position
        FROM subscriptions
    ) ranked
    WHERE position = 1
), latest_prompts AS (
    SELECT DISTINCT ON (user_id, podcast_id) user_id, podcast_id, chat_prompt
    FROM subscriptions
    WHERE chat_prompt IS NOT NULL
    ORDER BY user_id, podcast_id, created_at DESC, id DESC
)
UPDATE subscriptions survivor
SET chat_prompt = prompt.chat_prompt
FROM survivors, latest_prompts prompt
WHERE survivor.id = survivors.id
  AND prompt.user_id = survivors.user_id
  AND prompt.podcast_id = survivors.podcast_id;

WITH ranked AS (
    SELECT id, ROW_NUMBER() OVER (PARTITION BY user_id, podcast_id ORDER BY created_at NULLS LAST, id) AS position
    FROM subscriptions
)
DELETE FROM subscriptions duplicate
USING ranked
WHERE duplicate.id = ranked.id AND ranked.position > 1;

ALTER TABLE subscriptions ADD CONSTRAINT subscriptions_user_podcast_unique UNIQUE (user_id, podcast_id);

CREATE TABLE api_jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    episode_id TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('summary', 'transcript')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'done', 'error')),
    result_url TEXT,
    error_code TEXT,
    error_message TEXT,
    worker_id TEXT,
    lease_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX api_jobs_one_active_per_resource
ON api_jobs (user_id, episode_id, kind)
WHERE status IN ('pending', 'running');

CREATE INDEX api_jobs_pending_created_at
ON api_jobs (created_at)
WHERE status = 'pending';
