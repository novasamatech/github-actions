#!/usr/bin/env python3
"""
Render and send build changelog notifications to Telegram and Matrix
via an external notification bot service.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader


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
        items.append({
            "raw": line,
            "linked": linkify_urls(line),
        })
    return items


def parse_comma_list(value: str) -> list[str]:
    """Split comma-separated string into a list of non-empty stripped values."""
    return [v.strip() for v in value.split(",") if v.strip()]


# ---------------------------------------------------------------------------
# HTTP sender
# ---------------------------------------------------------------------------

def http_post(url: str, headers: dict, body: bytes | str) -> tuple[int, str]:
    """Send HTTP POST and return (status_code, response_body)."""
    if isinstance(body, str):
        body = body.encode("utf-8")

    headers.setdefault("User-Agent", "GitHubActions/2.0 (send-notification; +https://github.com)")
    headers.setdefault("Accept", "application/json, text/plain, */*")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        return 0, str(e.reason)


def send_telegram(
    bot_url: str,
    token: str,
    chat_id: str,
    message: str,
    thread_id: str = "",
) -> bool:
    headers = {
        "Authorization": token,
        "Parse-Mode": "HTML",
    }
    if thread_id:
        headers["X-Thread-ID"] = thread_id

    url = f"{bot_url}/telegram/send/{chat_id}"
    code, resp = http_post(url, headers, message)

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
) -> bool:
    encoded_room = urllib.parse.quote(room_id, safe="")
    url = f"{bot_url}/matrix/send/{encoded_room}"
    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
    }
    payload = json.dumps({"text": plain_text, "formatted_text": html})
    code, resp = http_post(url, headers, payload)

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
    date = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    bot_url = os.environ["INPUT_BOT_URL"].rstrip("/")
    bot_token = os.environ["INPUT_BOT_API_TOKEN"]
    telegram_chat_ids = parse_comma_list(os.environ.get("INPUT_TELEGRAM_CHAT_IDS", ""))
    telegram_thread_id = os.environ.get("INPUT_TELEGRAM_THREAD_ID", "")
    matrix_room_ids = parse_comma_list(os.environ.get("INPUT_MATRIX_ROOM_IDS", ""))

    if not telegram_chat_ids and not matrix_room_ids:
        print("::error::At least one of telegram_chat_ids or matrix_room_ids must be provided")
        sys.exit(1)

    # Prepare template data
    prs = parse_pr_list(pr_list_raw)
    downloads = parse_download_links(download_links_raw)

    template_ctx = {
        "platform": platform,
        "date": date,
        "prs": prs,
        "downloads": downloads,
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
            if not send_telegram(bot_url, bot_token, chat_id, message, telegram_thread_id):
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
            if not send_matrix(bot_url, bot_token, room_id, plain_message, html_message):
                failures.append(f"Matrix [{room_id}]")

    if failures:
        print(f"::error::Failed to deliver to: {', '.join(failures)}")
        sys.exit(1)

    print("Done.")


if __name__ == "__main__":
    main()
