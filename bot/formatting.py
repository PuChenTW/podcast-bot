import html as _html
import re


def markdown_to_html(text: str) -> str:
    """Convert Gemini-emitted Markdown to Telegram HTML."""
    # Escape HTML special chars first, before inserting any tags
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Fenced code blocks (``` ... ```) — before inline `code`
    text = re.sub(
        r"```(?:\w+\n)?(.*?)```",
        lambda m: f"<pre>{m.group(1).strip()}</pre>",
        text,
        flags=re.DOTALL,
    )

    # Inline code
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)

    # Bold (**text**) — before italic so ** isn't consumed as two *
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

    # Italic (*text* or _text_)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<i>\1</i>", text)

    # ATX headers (# through ######) → <b>
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # Horizontal rules — strip entirely
    text = re.sub(r"^\s*---+\s*$", "", text, flags=re.MULTILINE)

    # Leading - or * bullets → •
    text = re.sub(r"^[ \t]*[-*]\s+", "• ", text, flags=re.MULTILINE)

    # Clean up excess blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def format_summary(podcast_title: str, episode_title: str, summary: str) -> str:
    title_safe = _html.escape(podcast_title)
    ep_safe = _html.escape(episode_title)
    body = markdown_to_html(summary)
    return f"<b>{title_safe}</b>\n<i>{ep_safe}</i>\n\n{body}"


async def send_html(send_fn, text: str, **kwargs) -> None:
    """Send a Telegram message with HTML parse mode."""
    await send_fn(text, parse_mode="HTML", **kwargs)
