# Send Notification

Sends an arbitrary message to **Telegram** and/or **Matrix** via an external notification bot service.

Unlike `send-release-notification`, this action accepts pre-formatted messages directly — no templates or PR parsing involved.

## Usage

```yaml
- name: Send failure notification
  uses: ./.github/actions/send-notification
  with:
    message: |
      Build failed
      Branch: main
      Run: https://github.com/org/repo/actions/runs/123
    html_message: |
      <b>Build failed</b>
      Branch: <code>main</code>
      <a href="https://github.com/org/repo/actions/runs/123">View run</a>
    bot_url: ${{ secrets.NOTIFICATION_BOT_URL }}
    bot_api_token: ${{ secrets.NOTIFICATION_BOT_TOKEN }}
    telegram_chat_ids: "-100500:42, -100501"
    matrix_room_ids: "!room1:matrix.org, !room2:matrix.org"
```

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `message` | yes | — | Plain text message |
| `html_message` | no | `""` | HTML-formatted message (falls back to `message` if empty) |
| `bot_url` | yes | — | Notification bot base URL |
| `bot_api_token` | yes | — | API token for the notification bot service |
| `telegram_chat_ids` | no | `""` | Comma-separated Telegram destinations: `chat_id` or `chat_id:thread_id` |
| `matrix_room_ids` | no | `""` | Comma-separated Matrix room IDs |

At least one of `telegram_chat_ids` or `matrix_room_ids` must be provided.

### Telegram destination format

Each entry in `telegram_chat_ids` can be:

- `chat_id` — send to the chat's main thread
- `chat_id:thread_id` — send to a specific forum topic (thread)

Examples:
```yaml
# Single chat, no thread
telegram_chat_ids: "-100500"

# Single chat with thread
telegram_chat_ids: "-100500:42"

# Multiple destinations with different threads
telegram_chat_ids: "-100500:42, -100501:99, -100502"
```

## How it works

1. Reads `message` and optional `html_message` from inputs
2. If `html_message` is empty, uses `message` for both plain and HTML delivery
3. Sends HTTP POST requests to the notification bot API for each destination:
   - **Telegram**: `POST /telegram/send/{chat_id}/{thread_id}` with `Parse-Mode: HTML` header
   - **Matrix**: `POST /matrix/send/{room_id}` with JSON `{text, formatted_text}`
4. Exits with error if any delivery fails

## Development

Run tests locally:

```bash
cd .github/actions/send-notification
pip install pytest
pytest test_send.py -v
```
