# AGENTS Guide

This repository contains reusable GitHub composite actions. Each action lives in its own top-level directory.

## Repository layout

- `collect-prs/`
- `s3-upload/`
- `send-notification/`
- `send-release-notification/`
- `trigger-allure-testops/`
- `.github/workflows/` contains per-action PR checks and shared repository workflows.

Current action metadata files:

- `collect-prs/action.yml`
- `s3-upload/action.yml`
- `send-notification/action.yml`
- `send-release-notification/action.yaml`
- `trigger-allure-testops/action.yml`

## Python actions

Only these actions currently contain Python code and tests:

- `send-notification/`
- `send-release-notification/`

Shared pinned Python dependencies live in the repository root `requirements.txt`.

## Python environment rules

Always use the root virtual environment `.venv` for Python work in this repository.

- Preferred interpreter: `.venv/bin/python`
- Preferred pip: `.venv/bin/pip`
- Preferred pytest: `.venv/bin/pytest`

Do not create per-action virtual environments. Do not rely on system `python`, `pip`, or `pytest` when working on repository Python code.

If `.venv` is missing, create it from the repository root and install the shared dependencies:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Use the root pinned dependencies for every Python run:

```bash
.venv/bin/python send-notification/send.py
.venv/bin/pytest -q send-notification/test_*.py
```

## Testing requirements

Any behavior change in Python code must be covered by tests in the same change.

Minimum expectations:

- Add or update unit tests for every new input, branch, retry rule, timeout rule, parser rule, or failure mode.
- Cover both success and failure paths for external delivery logic.
- Cover `main()` integration for new environment variables and argument propagation.
- Cover invalid and edge-case input values for new numeric/string parsing.
- If a change affects both Python actions, update tests in both suites.
- If action defaults change, update tests so they verify the Python constants against the action metadata defaults.

Required test runs after Python changes:

```bash
.venv/bin/pytest -q send-notification/test_*.py
.venv/bin/pytest -q send-release-notification/test_*.py
```

If the change can affect shared Python behavior, run the combined root-level check too:

```bash
.venv/bin/pytest -q send-notification/test_*.py send-release-notification/test_*.py
```

## Sync requirements

When changing Python action behavior, keep these in sync when applicable:

- implementation in `send.py`
- action inputs/defaults in `action.yml` or `action.yaml`
- action README
- root `README.md` if developer workflow changes
- `CHANGELOG.md` for user-visible behavior changes

Examples that require synchronized updates:

- new action input
- changed default value
- retry behavior changes
- timeout behavior changes
- dependency changes in `requirements.txt`
- test command changes

## Workflow conventions

- Each action has a PR workflow in `.github/workflows/<action-directory-name>-prs.yml`.
- Workflow `name:` should follow `<action-directory-name> PR checks`.
- Python PR workflows should install dependencies from the root `requirements.txt`.

## Notes for future agents

- The repository-wide Python dependency source of truth is `requirements.txt` in the repo root.
- Root-level combined pytest collection must work; avoid duplicate test module naming that breaks collection.
- For Python tests in this repo, prefer file names matching `test_*.py`.
