# Collect Merged PRs

A composite GitHub Action that collects merged pull requests within a specified time window and generates release notes.

## Usage

```yaml
- name: Collect merged PRs
  id: collect-prs
  uses: novasamatech/github-actions/collect-prs@v1
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    base_branch: 'main'
```

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `github_token` | Yes | - | GitHub token for API access |
| `base_branch` | Yes | - | Target branch to filter PRs (only PRs merged into this branch will be collected) |
| `since` | No | last 24 hours | Collect PRs merged after this timestamp (ISO 8601 format, e.g. `2025-01-20T12:00:00Z`) |
| `release_title` | No | - | Title template for release notes. Supports placeholders: `{date}`, `{version_name}`, `{version_code}` |
| `version_name` | No | - | Version name to include in release notes |
| `version_code` | No | - | Version code to include in release notes |

## Outputs

| Output | Description |
|--------|-------------|
| `should_build` | Whether there are merged PRs to build (`true`/`false`) |
| `release_notes` | Generated release notes from merged PRs |
| `pr_count` | Number of merged PRs found |
| `pr_numbers` | Comma-separated list of merged PR numbers |

## Examples

### Basic usage (last 24 hours)

```yaml
jobs:
  check-prs:
    runs-on: ubuntu-latest
    outputs:
      should_build: ${{ steps.collect.outputs.should_build }}
      release_notes: ${{ steps.collect.outputs.release_notes }}
    steps:
      - name: Collect merged PRs
        id: collect
        uses: novasamatech/github-actions/collect-prs@v1
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          base_branch: 'main'

      - name: Build if PRs were merged
        if: steps.collect.outputs.should_build == 'true'
        run: echo "Building with ${{ steps.collect.outputs.pr_count }} merged PRs"
```

### Custom time window (since specific date)

```yaml
- name: Collect merged PRs since specific date
  id: collect
  uses: novasamatech/github-actions/collect-prs@v1
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    base_branch: 'develop'
    since: '2025-01-15T00:00:00Z'
```

### With release title template

```yaml
- name: Collect merged PRs
  id: collect
  uses: novasamatech/github-actions/collect-prs@v1
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    base_branch: 'main'
    release_title: 'Nightly {date} (version {version_name} code {version_code})'
    version_name: '1.2.3'
    version_code: '456'
```

This will generate release notes like:

```
Nightly 2025-01-20 (version 1.2.3 code 456)

Merged pull requests:
- #123: Add new feature https://github.com/novasamatech/repo-name/pull/123
- #124: Fix bug in login https://github.com/novasamatech/repo-name/pull/124
```

### Nightly build workflow

```yaml
name: Nightly Build

on:
  schedule:
    - cron: '0 2 * * *'

jobs:
  check:
    runs-on: ubuntu-latest
    outputs:
      should_build: ${{ steps.meta.outputs.should_build }}
      release_notes: ${{ steps.meta.outputs.release_notes }}
    steps:
      - name: Collect merged PRs
        id: meta
        uses: novasamatech/github-actions/collect-prs@v1
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          base_branch: 'main'
          release_title: 'Nightly {date}'

  build:
    needs: check
    if: needs.check.outputs.should_build == 'true'
    runs-on: ubuntu-latest
    steps:
      - name: Build
        run: echo "Building nightly..."

      - name: Create release
        uses: softprops/action-gh-release@v1
        with:
          body: ${{ needs.check.outputs.release_notes }}
          tag_name: nightly-${{ github.run_id }}
          prerelease: true
```
