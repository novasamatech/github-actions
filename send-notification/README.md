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
| `retry_count` | no | `6` | Number of retries after the initial attempt when the bot API call fails with a transport error, HTTP 429, or 5xx |
| `retry_delay` | no | `20` | Fallback delay in seconds between retry attempts when `Retry-After` is not provided |
| `request_timeout` | no | `60` | Per-attempt HTTP socket timeout in seconds |

At least one of `telegram_chat_ids` or `matrix_room_ids` must be provided.

### Retry behavior

Each destination (Telegram chat or Matrix room) has its own retry budget. The action retries only on errors that are likely to be transient:

- transport errors (DNS failure, connection refused, timeout)
- HTTP `429 Too Many Requests` (`Retry-After` is honored when provided)
- any HTTP `5xx` server error

Each HTTP attempt has its own socket timeout (`request_timeout`, default `60s`) covering connection setup and blocking reads from the response socket. This is not a strict wall-clock limit for the whole transfer, but if the bot service leaves the client waiting longer than `60s` for connect or response data, the attempt fails and retry logic continues. 4xx responses (authentication errors, malformed requests, etc.) are **not** retried, because they will not succeed without a configuration change.

With the defaults, a single destination can take up to about **9 minutes** in the worst case: `7` attempts (`1` initial + `6` retries) × `60s` timeout, plus `6` waits × `20s`. If the bot returns a longer `Retry-After` value for HTTP `429`, the total time can be longer because that server-provided delay takes precedence over `retry_delay`.

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

Dependencies are declared at the repository root in [`requirements.txt`](../requirements.txt). Run tests locally:

```bash
# from repo root
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd send-notification
pytest test_*.py -v
```
