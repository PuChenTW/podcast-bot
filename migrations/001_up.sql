CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    telegram_user_id INTEGER UNIQUE NOT NULL,
    chat_id INTEGER NOT NULL,
    language TEXT DEFAULT 'zh-tw',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id),
    podcast_title TEXT NOT NULL,
    rss_url TEXT NOT NULL,
    custom_prompt TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS episodes (
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
