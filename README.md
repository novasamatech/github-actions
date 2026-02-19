# Reusable GitHub Automation

Collection of reusable GitHub workflows and composite actions for CI/CD pipelines.

## Versioning

Version is managed via [`.version`](.version). On every push to `main`, two tags are automatically created/updated:
- Full version tag (for example, `v3.2.0`) that points to a specific release
- Major version tag (for example, `v3`) that tracks the latest release in that major line

Use pinned tags (`@v3.2.0`) for strict reproducibility, or major tags (`@v3`) for automatic non-breaking updates.

## Reusable Workflows

### PR Summary Report

Path:
- `.github/workflows/pr-summary-report.yml`

What it does:
- Collects merged PRs for a reporting window
- Generates human-readable PR summary in job logs and `GITHUB_STEP_SUMMARY`
- Produces CSV output and uploads it as `report` artifact

Window behavior:
- `schedule` run ignores `days`
- for `schedule`, workflow expects execution on the 1st day of month (UTC), otherwise it fails
- `schedule` window is calculated as: full previous month in hours + hours elapsed since `00:00 UTC` of current day
- any other run type: `days * 24` hours

Inputs:
- `days` (optional, default `30`): lookback in days for non-scheduled runs

Complete caller workflow example (in another repository):

```yaml
name: PR Summary Report

on:
  workflow_dispatch:
    inputs:
      days:
        description: Number of days to look back for merged PRs
        required: false
        default: 30
        type: number
  schedule:
    - cron: "0 7 1 * *"

jobs:
  pr-summary:
    uses: novasamatech/github-actions/.github/workflows/pr-summary-report.yml@v3
    with:
      days: ${{ fromJSON(github.event.inputs.days || '30') }}
    secrets: inherit
```

## Composite Actions

| Action | Path | Description |
|---|---|---|
| Collect Merged PRs | [`collect-prs`](./collect-prs) | Collects merged PRs either from commit diff (`src_ref`/`dst_ref`) or by time window on a branch, with multiple release notes formats. |
| Upload to S3 | [`s3-upload`](./s3-upload) | Uploads file or directory to S3-compatible storage (via `s3cmd`) and returns uploaded path. |
| Trigger Allure TestOps Job | [`trigger-allure-testops`](./trigger-allure-testops) | Authenticates in Allure TestOps and starts a job run with branch and launch parameters. |

## License

This project is licensed under the [Apache License 2.0](LICENSE).
