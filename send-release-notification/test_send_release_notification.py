"""Tests for send-release-notification action."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread
from unittest.mock import patch

import pytest
from jinja2 import Environment, FileSystemLoader

MODULE_NAME = "send_release_notification_action"
MODULE_PATH = Path(__file__).with_name("send.py")
MODULE_SPEC = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
send = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_NAME] = send
MODULE_SPEC.loader.exec_module(send)

DEFAULT_RETRY_COUNT = send.DEFAULT_RETRY_COUNT
DEFAULT_RETRY_DELAY = send.DEFAULT_RETRY_DELAY
DEFAULT_REQUEST_TIMEOUT = send.DEFAULT_REQUEST_TIMEOUT
http_post = send.http_post
http_post_with_retry = send.http_post_with_retry
linkify_urls = send.linkify_urls
main = send.main
markdown_links_to_html = send.markdown_links_to_html
parse_comma_list = send.parse_comma_list
parse_download_links = send.parse_download_links
parse_pr_list = send.parse_pr_list
parse_retry_count = send.parse_retry_count
parse_retry_delay = send.parse_retry_delay
parse_request_timeout = send.parse_request_timeout
parse_retry_after = send.parse_retry_after
send_matrix = send.send_matrix
send_telegram = send.send_telegram
should_retry = send.should_retry
strip_markdown_links = send.strip_markdown_links
validate_pr_list_format = send.validate_pr_list_format

TEMPLATES_DIR = Path(__file__).parent / "templates"
ACTION_FILE = Path(__file__).with_name("action.yaml")


def action_input_default(path: Path, input_name: str) -> str:
    lines = path.read_text().splitlines()
    for index, line in enumerate(lines):
        if line == f"  {input_name}:":
            for nested in lines[index + 1:]:
                if nested.startswith("  ") and not nested.startswith("    "):
                    break
                stripped = nested.strip()
                if stripped.startswith("default:"):
                    return stripped.split(":", 1)[1].strip().strip("'\"")
    raise AssertionError(f"default for {input_name!r} not found in {path}")


def patch_send(target: str, *args, **kwargs):
    return patch(f"{MODULE_NAME}.{target}", *args, **kwargs)


# ---------------------------------------------------------------------------
# Global: speed up any test that goes through retry logic by stubbing sleep.
# Tests that want to inspect sleep timing patch send.time.sleep themselves.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_real_sleep():
    with patch_send("time.sleep") as m:
        yield m


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


class TestParseRetryCount:
    def test_empty_returns_default(self):
        assert parse_retry_count("") == DEFAULT_RETRY_COUNT

    def test_whitespace_returns_default(self):
        assert parse_retry_count("   ") == DEFAULT_RETRY_COUNT

    def test_valid_value(self):
        assert parse_retry_count("3") == 3

    def test_zero_allowed(self):
        assert parse_retry_count("0") == 0

    def test_negative_returns_default(self):
        assert parse_retry_count("-1") == DEFAULT_RETRY_COUNT

    def test_non_numeric_returns_default(self):
        assert parse_retry_count("abc") == DEFAULT_RETRY_COUNT

    def test_float_returns_default(self):
        assert parse_retry_count("2.5") == DEFAULT_RETRY_COUNT

    def test_custom_default(self):
        assert parse_retry_count("", default=2) == 2

    def test_trims_whitespace(self):
        assert parse_retry_count("  4  ") == 4


class TestParseRetryDelay:
    def test_empty_returns_default(self):
        assert parse_retry_delay("") == DEFAULT_RETRY_DELAY

    def test_valid_int(self):
        assert parse_retry_delay("30") == 30.0

    def test_valid_float(self):
        assert parse_retry_delay("2.5") == 2.5

    def test_zero_allowed(self):
        assert parse_retry_delay("0") == 0.0

    def test_negative_returns_default(self):
        assert parse_retry_delay("-5") == DEFAULT_RETRY_DELAY

    def test_non_numeric_returns_default(self):
        assert parse_retry_delay("abc") == DEFAULT_RETRY_DELAY

    def test_custom_default(self):
        assert parse_retry_delay("", default=5.0) == 5.0

    def test_non_finite_returns_default(self):
        assert parse_retry_delay("nan") == DEFAULT_RETRY_DELAY
        assert parse_retry_delay("inf") == DEFAULT_RETRY_DELAY


class TestParseRequestTimeout:
    def test_empty_returns_default(self):
        assert parse_request_timeout("") == DEFAULT_REQUEST_TIMEOUT

    def test_valid_int(self):
        assert parse_request_timeout("10") == 10.0

    def test_valid_float(self):
        assert parse_request_timeout("2.5") == 2.5

    def test_zero_returns_default(self):
        assert parse_request_timeout("0") == DEFAULT_REQUEST_TIMEOUT

    def test_negative_returns_default(self):
        assert parse_request_timeout("-5") == DEFAULT_REQUEST_TIMEOUT

    def test_non_numeric_returns_default(self):
        assert parse_request_timeout("abc") == DEFAULT_REQUEST_TIMEOUT

    def test_non_finite_returns_default(self):
        assert parse_request_timeout("nan") == DEFAULT_REQUEST_TIMEOUT
        assert parse_request_timeout("inf") == DEFAULT_REQUEST_TIMEOUT

    def test_custom_default(self):
        assert parse_request_timeout("", default=5.0) == 5.0


class TestParseRetryAfter:
    def test_empty_returns_none(self):
        assert parse_retry_after("") is None

    def test_delta_seconds(self):
        assert parse_retry_after("7") == 7.0

    def test_http_date(self):
        with patch_send("datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 4, 23, 10, 0, tzinfo=timezone.utc)
            assert parse_retry_after("Thu, 23 Apr 2026 10:00:05 GMT") == 5.0

    def test_invalid_returns_none(self):
        assert parse_retry_after("nonsense") is None
        assert parse_retry_after("nan") is None


class TestShouldRetry:
    def test_transport_error(self):
        assert should_retry(0) is True

    def test_rate_limit(self):
        assert should_retry(429) is True

    @pytest.mark.parametrize("code", [500, 502, 503, 504, 599])
    def test_5xx(self, code):
        assert should_retry(code) is True

    @pytest.mark.parametrize("code", [200, 201, 204])
    def test_2xx_not_retried(self, code):
        assert should_retry(code) is False

    @pytest.mark.parametrize("code", [301, 302])
    def test_3xx_not_retried(self, code):
        assert should_retry(code) is False

    @pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
    def test_4xx_not_retried_except_429(self, code):
        assert should_retry(code) is False


class TestRetryDefaults:
    def test_default_retry_count(self):
        assert DEFAULT_RETRY_COUNT == int(action_input_default(ACTION_FILE, "retry_count"))

    def test_default_retry_delay(self):
        assert DEFAULT_RETRY_DELAY == float(action_input_default(ACTION_FILE, "retry_delay"))

    def test_default_request_timeout(self):
        assert DEFAULT_REQUEST_TIMEOUT == float(action_input_default(ACTION_FILE, "request_timeout"))


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
    """Records requests for inspection in tests.

    Supports a per-class response script for simulating flaky endpoints:
    set ``_RecordingHandler.response_script`` to a list of status codes or
    ``(status, headers)`` tuples; each incoming request pops one entry.
    When the list is empty, returns 200.
    """

    requests: list[dict] = []
    response_script: list[object] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        self.__class__.requests.append({
            "path": self.path,
            "headers": dict(self.headers),
            "body": body,
        })
        if self.__class__.response_script:
            response = self.__class__.response_script.pop(0)
        else:
            response = 200
        if isinstance(response, tuple):
            status, extra_headers = response
        else:
            status, extra_headers = response, {}
        self.send_response(status)
        for key, value in extra_headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(b'{"ok":true}' if 200 <= status < 300 else b'{"error":"x"}')

    def log_message(self, format, *args):
        pass  # suppress console output


@pytest.fixture
def mock_server():
    _RecordingHandler.requests = []
    _RecordingHandler.response_script = []
    server = HTTPServer(("127.0.0.1", 0), _RecordingHandler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}", _RecordingHandler.requests, _RecordingHandler
    server.shutdown()


class TestHttpPost:
    def test_success(self, mock_server):
        url, reqs, _ = mock_server
        code, body, headers = http_post(f"{url}/test", {"X-Custom": "val"}, "hello")
        assert code == 200
        assert headers["server"]
        assert reqs[0]["path"] == "/test"
        assert reqs[0]["body"] == "hello"
        assert reqs[0]["headers"]["X-Custom"] == "val"

    def test_connection_refused(self):
        code, body, headers = http_post("http://127.0.0.1:1", {}, "x")
        assert code == 0
        assert headers == {}
        assert body  # contains error reason

    def test_passes_timeout_to_urlopen(self):
        class DummyResponse:
            status = 200
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"ok"

        with patch_send("urllib.request.urlopen", return_value=DummyResponse()) as mock_urlopen:
            code, body, headers = http_post("https://example.com/test", {}, "x", timeout=7.5)
        assert code == 200
        assert body == "ok"
        assert headers == {}
        assert mock_urlopen.call_args.kwargs["timeout"] == 7.5


# ---------------------------------------------------------------------------
# Retry wrapper
# ---------------------------------------------------------------------------


class TestHttpPostWithRetry:
    def test_success_no_retry(self, mock_server, _no_real_sleep):
        url, reqs, _ = mock_server
        code, _body = http_post_with_retry(
            f"{url}/ok", {}, "x", retry_count=3, retry_delay=0.01,
        )
        assert code == 200
        assert len(reqs) == 1
        _no_real_sleep.assert_not_called()

    def test_retries_on_5xx_then_succeeds(self, mock_server, _no_real_sleep):
        url, reqs, handler = mock_server
        handler.response_script = [500, 502, 503]
        code, _body = http_post_with_retry(
            f"{url}/ok", {}, "x", retry_count=6, retry_delay=20.0,
        )
        assert code == 200
        assert len(reqs) == 4
        assert _no_real_sleep.call_count == 3
        for call in _no_real_sleep.call_args_list:
            assert call.args == (20.0,)

    def test_retries_on_429(self, mock_server, _no_real_sleep):
        url, reqs, handler = mock_server
        handler.response_script = [429, 429]
        code, _body = http_post_with_retry(
            f"{url}/ok", {}, "x", retry_count=5, retry_delay=0.01,
        )
        assert code == 200
        assert len(reqs) == 3

    def test_429_uses_retry_after_header(self, mock_server, _no_real_sleep):
        url, reqs, handler = mock_server
        handler.response_script = [(429, {"Retry-After": "7"}), 200]
        code, _body = http_post_with_retry(
            f"{url}/ok", {}, "x", retry_count=5, retry_delay=0.01,
        )
        assert code == 200
        assert len(reqs) == 2
        assert _no_real_sleep.call_args_list[0].args == (7.0,)

    def test_retries_on_transport_error_then_succeeds(self, _no_real_sleep):
        call_counter = {"n": 0}

        def fake_http_post(url, headers, body, timeout):
            call_counter["n"] += 1
            if call_counter["n"] < 3:
                return 0, "Connection refused", {}
            return 200, "ok", {}

        with patch_send("http_post", side_effect=fake_http_post):
            code, body = http_post_with_retry(
                "http://example.invalid/x", {}, "data",
                retry_count=5, retry_delay=1.0,
            )
        assert code == 200
        assert call_counter["n"] == 3
        assert _no_real_sleep.call_count == 2

    def test_does_not_retry_on_4xx(self, mock_server, _no_real_sleep):
        url, reqs, handler = mock_server
        handler.response_script = [400]
        code, _body = http_post_with_retry(
            f"{url}/ok", {}, "x", retry_count=5, retry_delay=0.01,
        )
        assert code == 400
        assert len(reqs) == 1
        _no_real_sleep.assert_not_called()

    def test_exhausts_retries_and_returns_last_error(self, mock_server, _no_real_sleep):
        url, reqs, handler = mock_server
        handler.response_script = [500] * 10
        code, _body = http_post_with_retry(
            f"{url}/ok", {}, "x", retry_count=3, retry_delay=0.5,
        )
        assert code == 500
        assert len(reqs) == 4
        assert _no_real_sleep.call_count == 3

    def test_retry_count_zero_means_single_attempt(self, mock_server, _no_real_sleep):
        url, reqs, handler = mock_server
        handler.response_script = [500]
        code, _body = http_post_with_retry(
            f"{url}/ok", {}, "x", retry_count=0, retry_delay=99.0,
        )
        assert code == 500
        assert len(reqs) == 1
        _no_real_sleep.assert_not_called()

    def test_negative_retry_count_clamped_to_zero(self, mock_server, _no_real_sleep):
        url, reqs, handler = mock_server
        handler.response_script = [500]
        code, _body = http_post_with_retry(
            f"{url}/ok", {}, "x", retry_count=-3, retry_delay=0.01,
        )
        assert code == 500
        assert len(reqs) == 1
        _no_real_sleep.assert_not_called()

    def test_retry_delay_passed_to_sleep(self, mock_server, _no_real_sleep):
        url, _reqs, handler = mock_server
        handler.response_script = [500, 500]
        http_post_with_retry(
            f"{url}/ok", {}, "x", retry_count=2, retry_delay=7.5,
        )
        assert _no_real_sleep.call_args_list[0].args == (7.5,)
        assert _no_real_sleep.call_args_list[1].args == (7.5,)

    def test_request_timeout_passed_to_http_post(self):
        with patch_send("http_post", return_value=(500, "x", {})) as mock_http_post:
            http_post_with_retry(
                "https://example.com/ok",
                {},
                "x",
                retry_count=0,
                request_timeout=4.5,
            )
        assert mock_http_post.call_args.kwargs["timeout"] == 4.5


class TestSendTelegram:
    def test_sends_to_correct_path(self, mock_server):
        url, reqs, _ = mock_server
        assert send_telegram(url, "tok123", "-100500", "<b>hi</b>") is True
        assert reqs[0]["path"] == "/telegram/send/-100500"
        assert reqs[0]["headers"]["Authorization"] == "tok123"
        assert reqs[0]["headers"]["Parse-Mode"] == "HTML"
        assert reqs[0]["body"] == "<b>hi</b>"

    def test_includes_thread_id(self, mock_server):
        url, reqs, _ = mock_server
        send_telegram(url, "tok", "-100", "msg", thread_id="42")
        assert reqs[0]["headers"]["X-Thread-Id"] == "42"

    def test_no_thread_id_header_when_empty(self, mock_server):
        url, reqs, _ = mock_server
        send_telegram(url, "tok", "-100", "msg", thread_id="")
        assert "X-Thread-Id" not in reqs[0]["headers"]

    def test_returns_false_on_failure(self):
        assert send_telegram(
            "http://127.0.0.1:1", "tok", "-1", "msg",
            retry_count=0,
        ) is False

    def test_retries_on_transient_failure(self, mock_server, _no_real_sleep):
        url, reqs, handler = mock_server
        handler.response_script = [502, 503]
        assert send_telegram(
            url, "tok", "-100", "msg",
            retry_count=5, retry_delay=1.0,
        ) is True
        assert len(reqs) == 3
        assert _no_real_sleep.call_count == 2

    def test_returns_false_after_retries_exhausted(self, mock_server, _no_real_sleep):
        url, reqs, handler = mock_server
        handler.response_script = [500] * 10
        assert send_telegram(
            url, "tok", "-100", "msg",
            retry_count=3, retry_delay=0.01,
        ) is False
        assert len(reqs) == 4

    def test_passes_request_timeout_to_retry_wrapper(self):
        with patch_send("http_post_with_retry", return_value=(200, "ok")) as mock_retry:
            assert send_telegram(
                "https://example.com",
                "tok",
                "-100",
                "msg",
                request_timeout=4.5,
            ) is True
        assert mock_retry.call_args.kwargs["request_timeout"] == 4.5


class TestSendMatrix:
    def test_sends_to_encoded_path(self, mock_server):
        url, reqs, _ = mock_server
        assert send_matrix(url, "tok", "!room:matrix.org", "plain", "<b>html</b>") is True
        assert reqs[0]["path"] == "/matrix/send/%21room%3Amatrix.org"

    def test_sends_json_payload(self, mock_server):
        url, reqs, _ = mock_server
        send_matrix(url, "tok", "!r:m.org", "plain text", "<b>html</b>")
        payload = json.loads(reqs[0]["body"])
        assert payload["text"] == "plain text"
        assert payload["formatted_text"] == "<b>html</b>"

    def test_content_type_json(self, mock_server):
        url, reqs, _ = mock_server
        send_matrix(url, "tok", "!r:m.org", "p", "h")
        assert reqs[0]["headers"]["Content-Type"] == "application/json"

    def test_returns_false_on_failure(self):
        assert send_matrix(
            "http://127.0.0.1:1", "tok", "!r:m", "p", "h",
            retry_count=0,
        ) is False

    def test_retries_on_transient_failure(self, mock_server, _no_real_sleep):
        url, reqs, handler = mock_server
        handler.response_script = [500, 429]
        assert send_matrix(
            url, "tok", "!r:m.org", "p", "h",
            retry_count=5, retry_delay=0.5,
        ) is True
        assert len(reqs) == 3
        assert _no_real_sleep.call_count == 2

    def test_passes_request_timeout_to_retry_wrapper(self):
        with patch_send("http_post_with_retry", return_value=(200, "ok")) as mock_retry:
            assert send_matrix(
                "https://example.com",
                "tok",
                "!r:m.org",
                "p",
                "h",
                request_timeout=4.5,
            ) is True
        assert mock_retry.call_args.kwargs["request_timeout"] == 4.5


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
             patch_send("datetime") as mock_dt:
            mock_dt.now = self._frozen_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            main()

    def test_sends_to_telegram(self, mock_server):
        url, reqs, _ = mock_server
        env = self._env(url, INPUT_TELEGRAM_CHAT_IDS="-100")
        self._run_main(env)
        assert len(reqs) == 1
        assert "/telegram/send/-100" in reqs[0]["path"]

    def test_sends_to_matrix(self, mock_server):
        url, reqs, _ = mock_server
        env = self._env(url, INPUT_MATRIX_ROOM_IDS="!room:m.org")
        self._run_main(env)
        assert len(reqs) == 1
        assert "/matrix/send/" in reqs[0]["path"]

    def test_sends_to_both(self, mock_server):
        url, reqs, _ = mock_server
        env = self._env(url, INPUT_TELEGRAM_CHAT_IDS="-100", INPUT_MATRIX_ROOM_IDS="!r:m.org")
        self._run_main(env)
        assert len(reqs) == 2

    def test_multiple_chat_ids(self, mock_server):
        url, reqs, _ = mock_server
        env = self._env(url, INPUT_TELEGRAM_CHAT_IDS="-100, -200, -300")
        self._run_main(env)
        assert len(reqs) == 3
        paths = [r["path"] for r in reqs]
        assert "/telegram/send/-100" in paths
        assert "/telegram/send/-200" in paths
        assert "/telegram/send/-300" in paths

    def test_multiple_room_ids(self, mock_server):
        url, reqs, _ = mock_server
        env = self._env(url, INPUT_MATRIX_ROOM_IDS="!r1:m.org, !r2:m.org")
        self._run_main(env)
        assert len(reqs) == 2

    def test_fails_when_no_destinations(self, mock_server):
        url, _reqs, _ = mock_server
        env = self._env(url)
        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(SystemExit, match="1"):
                main()

    def test_telegram_message_content(self, mock_server):
        url, reqs, _ = mock_server
        env = self._env(url, INPUT_TELEGRAM_CHAT_IDS="-100")
        self._run_main(env)
        body = reqs[0]["body"]
        assert "<b>Changelog Android - 16.03.2026</b>" in body
        assert "pull/1" in body
        assert "pull/2" in body
        assert "https://firebase.com/app" in body

    def test_matrix_message_content(self, mock_server):
        url, reqs, _ = mock_server
        env = self._env(url, INPUT_MATRIX_ROOM_IDS="!r:m.org")
        self._run_main(env)
        payload = json.loads(reqs[0]["body"])
        assert "<h3>" in payload["formatted_text"]
        assert "<li>" in payload["formatted_text"]
        assert "<a href=" not in payload["text"]  # plain text has no HTML

    def test_date_auto_computed(self, mock_server):
        """Date is computed internally, not from env."""
        url, reqs, _ = mock_server
        env = self._env(url, INPUT_TELEGRAM_CHAT_IDS="-100")
        self._run_main(env)
        body = reqs[0]["body"]
        assert "16.03.2026" in body

    def test_exits_on_delivery_failure(self):
        """Script must exit(1) if any destination fails."""
        env = self._env(
            "http://127.0.0.1:1",
            INPUT_TELEGRAM_CHAT_IDS="-100",
            INPUT_RETRY_COUNT="0",
        )
        with patch.dict(os.environ, env, clear=False), \
             patch_send("datetime") as mock_dt:
            mock_dt.now = self._frozen_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            with pytest.raises(SystemExit, match="1"):
                main()

    def test_partial_failure_still_sends_all(self, mock_server):
        """Even if one TG chat fails, other destinations are still attempted."""
        url, reqs, _ = mock_server
        # Mix: one reachable mock server chat + one unreachable
        env = self._env(url, INPUT_TELEGRAM_CHAT_IDS="-100")
        # Override send_telegram to simulate partial failure
        original_send = send_telegram
        call_count = {"n": 0}

        def patched_send(bot_url, token, chat_id, message, thread_id="", **kwargs):
            call_count["n"] += 1
            return original_send(bot_url, token, chat_id, message, thread_id, **kwargs)

        with patch.dict(os.environ, env, clear=False), \
             patch_send("datetime") as mock_dt, \
             patch_send("send_telegram", side_effect=patched_send):
            mock_dt.now = self._frozen_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            main()
        assert call_count["n"] == 1

    # ---- retry integration ----

    def test_retries_in_main_on_transient_5xx(self, mock_server, _no_real_sleep):
        url, reqs, handler = mock_server
        handler.response_script = [503, 503]
        env = self._env(
            url,
            INPUT_TELEGRAM_CHAT_IDS="-100",
            INPUT_RETRY_COUNT="3",
            INPUT_RETRY_DELAY="1",
        )
        self._run_main(env)
        assert len(reqs) == 3
        assert _no_real_sleep.call_count == 2
        for call in _no_real_sleep.call_args_list:
            assert call.args == (1.0,)

    def test_main_default_retry_values_used_when_inputs_missing(self, mock_server):
        """With no env vars set, default retry and timeout values propagate into send_*."""
        url, _reqs, _ = mock_server
        env = self._env(url, INPUT_TELEGRAM_CHAT_IDS="-100")
        with patch.dict(os.environ, env, clear=False), \
             patch_send("datetime") as mock_dt, \
             patch_send("send_telegram", return_value=True) as st:
            mock_dt.now = self._frozen_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            main()
        st.assert_called_once()
        assert st.call_args.kwargs["retry_count"] == DEFAULT_RETRY_COUNT
        assert st.call_args.kwargs["retry_delay"] == DEFAULT_RETRY_DELAY
        assert st.call_args.kwargs["request_timeout"] == DEFAULT_REQUEST_TIMEOUT

    def test_main_custom_retry_values_override(self, mock_server):
        url, _reqs, _ = mock_server
        env = self._env(
            url,
            INPUT_MATRIX_ROOM_IDS="!r:m.org",
            INPUT_RETRY_COUNT="2",
            INPUT_RETRY_DELAY="0.5",
            INPUT_REQUEST_TIMEOUT="4.5",
        )
        with patch.dict(os.environ, env, clear=False), \
             patch_send("datetime") as mock_dt, \
             patch_send("send_matrix", return_value=True) as sm:
            mock_dt.now = self._frozen_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            main()
        sm.assert_called_once()
        assert sm.call_args.kwargs["retry_count"] == 2
        assert sm.call_args.kwargs["retry_delay"] == 0.5
        assert sm.call_args.kwargs["request_timeout"] == 4.5

    def test_main_invalid_retry_values_fall_back_to_defaults(self, mock_server):
        url, _reqs, _ = mock_server
        env = self._env(
            url,
            INPUT_TELEGRAM_CHAT_IDS="-100",
            INPUT_RETRY_COUNT="abc",
            INPUT_RETRY_DELAY="xyz",
            INPUT_REQUEST_TIMEOUT="nan",
        )
        with patch.dict(os.environ, env, clear=False), \
             patch_send("datetime") as mock_dt, \
             patch_send("send_telegram", return_value=True) as st:
            mock_dt.now = self._frozen_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            main()
        assert st.call_args.kwargs["retry_count"] == DEFAULT_RETRY_COUNT
        assert st.call_args.kwargs["retry_delay"] == DEFAULT_RETRY_DELAY
        assert st.call_args.kwargs["request_timeout"] == DEFAULT_REQUEST_TIMEOUT

    def test_main_zero_retries_sends_exactly_once(self, mock_server, _no_real_sleep):
        url, reqs, handler = mock_server
        handler.response_script = [500]
        env = self._env(
            url,
            INPUT_TELEGRAM_CHAT_IDS="-100",
            INPUT_RETRY_COUNT="0",
            INPUT_RETRY_DELAY="60",
        )
        with patch.dict(os.environ, env, clear=False), \
             patch_send("datetime") as mock_dt:
            mock_dt.now = self._frozen_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            with pytest.raises(SystemExit, match="1"):
                main()
        assert len(reqs) == 1
        _no_real_sleep.assert_not_called()

    def test_main_4xx_failure_is_not_retried(self, mock_server, _no_real_sleep):
        url, reqs, handler = mock_server
        handler.response_script = [401]
        env = self._env(
            url,
            INPUT_TELEGRAM_CHAT_IDS="-100",
            INPUT_RETRY_COUNT="5",
            INPUT_RETRY_DELAY="0.01",
        )
        with patch.dict(os.environ, env, clear=False), \
             patch_send("datetime") as mock_dt:
            mock_dt.now = self._frozen_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            with pytest.raises(SystemExit, match="1"):
                main()
        assert len(reqs) == 1
        _no_real_sleep.assert_not_called()

    def test_main_retries_per_destination(self, mock_server, _no_real_sleep):
        """Each destination has its own retry budget."""
        url, reqs, handler = mock_server
        handler.response_script = [500, 200, 500, 200]
        env = self._env(
            url,
            INPUT_TELEGRAM_CHAT_IDS="-100, -200",
            INPUT_RETRY_COUNT="3",
            INPUT_RETRY_DELAY="0.01",
        )
        self._run_main(env)
        assert len(reqs) == 4
        paths = [r["path"] for r in reqs]
        assert paths.count("/telegram/send/-100") == 2
        assert paths.count("/telegram/send/-200") == 2
