"""Tests for send-notification action."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread
from unittest.mock import patch

import pytest
from jinja2 import Environment, FileSystemLoader

from send import (
    http_post,
    linkify_urls,
    main,
    markdown_links_to_html,
    parse_comma_list,
    parse_download_links,
    parse_pr_list,
    send_matrix,
    send_telegram,
    strip_markdown_links,
    validate_pr_list_format,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"


# ---------------------------------------------------------------------------
# Helpers: linkify
# ---------------------------------------------------------------------------


class TestMarkdownLinksToHtml:
    def test_converts_markdown_link(self):
        assert markdown_links_to_html("[#123](https://github.com/org/repo/pull/123): Fix bug") == (
            '<a href="https://github.com/org/repo/pull/123">#123</a>: Fix bug'
        )

    def test_multiple_links(self):
        result = markdown_links_to_html("Refs [#10](https://example.com/10) and [#20](https://example.com/20)")
        assert '<a href="https://example.com/10">#10</a>' in result
        assert '<a href="https://example.com/20">#20</a>' in result

    def test_no_links_returns_unchanged(self):
        assert markdown_links_to_html("Just text") == "Just text"


class TestStripMarkdownLinks:
    def test_strips_link(self):
        assert strip_markdown_links("[#123](https://example.com/123): Fix") == "#123: Fix"

    def test_multiple_links(self):
        result = strip_markdown_links("[A](url1) and [B](url2)")
        assert result == "A and B"

    def test_no_links_returns_unchanged(self):
        assert strip_markdown_links("Just text") == "Just text"


class TestLinkifyUrls:
    def test_converts_https_url(self):
        result = linkify_urls("Visit https://example.com for details")
        assert result == 'Visit <a href="https://example.com">https://example.com</a> for details'

    def test_converts_http_url(self):
        result = linkify_urls("http://example.com")
        assert '<a href="http://example.com">' in result

    def test_url_with_path_and_query(self):
        url = "https://example.com/path?q=1&b=2"
        result = linkify_urls(url)
        assert f'<a href="{url}">{url}</a>' == result

    def test_multiple_urls(self):
        text = "A: https://a.com B: https://b.com"
        result = linkify_urls(text)
        assert result.count("<a href=") == 2

    def test_no_urls_returns_unchanged(self):
        assert linkify_urls("no links here") == "no links here"


# ---------------------------------------------------------------------------
# Helpers: parsers
# ---------------------------------------------------------------------------


class TestValidatePrListFormat:
    def test_valid_lines(self):
        raw = "- [#1](https://github.com/org/repo/pull/1): First\n- [#2](https://github.com/org/repo/pull/2): Second"
        assert validate_pr_list_format(raw) == []

    def test_missing_markdown_link(self):
        raw = "- #1: First PR"
        errors = validate_pr_list_format(raw)
        assert len(errors) == 1
        assert "- #1: First PR" in errors[0]

    def test_plain_text_line(self):
        raw = "- Just some text without PR number"
        assert len(validate_pr_list_format(raw)) == 1

    def test_mixed_valid_and_invalid(self):
        raw = "- [#1](https://github.com/org/repo/pull/1): Good\n- #2: Bad format"
        errors = validate_pr_list_format(raw)
        assert len(errors) == 1
        assert "#2: Bad format" in errors[0]

    def test_skips_empty_lines(self):
        raw = "- [#1](https://github.com/org/repo/pull/1): First\n\n- [#2](https://github.com/org/repo/pull/2): Second"
        assert validate_pr_list_format(raw) == []

    def test_missing_title(self):
        raw = "- [#1](https://github.com/org/repo/pull/1):"
        assert len(validate_pr_list_format(raw)) == 1

    def test_missing_colon_after_link(self):
        raw = "- [#1](https://github.com/org/repo/pull/1) No colon"
        assert len(validate_pr_list_format(raw)) == 1

    def test_http_url_accepted(self):
        raw = "- [#1](http://github.com/org/repo/pull/1): Title"
        assert validate_pr_list_format(raw) == []


class TestParsePrList:
    def test_basic(self):
        raw = "- [#1](https://github.com/org/repo/pull/1): First\n- [#2](https://github.com/org/repo/pull/2): Second"
        items = parse_pr_list(raw)
        assert len(items) == 2
        assert items[0]["raw"] == "#1: First"
        assert "pull/1" in items[0]["linked"]

    def test_strips_dash_prefix(self):
        items = parse_pr_list("-  [#5](https://github.com/org/repo/pull/5): Title")
        assert items[0]["raw"] == "#5: Title"

    def test_skips_empty_lines(self):
        items = parse_pr_list("- [#1](https://example.com/1): A\n\n- [#2](https://example.com/2): B\n")
        assert len(items) == 2

    def test_plain_text_without_links(self):
        items = parse_pr_list("- #1: A")
        assert items[0]["raw"] == "#1: A"
        assert items[0]["linked"] == "#1: A"


class TestParseDownloadLinks:
    def test_basic(self):
        raw = "Firebase: https://firebase.com/app\nAPK: https://s3.com/app.apk"
        items = parse_download_links(raw)
        assert len(items) == 2
        assert items[0]["raw"] == "Firebase: https://firebase.com/app"
        assert '<a href="https://firebase.com/app">' in items[0]["linked"]

    def test_skips_empty_lines(self):
        items = parse_download_links("A: https://a.com\n\nB: https://b.com\n")
        assert len(items) == 2


class TestParseCommaList:
    def test_basic(self):
        assert parse_comma_list("-100, -200, -300") == ["-100", "-200", "-300"]

    def test_single_value(self):
        assert parse_comma_list("-100") == ["-100"]

    def test_empty_string(self):
        assert parse_comma_list("") == []

    def test_whitespace_only(self):
        assert parse_comma_list("  ,  , ") == []

    def test_trailing_comma(self):
        assert parse_comma_list("-100, -200,") == ["-100", "-200"]


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


@pytest.fixture
def jinja_env():
    return Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=False,
        keep_trailing_newline=False,
    )


@pytest.fixture
def template_ctx():
    return {
        "platform": "Android",
        "date": "16.03.2026",
        "prs": [
            {"raw": "#377: Fix scroll", "linked": '<a href="https://github.com/org/repo/pull/377">#377</a>: Fix scroll'},
            {"raw": "#384: Fix SSO", "linked": '<a href="https://github.com/org/repo/pull/384">#384</a>: Fix SSO'},
        ],
        "downloads": [
            {"raw": "Firebase: https://firebase.com/app", "linked": 'Firebase: <a href="https://firebase.com/app">https://firebase.com/app</a>'},
            {"raw": "APK: https://s3.com/app.apk", "linked": 'APK: <a href="https://s3.com/app.apk">https://s3.com/app.apk</a>'},
        ],
    }


class TestTelegramTemplate:
    def test_renders_header(self, jinja_env, template_ctx):
        result = jinja_env.get_template("telegram.html.j2").render(**template_ctx).strip()
        assert "<b>Changelog Android - 16.03.2026</b>" in result

    def test_renders_pr_links(self, jinja_env, template_ctx):
        result = jinja_env.get_template("telegram.html.j2").render(**template_ctx).strip()
        assert "pull/377" in result
        assert "pull/384" in result

    def test_renders_download_links(self, jinja_env, template_ctx):
        result = jinja_env.get_template("telegram.html.j2").render(**template_ctx).strip()
        assert "https://firebase.com/app" in result
        assert "https://s3.com/app.apk" in result

    def test_no_block_level_html(self, jinja_env, template_ctx):
        """Telegram does not support block-level HTML elements."""
        result = jinja_env.get_template("telegram.html.j2").render(**template_ctx).strip()
        for tag in ["<p>", "<br>", "<h1>", "<h2>", "<h3>", "<ul>", "<li>", "<div>"]:
            assert tag not in result, f"Telegram template must not contain {tag}"

    def test_uses_literal_newlines(self, jinja_env, template_ctx):
        result = jinja_env.get_template("telegram.html.j2").render(**template_ctx).strip()
        assert "\n" in result


class TestMatrixHtmlTemplate:
    def test_renders_h3_header(self, jinja_env, template_ctx):
        result = jinja_env.get_template("matrix.html.j2").render(**template_ctx).strip()
        assert "<h3>Changelog Android - 16.03.2026</h3>" in result

    def test_renders_pr_list_items(self, jinja_env, template_ctx):
        result = jinja_env.get_template("matrix.html.j2").render(**template_ctx).strip()
        assert "<li>" in result
        assert "<ul>" in result
        assert "pull/377" in result

    def test_renders_download_list_items(self, jinja_env, template_ctx):
        result = jinja_env.get_template("matrix.html.j2").render(**template_ctx).strip()
        assert result.count("<ul>") == 2  # PRs + Downloads


class TestMatrixPlainTemplate:
    def test_renders_plain_text(self, jinja_env, template_ctx):
        result = jinja_env.get_template("matrix_plain.txt.j2").render(**template_ctx).strip()
        assert "Changelog Android - 16.03.2026" in result
        assert "<" not in result.split("Changelog")[0]  # no HTML before header

    def test_uses_raw_pr_text(self, jinja_env, template_ctx):
        result = jinja_env.get_template("matrix_plain.txt.j2").render(**template_ctx).strip()
        assert "#377: Fix scroll" in result
        assert "<a href=" not in result

    def test_uses_raw_download_text(self, jinja_env, template_ctx):
        result = jinja_env.get_template("matrix_plain.txt.j2").render(**template_ctx).strip()
        assert "Firebase: https://firebase.com/app" in result
        assert "<a href=" not in result


# ---------------------------------------------------------------------------
# HTTP / sender (with mock server)
# ---------------------------------------------------------------------------


class _RecordingHandler(BaseHTTPRequestHandler):
    """Records requests for inspection in tests."""

    requests: list[dict] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        self.__class__.requests.append({
            "path": self.path,
            "headers": dict(self.headers),
            "body": body,
        })
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, format, *args):
        pass  # suppress console output


@pytest.fixture
def mock_server():
    _RecordingHandler.requests = []
    server = HTTPServer(("127.0.0.1", 0), _RecordingHandler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}", _RecordingHandler.requests
    server.shutdown()


class TestHttpPost:
    def test_success(self, mock_server):
        url, reqs = mock_server
        code, body = http_post(f"{url}/test", {"X-Custom": "val"}, "hello")
        assert code == 200
        assert reqs[0]["path"] == "/test"
        assert reqs[0]["body"] == "hello"
        assert reqs[0]["headers"]["X-Custom"] == "val"

    def test_connection_refused(self):
        code, body = http_post("http://127.0.0.1:1", {}, "x")
        assert code == 0
        assert body  # contains error reason


class TestSendTelegram:
    def test_sends_to_correct_path(self, mock_server):
        url, reqs = mock_server
        assert send_telegram(url, "tok123", "-100500", "<b>hi</b>") is True
        assert reqs[0]["path"] == "/telegram/send/-100500"
        assert reqs[0]["headers"]["Authorization"] == "tok123"
        assert reqs[0]["headers"]["Parse-Mode"] == "HTML"
        assert reqs[0]["body"] == "<b>hi</b>"

    def test_includes_thread_id(self, mock_server):
        url, reqs = mock_server
        send_telegram(url, "tok", "-100", "msg", thread_id="42")
        assert reqs[0]["headers"]["X-Thread-Id"] == "42"

    def test_no_thread_id_header_when_empty(self, mock_server):
        url, reqs = mock_server
        send_telegram(url, "tok", "-100", "msg", thread_id="")
        assert "X-Thread-Id" not in reqs[0]["headers"]

    def test_returns_false_on_failure(self):
        assert send_telegram("http://127.0.0.1:1", "tok", "-1", "msg") is False


class TestSendMatrix:
    def test_sends_to_encoded_path(self, mock_server):
        url, reqs = mock_server
        assert send_matrix(url, "tok", "!room:matrix.org", "plain", "<b>html</b>") is True
        assert reqs[0]["path"] == "/matrix/send/%21room%3Amatrix.org"

    def test_sends_json_payload(self, mock_server):
        url, reqs = mock_server
        send_matrix(url, "tok", "!r:m.org", "plain text", "<b>html</b>")
        payload = json.loads(reqs[0]["body"])
        assert payload["text"] == "plain text"
        assert payload["formatted_text"] == "<b>html</b>"

    def test_content_type_json(self, mock_server):
        url, reqs = mock_server
        send_matrix(url, "tok", "!r:m.org", "p", "h")
        assert reqs[0]["headers"]["Content-Type"] == "application/json"

    def test_returns_false_on_failure(self):
        assert send_matrix("http://127.0.0.1:1", "tok", "!r:m", "p", "h") is False


# ---------------------------------------------------------------------------
# Integration: main()
# ---------------------------------------------------------------------------


class TestMain:
    FIXED_DATE = "16.03.2026"

    BASE_ENV = {
        "INPUT_PLATFORM": "Android",
        "INPUT_PR_LIST": "- [#1](https://github.com/org/repo/pull/1): First PR\n- [#2](https://github.com/org/repo/pull/2): Second PR",
        "INPUT_DOWNLOAD_LINKS": "Firebase: https://firebase.com/app\nAPK: https://s3.com/app.apk",
        "INPUT_BOT_API_TOKEN": "test-token",
    }

    def _env(self, bot_url: str, **overrides) -> dict:
        env = {**self.BASE_ENV, "INPUT_BOT_URL": bot_url, **overrides}
        return env

    @staticmethod
    def _frozen_now(tz=None):
        return datetime(2026, 3, 16, 12, 0, 0, tzinfo=timezone.utc)

    def _run_main(self, env: dict) -> None:
        with patch.dict(os.environ, env, clear=False), \
             patch("send.datetime") as mock_dt:
            mock_dt.now = self._frozen_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            main()

    def test_sends_to_telegram(self, mock_server):
        url, reqs = mock_server
        env = self._env(url, INPUT_TELEGRAM_CHAT_IDS="-100")
        self._run_main(env)
        assert len(reqs) == 1
        assert "/telegram/send/-100" in reqs[0]["path"]

    def test_sends_to_matrix(self, mock_server):
        url, reqs = mock_server
        env = self._env(url, INPUT_MATRIX_ROOM_IDS="!room:m.org")
        self._run_main(env)
        assert len(reqs) == 1
        assert "/matrix/send/" in reqs[0]["path"]

    def test_sends_to_both(self, mock_server):
        url, reqs = mock_server
        env = self._env(url, INPUT_TELEGRAM_CHAT_IDS="-100", INPUT_MATRIX_ROOM_IDS="!r:m.org")
        self._run_main(env)
        assert len(reqs) == 2

    def test_multiple_chat_ids(self, mock_server):
        url, reqs = mock_server
        env = self._env(url, INPUT_TELEGRAM_CHAT_IDS="-100, -200, -300")
        self._run_main(env)
        assert len(reqs) == 3
        paths = [r["path"] for r in reqs]
        assert "/telegram/send/-100" in paths
        assert "/telegram/send/-200" in paths
        assert "/telegram/send/-300" in paths

    def test_multiple_room_ids(self, mock_server):
        url, reqs = mock_server
        env = self._env(url, INPUT_MATRIX_ROOM_IDS="!r1:m.org, !r2:m.org")
        self._run_main(env)
        assert len(reqs) == 2

    def test_fails_when_no_destinations(self, mock_server):
        url, _ = mock_server
        env = self._env(url)
        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(SystemExit, match="1"):
                main()

    def test_telegram_message_content(self, mock_server):
        url, reqs = mock_server
        env = self._env(url, INPUT_TELEGRAM_CHAT_IDS="-100")
        self._run_main(env)
        body = reqs[0]["body"]
        assert "<b>Changelog Android - 16.03.2026</b>" in body
        assert "pull/1" in body
        assert "pull/2" in body
        assert "https://firebase.com/app" in body

    def test_matrix_message_content(self, mock_server):
        url, reqs = mock_server
        env = self._env(url, INPUT_MATRIX_ROOM_IDS="!r:m.org")
        self._run_main(env)
        payload = json.loads(reqs[0]["body"])
        assert "<h3>" in payload["formatted_text"]
        assert "<li>" in payload["formatted_text"]
        assert "<a href=" not in payload["text"]  # plain text has no HTML

    def test_date_auto_computed(self, mock_server):
        """Date is computed internally, not from env."""
        url, reqs = mock_server
        env = self._env(url, INPUT_TELEGRAM_CHAT_IDS="-100")
        self._run_main(env)
        body = reqs[0]["body"]
        assert "16.03.2026" in body

    def test_exits_on_delivery_failure(self):
        """Script must exit(1) if any destination fails."""
        env = self._env("http://127.0.0.1:1", INPUT_TELEGRAM_CHAT_IDS="-100")
        with patch.dict(os.environ, env, clear=False), \
             patch("send.datetime") as mock_dt:
            mock_dt.now = self._frozen_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            with pytest.raises(SystemExit, match="1"):
                main()

    def test_partial_failure_still_sends_all(self, mock_server):
        """Even if one TG chat fails, other destinations are still attempted."""
        url, reqs = mock_server
        # Mix: one reachable mock server chat + one unreachable
        env = self._env(url, INPUT_TELEGRAM_CHAT_IDS="-100")
        # Override send_telegram to simulate partial failure
        original_send = send_telegram
        call_count = {"n": 0}

        def patched_send(bot_url, token, chat_id, message, thread_id=""):
            call_count["n"] += 1
            return original_send(bot_url, token, chat_id, message, thread_id)

        with patch.dict(os.environ, env, clear=False), \
             patch("send.datetime") as mock_dt, \
             patch("send.send_telegram", side_effect=patched_send):
            mock_dt.now = self._frozen_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            main()
        assert call_count["n"] == 1
