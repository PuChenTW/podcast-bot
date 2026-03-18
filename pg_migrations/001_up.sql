CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    telegram_user_id BIGINT UNIQUE NOT NULL,
    chat_id BIGINT NOT NULL,
    language TEXT DEFAULT 'zh-tw',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS podcasts (
    id TEXT PRIMARY KEY,
    rss_url TEXT UNIQUE NOT NULL,
    title TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id),
    podcast_id TEXT REFERENCES podcasts(id),
    custom_prompt TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    podcast_id TEXT REFERENCES podcasts(id),
    episode_guid TEXT NOT NULL,
    title TEXT,
    published_at TIMESTAMPTZ,
    transcript TEXT,
    condensed_transcript TEXT,
    description TEXT,
    UNIQUE(podcast_id, episode_guid)
);

CREATE TABLE IF NOT EXISTS user_episodes (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id),
    episode_id TEXT REFERENCES episodes(id),
    summary TEXT,
    notified_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, episode_id)
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
