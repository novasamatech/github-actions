# Find First PR

A composite GitHub Action that finds the first merged PR number in the commit range between two refs.

## Usage

```yaml
- name: Find first PR
  id: first-pr
  uses: novasamatech/github-actions/first-pr@v1
  with:
    github_token: ${{ github.token }}
    src_ref: 'feature-branch'
    dst_ref: 'main'
```

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| `github_token` | Yes | GitHub token for API access |
| `src_ref` | Yes | Source ref (branch name or commit SHA) to start searching from |
| `dst_ref` | Yes | Destination ref (branch name) to compare against |

## Outputs

| Output | Description |
|--------|-------------|
| `pr_number` | The first merged PR number found, or empty string if none found |

## How It Works

1. Resolves the source ref to a commit SHA
2. Gets all commits that are in `src_ref` but not in `dst_ref` (oldest first)
3. Iterates through commits and checks for associated merged PRs
4. Returns the first merged PR number found

## Examples

### Find first PR between feature branch and main

```yaml
jobs:
  find-pr:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Find first PR
        id: first-pr
        uses: novasamatech/github-actions/first-pr@v1
        with:
          github_token: ${{ github.token }}
          src_ref: 'feature-branch'
          dst_ref: 'main'

      - name: Use PR number
        if: steps.first-pr.outputs.pr_number != ''
        run: echo "First PR is #${{ steps.first-pr.outputs.pr_number }}"
```

### Use with collect-prs action

```yaml
jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Find first PR since last release
        id: first-pr
        uses: novasamatech/github-actions/first-pr@v1
        with:
          github_token: ${{ github.token }}
          src_ref: ${{ github.sha }}
          dst_ref: 'main'

      - name: Collect PRs since first PR
        if: steps.first-pr.outputs.pr_number != ''
        id: collect
        uses: novasamatech/github-actions/collect-prs@v1
        with:
          github_token: ${{ github.token }}
          base_branch: 'main'
          since_pr: ${{ steps.first-pr.outputs.pr_number }}
```

## Requirements

- The repository must be checked out with `fetch-depth: 0` to have full git history
- Both source and destination refs must exist in the repository
