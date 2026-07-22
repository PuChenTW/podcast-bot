from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CatalogPodcast(BaseModel):
    name: str
    artist: str
    artwork_url: str
    feed_url: str


class Podcast(BaseModel):
    id: str
    title: str | None
    rss_url: str
    subscription_id: str


class PodcastList(BaseModel):
    items: list[Podcast]
    next_cursor: str | None


class SubscriptionCreate(BaseModel):
    rss_url: str


class SyncResult(BaseModel):
    new_count: int


class EpisodeListItem(BaseModel):
    id: str
    title: str | None
    published_at: datetime | None
    has_summary: bool
    has_transcript: bool


class EpisodeList(BaseModel):
    items: list[EpisodeListItem]
    next_cursor: str | None


class EpisodeDetail(BaseModel):
    id: str
    podcast_id: str
    title: str | None
    published_at: datetime | None
    description: str | None
    has_summary: bool
    has_transcript: bool


class Summary(BaseModel):
    episode_id: str
    content: str


class Transcript(BaseModel):
    episode_id: str
    content: str
    source: Literal["feed", "asr"] | None
    updated_at: datetime | None


class PromptSettings(BaseModel):
    summary_prompt: str | None
    chat_prompt: str | None


class PromptSettingsPatch(BaseModel):
    summary_prompt: str | None = None
    chat_prompt: str | None = None


class PromptDraftRequest(BaseModel):
    kind: Literal["summary", "chat"]
    description: str = ""


class PromptDraft(BaseModel):
    prompt: str


class Job(BaseModel):
    id: str
    episode_id: str
    kind: Literal["summary", "transcript"]
    status: Literal["pending", "running", "done", "error"]
    result_url: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ChatRequest(BaseModel):
    message: str = Field(max_length=4000)
    history: str = Field(max_length=200_000)
