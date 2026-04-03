import os

import httpx

from app.models.triage import TriageResult

GITHUB_API_BASE = "https://api.github.com"


def _headers() -> dict[str, str]:
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN environment variable is not set")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _build_triage_comment(result: TriageResult) -> str:
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
        f"| Field | Value |\n"
        f"|---|---|\n"
        f"| **Category** | {category_emoji} {result.category} |\n"
        f"| **Priority** | {priority_emoji} {result.priority} |\n"
        f"| **Suggested Labels** | {labels_md} |\n\n"
        f"**Reason:** {result.reason}\n\n"
        "_This triage was performed automatically. A maintainer will review shortly._"
    )


async def post_triage_comment(repo: str, issue_number: int, result: TriageResult) -> None:
    """Post a triage summary comment on the GitHub issue."""
    url = f"{GITHUB_API_BASE}/repos/{repo}/issues/{issue_number}/comments"
    comment_body = _build_triage_comment(result)
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=_headers(), json={"body": comment_body})
        response.raise_for_status()


async def apply_labels(repo: str, issue_number: int, labels: list[str]) -> None:
    """Apply labels to a GitHub issue, creating any that don't exist yet."""
    await _ensure_labels_exist(repo, labels)
    url = f"{GITHUB_API_BASE}/repos/{repo}/issues/{issue_number}/labels"
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=_headers(), json={"labels": labels})
        response.raise_for_status()


async def _ensure_labels_exist(repo: str, labels: list[str]) -> None:
    """Create any labels that don't yet exist in the repository."""
    url = f"{GITHUB_API_BASE}/repos/{repo}/labels"
    default_colors: dict[str, str] = {
        "bug": "d73a4a",
        "feature-request": "a2eeef",
        "documentation": "0075ca",
        "question": "d876e3",
        "other": "e4e669",
        "priority-high": "b60205",
        "priority-medium": "fbca04",
        "priority-low": "0e8a16",
    }

    async with httpx.AsyncClient() as client:
        existing_resp = await client.get(url, headers=_headers(), params={"per_page": 100})
        existing_resp.raise_for_status()
        existing_names = {lbl["name"] for lbl in existing_resp.json()}

        for label in labels:
            if label not in existing_names:
                color = default_colors.get(label, "ededed")
                await client.post(
                    url,
                    headers=_headers(),
                    json={"name": label, "color": color},
                )
