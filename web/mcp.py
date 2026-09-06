"""MCP server exposing a read-and-analyze slice of the v1 API to AI agents.

Tools are derived from the FastAPI routes' `operation_id`s, so the REST API
stays the single source of truth for ownership checks and behavior.

The surface is deliberately narrower than the REST API. An agent's job here is
to find a podcast, get its transcript, and reason over the text itself, so the
allow-list below carries only what that workflow needs. Everything omitted is
omitted on purpose:

- `delete_subscription` is destructive and serves no part of the workflow.
- Delivery and prompt tools configure the Telegram bot and the web UI, not
  analysis.
- `download_episode_transcript` returns a `Content-Disposition` attachment,
  which is meaningless over MCP; stripped of that header it is a lossier
  `get_episode_transcript` whose name would lure an agent away from the better
  tool.
- `chat_with_episode` runs a second LLM over the transcript and requires
  round-tripping an opaque pydantic-ai history blob. The MCP client is itself
  an LLM with the transcript in context, so it does that job better.
"""

from fastapi import FastAPI
from fastapi_mcp import FastApiMCP

MCP_TOOLS = [
    # Discovery
    "search_podcast_catalog",
    "list_podcasts",
    "get_podcast",
    "create_subscription",
    "sync_podcast",
    # Episodes
    "list_podcast_episodes",
    "get_episode",
    # Content
    "fetch_episode_transcript",
    "get_episode_transcript",
    "get_episode_summary",
    "create_summary_job",
    "get_job",
]

MCP_DESCRIPTION = (
    "Find podcasts and retrieve episode transcripts for analysis.\n\n"
    "Two different searches: `list_podcasts` searches podcasts the user already "
    "subscribes to — these have episodes on hand and often cached transcripts, so "
    "it is the fast path. `search_podcast_catalog` searches all of Apple Podcasts "
    "for shows the user does not have yet; reaching a transcript from there means "
    "subscribing and running a transcription that takes minutes. Prefer "
    "`list_podcasts` first, and only subscribe when the user wants a new show.\n\n"
    "To read an episode, use `fetch_episode_transcript`. It returns the full text "
    "when cached, and otherwise starts transcription and reports `generating` — do "
    "other work and call it again rather than blocking. Analyze the transcript "
    "yourself; do not ask this server to summarize unless the user wants the "
    "summary stored in their library."
)


def mount_mcp(app: FastAPI) -> FastApiMCP:
    """Mount the MCP server at /mcp on the given app."""
    mcp = FastApiMCP(app, name="Podcast Bot", include_operations=MCP_TOOLS)

    # fastapi-mcp 0.4.0 builds `Server(name, description)`, which lands the text in
    # the protocol's `version` slot and leaves `instructions` -- the field clients
    # actually feed to the model -- empty. Set both correctly on the built server.
    mcp.server.version = app.version
    mcp.server.instructions = MCP_DESCRIPTION

    mcp.mount_http()
    return mcp
