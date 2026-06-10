# Send Release Notification

Sends release changelog notifications to **Telegram** and **Matrix** via an external notification bot service.

Uses Jinja2 templates to render provider-specific HTML: Telegram (inline markup only) and Matrix (rich HTML subset).

## Usage

```yaml
- name: Send release notification
  uses: novasamatech/github-actions/send-release-notification@v3
  with:
    platform: Android
    release_info: |
      Version: 1.2.3
      Build number: 1234
    pr_list: |
      - [#377](https://github.com/org/repo/pull/377): Fix scroll position on rotation
      - [#384](https://github.com/org/repo/pull/384): Fix SSO login redirect
    download_links_format: inline
    download_links: |
      [Firebase](https://appdistribution.firebase.dev/i/e0627763965f4fed)
      [.apk (GitHub)](https://github.com/paritytech/polkadot-app-android-v2/releases)
      [.apk (s3 bucket)](https://polkadot-app-artefacts.s3.fr-par.scw.cloud/android/nightly/polkadot-app.apk)
      [WebPage (user:april)](https://nightly.personhood.dev/)
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
| `release_info` | no | `""` | Multiline plain text rendered after the changelog header and before the PR list |
| `download_links` | yes | — | Multiline download links. Supports Markdown named links and plain entries whose URLs are auto-linked |
| `download_links_format` | no | `list` | Render downloads as one entry per line (`list`) or on one line separated by `, ` (`inline`) |
| `bot_url` | yes | — | Notification bot base URL |
| `bot_api_token` | yes | — | API token for the notification bot service |
| `telegram_chat_ids` | no | `""` | Comma-separated Telegram chat IDs |
| `telegram_thread_id` | no | `""` | Telegram forum topic thread ID (applied to all chats) |
| `matrix_room_ids` | no | `""` | Comma-separated Matrix room IDs |
| `retry_count` | no | `6` | Number of retries after the initial attempt when the bot API call fails with a transport error, HTTP 429, or 5xx |
| `retry_delay` | no | `20` | Fallback delay in seconds between retry attempts when `Retry-After` is not provided |
| `request_timeout` | no | `60` | Per-attempt HTTP socket timeout in seconds |

At least one of `telegram_chat_ids` or `matrix_room_ids` must be provided.

### Download links

Markdown named links render as compact clickable labels in Telegram and Matrix HTML:

```yaml
download_links_format: inline
download_links: |
  [Firebase](https://example.com)
  [.apk (GitHub)](https://github.com/example/releases)
```

The Matrix plain-text fallback strips the Markdown syntax while retaining each URL, for example `Firebase (https://example.com)`. Existing plain entries remain supported:

```yaml
download_links: |
  Firebase: https://example.com
```

### Retry behavior

Each destination (Telegram chat or Matrix room) has its own retry budget. The action retries only on errors that are likely to be transient:

- transport errors (DNS failure, connection refused, timeout)
- HTTP `429 Too Many Requests` (`Retry-After` is honored when provided)
- any HTTP `5xx` server error

Each HTTP attempt has its own socket timeout (`request_timeout`, default `60s`) covering connection setup and blocking reads from the response socket. This is not a strict wall-clock limit for the whole transfer, but if the bot service leaves the client waiting longer than `60s` for connect or response data, the attempt fails and retry logic continues. 4xx responses (authentication errors, malformed requests, etc.) are **not** retried, because they will not succeed without a configuration change.

With the defaults, a single destination can take up to about **9 minutes** in the worst case: `7` attempts (`1` initial + `6` retries) × `60s` timeout, plus `6` waits × `20s`. If the bot returns a longer `Retry-After` value for HTTP `429`, the total time can be longer because that server-provided delay takes precedence over `retry_delay`.

## How it works

1. Parses `pr_list` into structured items with raw text and HTML-linked versions
2. Parses Markdown named links and auto-wraps URLs in existing plain download entries
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

Dependencies are declared at the repository root in [`requirements.txt`](../requirements.txt). Run tests locally:

```bash
# from repo root
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest -q send-release-notification/test_*.py
```
