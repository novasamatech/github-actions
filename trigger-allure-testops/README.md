# Trigger Allure TestOps Action

Trigger an Allure TestOps test plan run.

> **Breaking change in v5:** this action now triggers a **test plan** instead of a job.
> The `job_id` and `branch` inputs have been removed in favor of `testplan_id`.
> The job and branch are taken from the test plan configuration in Allure TestOps.

## Usage

```yaml
- uses: novasamatech/github-actions/trigger-allure-testops@v5
  with:
    testplan_id: '733'
    launch_name: 'Android Tests - Nightly'
    allure_token: ${{ secrets.ALLURE_TOKEN }}
```

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `testplan_id` | Yes | - | Allure TestOps Test Plan ID |
| `launch_name` | No | `Test Run` | Launch name in Allure TestOps |
| `allure_endpoint` | No | `https://nova.testops.cloud` | Allure TestOps endpoint URL |
| `allure_token` | Yes | - | Allure TestOps API token |

## Examples

**Basic usage:**
```yaml
- uses: novasamatech/github-actions/trigger-allure-testops@v5
  with:
    testplan_id: '733'
    allure_token: ${{ secrets.ALLURE_TOKEN }}
```

**Custom launch name:**
```yaml
- uses: novasamatech/github-actions/trigger-allure-testops@v5
  with:
    testplan_id: '733'
    launch_name: 'Android Tests - Nightly 2026-04-06'
    allure_token: ${{ secrets.ALLURE_TOKEN }}
```

**Custom endpoint:**
```yaml
- uses: novasamatech/github-actions/trigger-allure-testops@v5
  with:
    testplan_id: '733'
    allure_endpoint: 'https://custom.testops.cloud'
    allure_token: ${{ secrets.ALLURE_TOKEN }}
```

## Migrating from v4

v4:
```yaml
- uses: novasamatech/github-actions/trigger-allure-testops@v4
  with:
    job_id: '303'
    branch: 'master'
    launch_name: 'Android Tests - Nightly'
    allure_token: ${{ secrets.ALLURE_TOKEN }}
```

v5:
```yaml
- uses: novasamatech/github-actions/trigger-allure-testops@v5
  with:
    testplan_id: '733'
    launch_name: 'Android Tests - Nightly'
    allure_token: ${{ secrets.ALLURE_TOKEN }}
```

Make sure the test plan in Allure TestOps is configured with the correct job and branch — these are no longer passed from the workflow.
