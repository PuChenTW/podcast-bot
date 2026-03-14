PRAGMA foreign_keys = OFF;

-- New table: one row per unique podcast RSS feed
CREATE TABLE IF NOT EXISTS podcasts (
    id TEXT PRIMARY KEY,
    rss_url TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- New table: per-user episode delivery record (summary + notification)
CREATE TABLE IF NOT EXISTS user_episodes (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id),
    episode_id TEXT REFERENCES episodes(id),
    summary TEXT,
    notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, episode_id)
);

-- Add podcast_id to subscriptions before backfill
ALTER TABLE subscriptions ADD COLUMN podcast_id TEXT REFERENCES podcasts(id);

-- Populate podcasts from subscriptions; randomblob(16) stands in for ULID (ULID needs app layer)
INSERT OR IGNORE INTO podcasts (id, rss_url, title)
SELECT lower(hex(randomblob(16))), rss_url, podcast_title FROM subscriptions;

-- Wire subscriptions to their podcast rows
UPDATE subscriptions
SET podcast_id = (SELECT id FROM podcasts WHERE podcasts.rss_url = subscriptions.rss_url);

-- Add podcast_id to episodes before backfill
ALTER TABLE episodes ADD COLUMN podcast_id TEXT REFERENCES podcasts(id);

-- Backfill episodes.podcast_id via their subscription
UPDATE episodes
SET podcast_id = (
    SELECT s.podcast_id FROM subscriptions s WHERE s.id = episodes.subscription_id
);

-- Migrate per-subscription episode delivery records into user_episodes
INSERT INTO user_episodes (id, user_id, episode_id, summary, notified_at)
SELECT lower(hex(randomblob(16))), s.user_id, e.id, e.summary, e.notified_at
FROM episodes e
JOIN subscriptions s ON e.subscription_id = s.id;

-- Recreate subscriptions without rss_url and podcast_title
CREATE TABLE subscriptions_new (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id),
    podcast_id TEXT REFERENCES podcasts(id),
    custom_prompt TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO subscriptions_new (id, user_id, podcast_id, custom_prompt, created_at)
SELECT id, user_id, podcast_id, custom_prompt, created_at FROM subscriptions;

DROP TABLE subscriptions;
ALTER TABLE subscriptions_new RENAME TO subscriptions;

-- Recreate episodes without subscription_id, summary, notified_at; new dedup key is (podcast_id, episode_guid)
CREATE TABLE episodes_new (
    id TEXT PRIMARY KEY,
    podcast_id TEXT REFERENCES podcasts(id),
    episode_guid TEXT NOT NULL,
    title TEXT,
    published_at TIMESTAMP,
    transcript TEXT,
    UNIQUE(podcast_id, episode_guid)
);

INSERT INTO episodes_new (id, podcast_id, episode_guid, title, published_at, transcript)
SELECT id, podcast_id, episode_guid, title, published_at, transcript FROM episodes;

DROP TABLE episodes;
ALTER TABLE episodes_new RENAME TO episodes;

PRAGMA foreign_keys = ON;
