#!/usr/bin/env python3
"""
Render and send build changelog notifications to Telegram and Matrix
via an external notification bot service.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader


DEFAULT_RETRY_COUNT = 6
DEFAULT_RETRY_DELAY = 20.0
DEFAULT_REQUEST_TIMEOUT = 60.0
DEFAULT_DOWNLOAD_LINKS_FORMAT = "list"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def markdown_links_to_html(text: str) -> str:
    """Convert markdown [text](url) links to HTML <a href="url">text</a>."""
    return re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2">\1</a>',
        text,
    )


def linkify_urls(text: str) -> str:
    """Wrap plain URLs in <a> tags."""
    return re.sub(
        r"(https?://[^\s<>\"]+)",
        r'<a href="\1">\1</a>',
        text,
    )


def strip_markdown_links(text: str) -> str:
    """Strip markdown links to plain text: [text](url) -> text."""
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)


_PR_LINE_RE = re.compile(r"^-\s*\[#\d+\]\(https?://[^)]+\):\s*.+")


def validate_pr_list_format(raw: str) -> list[str]:
    """Validate that PR list lines match expected markdown format.

    Expected format: - [#N](url): Title
    Returns a list of invalid lines (empty if all valid).
    """
    errors = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if not _PR_LINE_RE.match(line):
            errors.append(line)
    return errors


def parse_pr_list(raw: str) -> list[dict]:
    """Parse multiline PR list into structured items with raw and linked versions.

    Expects markdown-formatted lines like: - [#377](url): Title
    """
    bad_lines = validate_pr_list_format(raw)
    if bad_lines:
        print(f"::warning::PR list contains lines not matching expected format '- [#N](url): Title':")
        for line in bad_lines:
            print(f"  {line}")

    items = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        clean = re.sub(r"^-\s*", "", line)
        items.append({
            "raw": strip_markdown_links(clean),
            "linked": markdown_links_to_html(clean),
        })
    return items


def parse_download_links(raw: str) -> list[dict]:
    """Parse multiline download links into items with raw and linked versions."""
    items = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        named_link = re.fullmatch(r"\[([^\]]+)\]\((https?://.+)\)", line)
        if named_link:
            label, url = named_link.groups()
            items.append({
                "raw": f"{label} ({url})",
                "linked": f'<a href="{url}">{label}</a>',
            })
            continue
        items.append({
            "raw": line,
            "linked": linkify_urls(line),
        })
    return items


def parse_download_links_format(
    value: str,
    default: str = DEFAULT_DOWNLOAD_LINKS_FORMAT,
) -> str:
    """Parse the download links layout, falling back to list when invalid."""
    parsed = (value or "").strip().lower()
    if not parsed:
        return default
    if parsed not in {"list", "inline"}:
        print(f"::warning::invalid download_links_format={value!r}, using default {default!r}")
        return default
    return parsed


def parse_comma_list(value: str) -> list[str]:
    """Split comma-separated string into a list of non-empty stripped values."""
    return [v.strip() for v in value.split(",") if v.strip()]


def parse_retry_count(value: str, default: int = DEFAULT_RETRY_COUNT) -> int:
    raw = (value or "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        print(f"::warning::invalid retry_count={value!r}, using default {default}")
        return default
    if parsed < 0:
        print(f"::warning::retry_count must be >= 0 (got {parsed}), using default {default}")
        return default
    return parsed


def parse_float_input(
    value: str,
    *,
    default: float,
    name: str,
    allow_zero: bool,
) -> float:
    raw = (value or "").strip()
    if not raw:
        return default
    try:
        parsed = float(raw)
    except ValueError:
        print(f"::warning::invalid {name}={value!r}, using default {default}")
        return default
    if not math.isfinite(parsed):
        print(f"::warning::{name} must be finite (got {parsed}), using default {default}")
        return default
    if parsed < 0 or (not allow_zero and parsed == 0):
        relation = ">= 0" if allow_zero else "> 0"
        print(f"::warning::{name} must be {relation} (got {parsed}), using default {default}")
        return default
    return parsed


def parse_retry_delay(value: str, default: float = DEFAULT_RETRY_DELAY) -> float:
    return parse_float_input(
        value,
        default=default,
        name="retry_delay",
        allow_zero=True,
    )


def parse_request_timeout(
    value: str,
    default: float = DEFAULT_REQUEST_TIMEOUT,
) -> float:
    return parse_float_input(
        value,
        default=default,
        name="request_timeout",
        allow_zero=False,
    )


def parse_retry_after(value: str) -> float | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        delay = float(raw)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(raw)
        except (TypeError, ValueError, IndexError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
    if not math.isfinite(delay) or delay < 0:
        return None
    return delay


# ---------------------------------------------------------------------------
# HTTP sender
# ---------------------------------------------------------------------------

def http_post(
    url: str,
    headers: dict,
    body: bytes | str,
    timeout: float = DEFAULT_REQUEST_TIMEOUT,
) -> tuple[int, str, dict[str, str]]:
    """Send HTTP POST and return (status_code, response_body)."""
    if isinstance(body, str):
        body = body.encode("utf-8")

    headers.setdefault("User-Agent", "GitHubActions/2.0 (send-notification; +https://github.com)")
    headers.setdefault("Accept", "application/json, text/plain, */*")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return (
                resp.status,
                resp.read().decode("utf-8", errors="replace"),
                {k.lower(): v for k, v in resp.headers.items()},
            )
    except urllib.error.HTTPError as e:
        return (
            e.code,
            e.read().decode("utf-8", errors="replace"),
            {k.lower(): v for k, v in e.headers.items()},
        )
    except urllib.error.URLError as e:
        return 0, str(e.reason), {}


def should_retry(status_code: int) -> bool:
    """Retry on transport errors (0), rate limiting (429) and 5xx server errors."""
    return status_code == 0 or status_code == 429 or 500 <= status_code < 600


def http_post_with_retry(
    url: str,
    headers: dict,
    body: bytes | str,
    retry_count: int = DEFAULT_RETRY_COUNT,
    retry_delay: float = DEFAULT_RETRY_DELAY,
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
) -> tuple[int, str]:
    """POST with retries on transport/429/5xx errors.

    retry_count: number of additional attempts after the first one (0 = no retries).
    retry_delay: seconds to sleep between attempts.
    request_timeout: per-attempt socket timeout in seconds.
    """
    attempts = max(retry_count, 0) + 1
    code, resp = 0, ""
    for attempt in range(1, attempts + 1):
        code, resp, response_headers = http_post(url, headers, body, timeout=request_timeout)
        if not should_retry(code):
            return code, resp
        if attempt < attempts:
            delay = retry_delay
            retry_after = parse_retry_after(response_headers.get("retry-after", ""))
            if code == 429 and retry_after is not None:
                delay = retry_after
            print(
                f"  ::warning::request to {url} failed (HTTP {code}), "
                f"retrying in {delay}s (attempt {attempt}/{retry_count})"
            )
            time.sleep(delay)
    return code, resp


def send_telegram(
    bot_url: str,
    token: str,
    chat_id: str,
    message: str,
    thread_id: str = "",
    retry_count: int = DEFAULT_RETRY_COUNT,
    retry_delay: float = DEFAULT_RETRY_DELAY,
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
) -> bool:
    headers = {
        "Authorization": token,
        "Parse-Mode": "HTML",
    }
    if thread_id:
        headers["X-Thread-ID"] = thread_id

    url = f"{bot_url}/telegram/send/{chat_id}"
    code, resp = http_post_with_retry(
        url,
        headers,
        message,
        retry_count=retry_count,
        retry_delay=retry_delay,
        request_timeout=request_timeout,
    )

    if 200 <= code < 300:
        print(f"  Telegram [{chat_id}] sent (HTTP {code})")
        return True
    print(f"  ::error::Telegram [{chat_id}] failed (HTTP {code}): {resp}")
    return False


def send_matrix(
    bot_url: str,
    token: str,
    room_id: str,
    plain_text: str,
    html: str,
    retry_count: int = DEFAULT_RETRY_COUNT,
    retry_delay: float = DEFAULT_RETRY_DELAY,
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
) -> bool:
    encoded_room = urllib.parse.quote(room_id, safe="")
    url = f"{bot_url}/matrix/send/{encoded_room}"
    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
    }
    payload = json.dumps({"text": plain_text, "formatted_text": html})
    code, resp = http_post_with_retry(
        url,
        headers,
        payload,
        retry_count=retry_count,
        retry_delay=retry_delay,
        request_timeout=request_timeout,
    )

    if 200 <= code < 300:
        print(f"  Matrix [{room_id}] sent (HTTP {code})")
        return True
    print(f"  ::error::Matrix [{room_id}] failed (HTTP {code}): {resp}")
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # Read inputs from environment
    platform = os.environ["INPUT_PLATFORM"]
    pr_list_raw = os.environ["INPUT_PR_LIST"]
    download_links_raw = os.environ["INPUT_DOWNLOAD_LINKS"]
    release_info = os.environ.get("INPUT_RELEASE_INFO", "").strip()
    download_links_format = parse_download_links_format(
        os.environ.get("INPUT_DOWNLOAD_LINKS_FORMAT", "")
    )
    date = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    bot_url = os.environ["INPUT_BOT_URL"].rstrip("/")
    bot_token = os.environ["INPUT_BOT_API_TOKEN"]
    telegram_chat_ids = parse_comma_list(os.environ.get("INPUT_TELEGRAM_CHAT_IDS", ""))
    telegram_thread_id = os.environ.get("INPUT_TELEGRAM_THREAD_ID", "")
    matrix_room_ids = parse_comma_list(os.environ.get("INPUT_MATRIX_ROOM_IDS", ""))
    retry_count = parse_retry_count(os.environ.get("INPUT_RETRY_COUNT", ""))
    retry_delay = parse_retry_delay(os.environ.get("INPUT_RETRY_DELAY", ""))
    request_timeout = parse_request_timeout(os.environ.get("INPUT_REQUEST_TIMEOUT", ""))

    if not telegram_chat_ids and not matrix_room_ids:
        print("::error::At least one of telegram_chat_ids or matrix_room_ids must be provided")
        sys.exit(1)

    # Prepare template data
    prs = parse_pr_list(pr_list_raw)
    downloads = parse_download_links(download_links_raw)

    template_ctx = {
        "platform": platform,
        "date": date,
        "release_info": release_info,
        "release_info_lines": release_info.splitlines(),
        "prs": prs,
        "downloads": downloads,
        "download_links_format": download_links_format,
    }

    # Load Jinja2 templates
    templates_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(templates_dir),
        autoescape=False,
        keep_trailing_newline=False,
    )

    failures = []

    # Send to Telegram
    if telegram_chat_ids:
        template = env.get_template("telegram.html.j2")
        message = template.render(**template_ctx).strip()

        print("--- Telegram HTML ---")
        print(message)
        print("--- end ---")

        for chat_id in telegram_chat_ids:
            if not send_telegram(
                bot_url, bot_token, chat_id, message, telegram_thread_id,
                retry_count=retry_count,
                retry_delay=retry_delay,
                request_timeout=request_timeout,
            ):
                failures.append(f"Telegram [{chat_id}]")

    # Send to Matrix
    if matrix_room_ids:
        html_template = env.get_template("matrix.html.j2")
        plain_template = env.get_template("matrix_plain.txt.j2")

        html_message = html_template.render(**template_ctx).strip()
        plain_message = plain_template.render(**template_ctx).strip()

        print("--- Matrix HTML ---")
        print(html_message)
        print("--- end ---")

        for room_id in matrix_room_ids:
            if not send_matrix(
                bot_url, bot_token, room_id, plain_message, html_message,
                retry_count=retry_count,
                retry_delay=retry_delay,
                request_timeout=request_timeout,
            ):
                failures.append(f"Matrix [{room_id}]")

    if failures:
        print(f"::error::Failed to deliver to: {', '.join(failures)}")
        sys.exit(1)

    print("Done.")


if __name__ == "__main__":
    main()
