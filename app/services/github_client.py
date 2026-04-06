import logging

import httpx

from app.models.triage import TriageResult

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"

_LABEL_COLORS: dict[str, str] = {
    "bug": "d73a4a",
    "feature-request": "a2eeef",
    "documentation": "0075ca",
    "question": "d876e3",
    "other": "e4e669",
    "priority-high": "b60205",
    "priority-medium": "fbca04",
    "priority-low": "0e8a16",
}


def build_triage_comment(result: TriageResult) -> str:
    """Format a rich triage comment with emojis and a markdown table."""
    priority_emoji = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}.get(result.priority, "⚪")
    category_emoji = {
        "Bug": "🐛",
        "Feature Request": "✨",
        "Documentation": "📄",
        "Question": "❓",
        "Other": "📌",
    }.get(result.category, "📌")
    labels_md = ", ".join(f"`{lbl}`" for lbl in result.suggested_labels)
    return (
        "## 🤖 Automated Issue Triage\n\n"
        "| Field | Value |\n"
        "|---|---|\n"
        f"| **Category** | {category_emoji} {result.category} |\n"
        f"| **Priority** | {priority_emoji} {result.priority} |\n"
        f"| **Suggested Labels** | {labels_md} |\n\n"
        f"**Reason:** {result.reason}\n\n"
        "_This triage was performed automatically. A maintainer will review shortly._"
    )


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
        """Apply labels to an issue, creating any that don't exist first."""
        self.ensure_labels_exist(repo, labels)
        url = f"{self._base_url}/repos/{repo}/issues/{issue_number}/labels"
        logger.debug("Applying labels %s to %s#%d", labels, repo, issue_number)
        response = self._client.post(url, json={"labels": labels})
        response.raise_for_status()
        return response.json()

    def ensure_labels_exist(self, repo: str, labels: list[str]) -> None:
        """Create any labels that don't yet exist in the repository."""
        url = f"{self._base_url}/repos/{repo}/labels"
        existing_resp = self._client.get(url, params={"per_page": 100})
        existing_resp.raise_for_status()
        existing_names = {lbl["name"] for lbl in existing_resp.json()}
        for label in labels:
            if label not in existing_names:
                color = _LABEL_COLORS.get(label, "ededed")
                self._client.post(url, json={"name": label, "color": color})
                logger.debug("Created label '%s' in %s", label, repo)
