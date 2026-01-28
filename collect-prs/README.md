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

The `release_notes` output will be formatted like:

```
Merged pull requests:
- #123: Add new feature https://github.com/novasamatech/repo-name/pull/123
- #124: Fix bug in login https://github.com/novasamatech/repo-name/pull/124
```
