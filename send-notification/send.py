#!/usr/bin/env python3
"""
Send an arbitrary message to Telegram and/or Matrix
via an external notification bot service.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request


def http_post(url: str, headers: dict, body: bytes | str) -> tuple[int, str]:
    if isinstance(body, str):
        body = body.encode("utf-8")

    headers.setdefault(
        "User-Agent",
        "GitHubActions/2.0 (send-notification; +https://github.com)",
    )
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

    url = f"{bot_url}/telegram/send/{chat_id}"
    if thread_id:
        url = f"{url}/{thread_id}"
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


def parse_comma_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def parse_telegram_destinations(value: str) -> list[tuple[str, str]]:
    """Parse comma-separated chat_id[:thread_id] entries.

    Returns list of (chat_id, thread_id) tuples. thread_id is "" if not specified.
    """
    destinations = []
    for entry in parse_comma_list(value):
        if ":" in entry:
            chat_id, thread_id = entry.split(":", 1)
            destinations.append((chat_id.strip(), thread_id.strip()))
        else:
            destinations.append((entry, ""))
    return destinations


def main() -> None:
    message = os.environ["INPUT_MESSAGE"]
    html_message = os.environ.get("INPUT_HTML_MESSAGE", "").strip() or message
    bot_url = os.environ["INPUT_BOT_URL"].rstrip("/")
    bot_token = os.environ["INPUT_BOT_API_TOKEN"]
    telegram_destinations = parse_telegram_destinations(
        os.environ.get("INPUT_TELEGRAM_CHAT_IDS", "")
    )
    matrix_room_ids = parse_comma_list(os.environ.get("INPUT_MATRIX_ROOM_IDS", ""))

    if not telegram_destinations and not matrix_room_ids:
        print("::error::At least one of telegram_chat_ids or matrix_room_ids must be provided")
        sys.exit(1)

    failures = []

    if telegram_destinations:
        for chat_id, thread_id in telegram_destinations:
            if not send_telegram(bot_url, bot_token, chat_id, html_message, thread_id):
                failures.append(f"Telegram [{chat_id}]")

    if matrix_room_ids:
        for room_id in matrix_room_ids:
            if not send_matrix(bot_url, bot_token, room_id, message, html_message):
                failures.append(f"Matrix [{room_id}]")

    if failures:
        print(f"::error::Failed to deliver to: {', '.join(failures)}")
        sys.exit(1)

    print("Done.")


if __name__ == "__main__":
    main()
