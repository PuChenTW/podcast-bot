DROP TABLE IF EXISTS api_jobs;
ALTER TABLE subscriptions DROP CONSTRAINT IF EXISTS subscriptions_user_podcast_unique;
ALTER TABLE episodes DROP COLUMN IF EXISTS transcript_updated_at;
ALTER TABLE episodes DROP COLUMN IF EXISTS transcript_source;
