# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v5.4.0] - 2026-06-10

### Added
- `send-release-notification`: optional multiline `release_info`, Markdown named download links, and the `download_links_format` input for compact inline download links. Existing plain download entries and list rendering remain supported, while Matrix plain-text fallbacks retain URLs without Markdown syntax.

## [v5.3.0] - 2026-05-26

### Added
- `collect-prs`: retry logic around GitHub API calls. Retries on HTTP `429` and `5xx` responses; `4xx` and errors without a numeric HTTP status are not retried. New inputs `retry_count` (default `6`) and `retry_delay` in seconds (default `10`). The retry budget is applied independently to each wrapped call: PR list pagination, per-commit PR lookup in diff mode, and per-author profile lookup (`users.getByUsername`). When the author profile lookup exhausts its retries the action keeps the PR and renders the author as `handle()` rather than failing the workflow.
- Extensive unit tests covering the retry path: `isRetriableError` classification, the `withRetry` wrapper (success, `5xx`/`429` retries, `4xx` short-circuit, exhaustion, zero retries, sleep-delay propagation), `runAction` retry behavior for paginate, commit lookup, and user lookup, retry-input parsing (defaults, overrides, invalid values), and a check that the `DEFAULT_RETRY_COUNT` / `DEFAULT_RETRY_DELAY` constants match the action metadata defaults.

## [v5.2.0] - 2026-04-22

### Added
- `send-notification`: retry logic around the notification bot API calls. Retries on transport errors, HTTP `429`, and `5xx` responses; `4xx` responses are not retried. New inputs `retry_count` (default `6`), `retry_delay` in seconds (default `20`), and `request_timeout` in seconds (default `60`). HTTP `429` honors `Retry-After` when the bot provides it. Each destination (Telegram chat or Matrix room) has its own retry budget.
- `send-release-notification`: same retry logic and inputs (`retry_count`, `retry_delay`, `request_timeout`) as `send-notification`, including `Retry-After` handling for HTTP `429`.
- Root `requirements.txt`: single shared, pinned Python dependency set used by all Python-based actions (currently `send-notification` and `send-release-notification`) and by CI.
- Root `README.md`: "Python development setup" section describing how to create a virtualenv, install from the shared `requirements.txt`, run tests, and upgrade dependencies.
- Action `README.md` files: documented the new `retry_count` / `retry_delay` / `request_timeout` inputs and described the retry behavior, including `Retry-After` for HTTP `429`; development instructions point to the shared root `requirements.txt`.
- Extensive unit tests covering the retry path: `should_retry` classification, the retry wrapper (success, `5xx`/`429`/transport retries, `4xx` short-circuit, exhaustion, zero/negative counts, `Retry-After`, timeout propagation, sleep-delay propagation), `send_telegram` / `send_matrix` retry behavior, and `main()` integration (defaults, overrides, invalid values, per-destination budgets).

### Changed
- CI workflows `.github/workflows/send-notification-prs.yml` and `.github/workflows/send-release-notification-prs.yml` now install Python dependencies via `pip install -r requirements.txt` (root). Their `paths:` triggers were extended so that a change to the root `requirements.txt` re-runs the relevant checks.

### Removed
- `send-release-notification/requirements.txt` — superseded by the shared root `requirements.txt`.
