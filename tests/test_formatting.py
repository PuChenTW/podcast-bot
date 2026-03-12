from unittest.mock import AsyncMock

from bot.formatting import format_summary, markdown_to_html, send_html


class TestMarkdownToHtml:
    def test_bold(self):
        assert markdown_to_html("**text**") == "<b>text</b>"

    def test_italic_star(self):
        assert markdown_to_html("*text*") == "<i>text</i>"

    def test_italic_underscore(self):
        assert markdown_to_html("_text_") == "<i>text</i>"

    def test_header(self):
        assert markdown_to_html("# Title") == "<b>Title</b>"

    def test_header_multiple_levels(self):
        assert markdown_to_html("### H3") == "<b>H3</b>"

    def test_fenced_code_block(self):
        result = markdown_to_html("```\ncode here\n```")
        assert result == "<pre>code here</pre>"

    def test_inline_code(self):
        assert markdown_to_html("`x`") == "<code>x</code>"

    def test_bullet_dash(self):
        assert markdown_to_html("- item") == "• item"

    def test_bullet_star(self):
        assert markdown_to_html("* item") == "• item"

    def test_horizontal_rule_stripped(self):
        result = markdown_to_html("before\n---\nafter")
        assert "---" not in result
        assert "<hr" not in result

    def test_html_chars_escaped_before_tags(self):
        # & < > must be escaped but the resulting <b> tags should not be double-escaped
        result = markdown_to_html("**a & b**")
        assert result == "<b>a &amp; b</b>"
        assert "&amp;amp;" not in result

    def test_lt_gt_escaped(self):
        result = markdown_to_html("a < b > c")
        assert "&lt;" in result
        assert "&gt;" in result

    def test_excess_blank_lines_collapsed(self):
        result = markdown_to_html("a\n\n\n\nb")
        assert "\n\n\n" not in result


class TestFormatSummary:
    def test_starts_with_title_and_episode(self):
        result = format_summary("My Show", "Ep 1", "body text")
        assert result.startswith("<b>My Show</b>\n<i>Ep 1</i>")

    def test_html_escapes_titles(self):
        result = format_summary("A & B", "C < D", "body")
        assert "<b>A &amp; B</b>" in result
        assert "<i>C &lt; D</i>" in result

    def test_body_markdown_converted(self):
        result = format_summary("Show", "Ep", "**bold**")
        assert "<b>bold</b>" in result


class TestSendHtml:
    async def test_parse_mode_html(self):
        send_fn = AsyncMock()
        await send_html(send_fn, "hello")
        send_fn.assert_called_once_with("hello", parse_mode="HTML")

    async def test_kwargs_forwarded(self):
        send_fn = AsyncMock()
        await send_html(send_fn, "hello", disable_web_page_preview=True)
        send_fn.assert_called_once_with(
            "hello", parse_mode="HTML", disable_web_page_preview=True
        )
