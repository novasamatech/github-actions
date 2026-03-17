# Send Release Notification

Sends release changelog notifications to **Telegram** and **Matrix** via an external notification bot service.

Uses Jinja2 templates to render provider-specific HTML: Telegram (inline markup only) and Matrix (rich HTML subset).

## Usage

```yaml
- name: Send release notification
  uses: novasamatech/github-actions/send-release-notification@v3
  with:
    platform: Android
    pr_list: |
      - [#377](https://github.com/org/repo/pull/377): Fix scroll position on rotation
      - [#384](https://github.com/org/repo/pull/384): Fix SSO login redirect
    download_links: |
      Firebase: https://appdistribution.firebase.dev/i/abc123
      APK: https://s3.amazonaws.com/builds/app-release.apk
    bot_url: ${{ secrets.NOTIFICATION_BOT_URL }}
    bot_api_token: ${{ secrets.NOTIFICATION_BOT_TOKEN }}
    telegram_chat_ids: "-100500, -100501"
    telegram_thread_id: "42"
    matrix_room_ids: "!room1:matrix.org, !room2:matrix.org"
```

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `platform` | yes | — | Platform name (e.g., `Android`, `iOS`) |
| `pr_list` | yes | — | Multiline list of merged PRs in markdown format: `- [#N](url): Title` |
| `download_links` | yes | — | Multiline download links (plain text, URLs are auto-linked) |
| `bot_url` | yes | — | Notification bot base URL |
| `bot_api_token` | yes | — | API token for the notification bot service |
| `telegram_chat_ids` | no | `""` | Comma-separated Telegram chat IDs |
| `telegram_thread_id` | no | `""` | Telegram forum topic thread ID (applied to all chats) |
| `matrix_room_ids` | no | `""` | Comma-separated Matrix room IDs |

At least one of `telegram_chat_ids` or `matrix_room_ids` must be provided.

## How it works

1. Parses `pr_list` into structured items with raw text and HTML-linked versions
2. Parses `download_links`, auto-wrapping plain URLs in `<a>` tags
3. Renders provider-specific templates via Jinja2:
   - **Telegram**: inline HTML only (`<b>`, `<a>`, etc.) with literal newlines
   - **Matrix**: rich HTML (`<h3>`, `<ul>`, `<li>`, etc.) + plain-text fallback
4. Sends HTTP POST requests to the notification bot API for each destination
5. Exits with error if any delivery fails

## Templates

Templates are located in [`templates/`](./templates):

- `telegram.html.j2` — Telegram HTML (no block-level tags)
- `matrix.html.j2` — Matrix formatted HTML
- `matrix_plain.txt.j2` — Matrix plain-text fallback

## Development

Run tests locally:

```bash
cd send-release-notification
pip install -r requirements.txt
pytest test_send.py -v
```
