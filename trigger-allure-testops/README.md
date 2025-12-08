# Trigger Allure TestOps Action

Trigger Allure TestOps job with specified parameters.

## Usage

```yaml
- uses: novasamatech/github-actions/trigger-allure-testops@v1
  with:
    job_id: '304'
    branch: 'master'
    launch_name: 'iOS TestFlight Tests'
    allure_token: ${{ secrets.ALLURE_TOKEN }}
```

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `job_id` | Yes | `304` | Allure TestOps Job ID |
| `branch` | Yes | `master` | Branch to run tests from |
| `launch_name` | No | `Android Tests` | Launch name in Allure TestOps |
| `allure_endpoint` | No | `https://nova.testops.cloud` | Allure TestOps endpoint URL |
| `allure_token` | Yes | - | Allure TestOps API token |

## Examples

**Basic usage:**
```yaml
- uses: novasamatech/github-actions/trigger-allure-testops@v1
  with:
    job_id: '304'
    branch: 'master'
    allure_token: ${{ secrets.ALLURE_TOKEN }}
```

**Custom launch name:**
```yaml
- uses: novasamatech/github-actions/trigger-allure-testops@v1
  with:
    job_id: '304'
    branch: 'develop'
    launch_name: 'iOS TestFlight Tests'
    allure_token: ${{ secrets.ALLURE_TOKEN }}
```

**Custom endpoint:**
```yaml
- uses: novasamatech/github-actions/trigger-allure-testops@v1
  with:
    job_id: '304'
    branch: 'master'
    allure_endpoint: 'https://custom.testops.cloud'
    allure_token: ${{ secrets.ALLURE_TOKEN }}
```
