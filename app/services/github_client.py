import logging

import httpx

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


class GitHubClient:
    """Minimal GitHub API client for issue triage operations."""

    def __init__(
        self,
        token: str,
        base_url: str = GITHUB_API_BASE,
        _client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._client = _client or httpx.Client(headers=headers)

    def post_comment(self, repo: str, issue_number: int, body: str) -> dict:
        """Post a comment on an issue. Returns the created comment object."""
        url = f"{self._base_url}/repos/{repo}/issues/{issue_number}/comments"
        logger.debug("POST comment on %s#%d", repo, issue_number)
        response = self._client.post(url, json={"body": body})
        response.raise_for_status()
        return response.json()

    def apply_labels(self, repo: str, issue_number: int, labels: list[str]) -> dict:
        """Apply labels to an issue. Returns the updated labels list."""
        url = f"{self._base_url}/repos/{repo}/issues/{issue_number}/labels"
        logger.debug("Applying labels %s to %s#%d", labels, repo, issue_number)
        response = self._client.post(url, json={"labels": labels})
        response.raise_for_status()
        return response.json()
