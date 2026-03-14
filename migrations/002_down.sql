PRAGMA foreign_keys = OFF;

-- Restore subscriptions with rss_url and podcast_title from podcasts
CREATE TABLE subscriptions_old (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id),
    podcast_title TEXT NOT NULL,
    rss_url TEXT NOT NULL,
    custom_prompt TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO subscriptions_old (id, user_id, podcast_title, rss_url, custom_prompt, created_at)
SELECT s.id, s.user_id, p.title, p.rss_url, s.custom_prompt, s.created_at
FROM subscriptions s
JOIN podcasts p ON p.id = s.podcast_id;

DROP TABLE subscriptions;
ALTER TABLE subscriptions_old RENAME TO subscriptions;

-- Restore episodes with subscription_id, summary, notified_at; dedup key reverts to (subscription_id, episode_guid)
-- For each episode, pick the first matching subscription (by user_id from user_episodes) to reconstruct subscription_id.
-- This is best-effort: ambiguous when multiple users subscribed to the same podcast.
CREATE TABLE episodes_old (
    id TEXT PRIMARY KEY,
    subscription_id TEXT REFERENCES subscriptions(id),
    episode_guid TEXT NOT NULL,
    title TEXT,
    published_at TIMESTAMP,
    summary TEXT,
    transcript TEXT,
    notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(subscription_id, episode_guid)
);

INSERT INTO episodes_old (id, subscription_id, episode_guid, title, published_at, summary, transcript, notified_at)
SELECT
    e.id,
    (
        SELECT s.id FROM subscriptions s
        JOIN podcasts p ON p.id = e.podcast_id
        JOIN user_episodes ue ON ue.user_id = s.user_id
        WHERE ue.episode_id = e.id
          AND s.rss_url = p.rss_url
        ORDER BY s.created_at
        LIMIT 1
    ) AS subscription_id,
    e.episode_guid,
    e.title,
    e.published_at,
    (SELECT ue.summary FROM user_episodes ue WHERE ue.episode_id = e.id ORDER BY ue.notified_at LIMIT 1),
    e.transcript,
    (SELECT ue.notified_at FROM user_episodes ue WHERE ue.episode_id = e.id ORDER BY ue.notified_at LIMIT 1)
FROM episodes e;

DROP TABLE episodes;
ALTER TABLE episodes_old RENAME TO episodes;

DROP TABLE IF EXISTS user_episodes;
DROP TABLE IF EXISTS podcasts;

PRAGMA foreign_keys = ON;
