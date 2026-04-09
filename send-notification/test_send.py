"""Tests for send-notification action."""

from __future__ import annotations

import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from unittest.mock import patch

import pytest

from send import (
    http_post,
    main,
    parse_comma_list,
    parse_telegram_destinations,
    send_matrix,
    send_telegram,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


class TestParseTelegramDestinations:
    def test_chat_id_only(self):
        assert parse_telegram_destinations("-100") == [("-100", "")]

    def test_chat_id_with_thread(self):
        assert parse_telegram_destinations("-100:42") == [("-100", "42")]

    def test_mixed(self):
        result = parse_telegram_destinations("-100:42, -200, -300:99")
        assert result == [("-100", "42"), ("-200", ""), ("-300", "99")]

    def test_empty_string(self):
        assert parse_telegram_destinations("") == []

    def test_whitespace(self):
        result = parse_telegram_destinations(" -100 : 42 , -200 ")
        assert result == [("-100", "42"), ("-200", "")]


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

    def test_includes_thread_id_in_path(self, mock_server):
        url, reqs = mock_server
        send_telegram(url, "tok", "-100", "msg", thread_id="42")
        assert reqs[0]["path"] == "/telegram/send/-100/42"

    def test_no_thread_id_in_path_when_empty(self, mock_server):
        url, reqs = mock_server
        send_telegram(url, "tok", "-100", "msg", thread_id="")
        assert reqs[0]["path"] == "/telegram/send/-100"

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
    BASE_ENV = {
        "INPUT_MESSAGE": "Build failed\nBranch: main",
        "INPUT_HTML_MESSAGE": "<b>Build failed</b><br>Branch: main",
        "INPUT_BOT_API_TOKEN": "test-token",
    }

    def _env(self, bot_url: str, **overrides) -> dict:
        return {**self.BASE_ENV, "INPUT_BOT_URL": bot_url, **overrides}

    def test_sends_to_telegram(self, mock_server):
        url, reqs = mock_server
        env = self._env(url, INPUT_TELEGRAM_CHAT_IDS="-100")
        with patch.dict(os.environ, env, clear=False):
            main()
        assert len(reqs) == 1
        assert "/telegram/send/-100" in reqs[0]["path"]

    def test_sends_to_matrix(self, mock_server):
        url, reqs = mock_server
        env = self._env(url, INPUT_MATRIX_ROOM_IDS="!room:m.org")
        with patch.dict(os.environ, env, clear=False):
            main()
        assert len(reqs) == 1
        assert "/matrix/send/" in reqs[0]["path"]

    def test_sends_to_both(self, mock_server):
        url, reqs = mock_server
        env = self._env(url, INPUT_TELEGRAM_CHAT_IDS="-100", INPUT_MATRIX_ROOM_IDS="!r:m.org")
        with patch.dict(os.environ, env, clear=False):
            main()
        assert len(reqs) == 2

    def test_multiple_chat_ids(self, mock_server):
        url, reqs = mock_server
        env = self._env(url, INPUT_TELEGRAM_CHAT_IDS="-100, -200, -300")
        with patch.dict(os.environ, env, clear=False):
            main()
        assert len(reqs) == 3
        paths = [r["path"] for r in reqs]
        assert "/telegram/send/-100" in paths
        assert "/telegram/send/-200" in paths
        assert "/telegram/send/-300" in paths

    def test_chat_ids_with_thread_ids(self, mock_server):
        url, reqs = mock_server
        env = self._env(url, INPUT_TELEGRAM_CHAT_IDS="-100:42, -200, -300:99")
        with patch.dict(os.environ, env, clear=False):
            main()
        assert len(reqs) == 3
        paths = [r["path"] for r in reqs]
        assert "/telegram/send/-100/42" in paths
        assert "/telegram/send/-200" in paths
        assert "/telegram/send/-300/99" in paths

    def test_multiple_room_ids(self, mock_server):
        url, reqs = mock_server
        env = self._env(url, INPUT_MATRIX_ROOM_IDS="!r1:m.org, !r2:m.org")
        with patch.dict(os.environ, env, clear=False):
            main()
        assert len(reqs) == 2

    def test_fails_when_no_destinations(self, mock_server):
        url, _ = mock_server
        env = self._env(url)
        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(SystemExit, match="1"):
                main()

    def test_telegram_receives_html_message(self, mock_server):
        url, reqs = mock_server
        env = self._env(url, INPUT_TELEGRAM_CHAT_IDS="-100")
        with patch.dict(os.environ, env, clear=False):
            main()
        assert reqs[0]["body"] == "<b>Build failed</b><br>Branch: main"

    def test_matrix_receives_both_formats(self, mock_server):
        url, reqs = mock_server
        env = self._env(url, INPUT_MATRIX_ROOM_IDS="!r:m.org")
        with patch.dict(os.environ, env, clear=False):
            main()
        payload = json.loads(reqs[0]["body"])
        assert payload["text"] == "Build failed\nBranch: main"
        assert payload["formatted_text"] == "<b>Build failed</b><br>Branch: main"

    def test_html_message_falls_back_to_plain(self, mock_server):
        """When html_message is empty, plain message is used everywhere."""
        url, reqs = mock_server
        env = self._env(url, INPUT_MATRIX_ROOM_IDS="!r:m.org", INPUT_HTML_MESSAGE="")
        with patch.dict(os.environ, env, clear=False):
            main()
        payload = json.loads(reqs[0]["body"])
        assert payload["text"] == "Build failed\nBranch: main"
        assert payload["formatted_text"] == "Build failed\nBranch: main"

    def test_exits_on_delivery_failure(self):
        env = self._env("http://127.0.0.1:1", INPUT_TELEGRAM_CHAT_IDS="-100")
        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(SystemExit, match="1"):
                main()
