# GitHub Issue Triage

A FastAPI application for automatically triaging GitHub issues using webhooks.

## Features

- Health check endpoint (`/health`)
- GitHub webhook endpoint (`/webhooks/github`) for receiving issue events

## Development

### Prerequisites

- Python >= 3.13
- Dependencies managed via `uv` (see `pyproject.toml`)

### Running Locally

```bash
# Install dependencies
uv sync

# Run the application
uvicorn app.main:app --reload
```

## Branching Strategy

This repository uses **`main`** as the default branch for all development and releases.

- **`main`**: Primary branch - all changes should be merged here
- Feature branches should be created from `main` and merged back via Pull Requests

**Note**: A legacy `master` branch existed with some historical changes, but all code has been consolidated into `main`. Please use `main` for all future work.
