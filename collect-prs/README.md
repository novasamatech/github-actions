# Collect Merged PRs

A composite GitHub Action that collects merged pull requests either from the commit diff between two git refs, or by time window on a single branch.

## Usage

### Diff mode (between two refs)

```yaml
- name: Collect merged PRs
  id: collect-prs
  uses: novasamatech/github-actions/collect-prs@v1
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    src_ref: 'feature-branch'
    dst_ref: 'main'
```

### Time mode (last N hours)

```yaml
- name: Collect merged PRs
  id: collect-prs
  uses: novasamatech/github-actions/collect-prs@v1
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    dst_ref: 'main'
```

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `github_token` | Yes | - | GitHub token for API access |
| `src_ref` | No | - | Source ref (branch name or commit SHA). If set, enables diff mode — collects PRs from commits between `dst_ref` and `src_ref` |
| `dst_ref` | Yes | - | Destination ref (branch name). In diff mode used as comparison base. In time mode used as the branch to search merged PRs |
| `hours` | No | `24` | Time window in hours to look back for merged PRs (only used when `src_ref` is not set) |
| `release_notes_format` | No | `plain` | Output format for `release_notes`: `plain` (main-compatible), `plain-ext-v1`, or `csv` (case-insensitive) |
| `timezone` | No | `Europe/Berlin` | IANA timezone used to format merge date (`YYYY-MM-DD`) for `plain-ext-v1` and `csv` |
| `retry_count` | No | `6` | Number of additional attempts for GitHub API calls that fail with transient errors (HTTP `429` or `5xx`). `0` disables retries |
| `retry_delay` | No | `10` | Delay in seconds between retry attempts for GitHub API calls |

## Outputs

| Output | Description |
|--------|-------------|
| `should_build` | Whether there are merged PRs to build (`true`/`false`) |
| `release_notes` | Generated release notes from merged PRs |
| `pr_count` | Number of merged PRs found |
| `pr_numbers` | Comma-separated list of merged PR numbers |

## Examples

### Diff mode — collect PRs between two refs

```yaml
jobs:
  check-prs:
    runs-on: ubuntu-latest
    outputs:
      should_build: ${{ steps.collect.outputs.should_build }}
      release_notes: ${{ steps.collect.outputs.release_notes }}
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Collect merged PRs
        id: collect
        uses: novasamatech/github-actions/collect-prs@v1
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          src_ref: 'release/1.0'
          dst_ref: 'main'

      - name: Build if PRs were merged
        if: steps.collect.outputs.should_build == 'true'
        run: echo "Building with ${{ steps.collect.outputs.pr_count }} merged PRs"
```

### Time mode — last 24 hours (default)

```yaml
- name: Collect merged PRs
  id: collect
  uses: novasamatech/github-actions/collect-prs@v1
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    dst_ref: 'main'
```

### Time mode — custom time window

```yaml
- name: Collect merged PRs (last 48 hours)
  id: collect
  uses: novasamatech/github-actions/collect-prs@v1
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    dst_ref: 'main'
    hours: '48'
```

### Output format

#### `plain` (default, main-compatible)

```
- #123: Add new feature https://github.com/novasamatech/repo-name/pull/123
- #124: Fix bug in login https://github.com/novasamatech/repo-name/pull/124
```

Row format:

```
- #PR_NUMBER: PR Title PR Link
```

#### `plain-ext-v1`

```
Add new feature ; https://github.com/novasamatech/repo-name/pull/123 ; octocat(The Octocat) ; 2026-02-18
Fix bug in login ; https://github.com/novasamatech/repo-name/pull/124 ; dev-user() ; 2026-02-18
```

Row format:

```
PR Title ; PR Link ; Author ; Merge Date
```

Author format:

```
handle(name)
```

If the user profile has no name, empty parentheses are preserved:

```
handle()
```

### `plain-ext-v1` example usage

```yaml
- name: Collect merged PRs (plain-ext-v1, CET/CEST)
  id: collect
  uses: novasamatech/github-actions/collect-prs@v1
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    dst_ref: 'main'
    release_notes_format: 'plain-ext-v1'
    timezone: 'Europe/Berlin'
```

#### `csv`

The first row is the header and values are CSV-escaped:

```csv
PR Title,PR Link,Author,Merge Date
Add new feature,https://github.com/novasamatech/repo-name/pull/123,octocat(The Octocat),2026-02-18
```

### CSV example usage

```yaml
- name: Collect merged PRs (CSV, CET/CEST)
  id: collect
  uses: novasamatech/github-actions/collect-prs@v1
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    dst_ref: 'main'
    release_notes_format: 'CSV'
    timezone: 'Europe/Berlin'
```

## Retry behavior

The action retries GitHub API calls that fail with transient errors:

- HTTP `429` (rate limited)
- HTTP `5xx` (server errors)

`4xx` responses other than `429` and errors without a numeric HTTP status are not retried and surface immediately. The same retry budget applies separately to every wrapped API call (PR list pagination, per-commit PR lookup in diff mode, and per-author profile lookup).

When the author profile lookup (`users.getByUsername`) exhausts its retries, the action keeps the PR but renders the author as `handle()` rather than failing the workflow — matching the existing behavior on non-retriable lookup errors.

## Development

### Run tests

Tests use Node's built-in test runner (`node:test`) and can be run locally:

```bash
cd collect-prs
node --test src/run.test.js
```
