import hashlib
import hmac
import os

from fastapi import FastAPI, Header, HTTPException, Request

from app.services.github_client import post_triage_comment, apply_labels
from app.services.issue_processor import triage_issue

app = FastAPI(title="GitHub Issue Triage")


def _verify_signature(body: bytes, signature_header: str | None) -> None:
    """Validate the X-Hub-Signature-256 header sent by GitHub."""
    secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    if not secret:
        # If no secret is configured, skip verification (useful in local dev).
        return
    if signature_header is None:
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256 header")
    if not signature_header.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Invalid signature format")

    expected = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhooks/github")
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
):
    raw_body = await request.body()
    _verify_signature(raw_body, x_hub_signature_256)

    if x_github_event is None:
        raise HTTPException(status_code=400, detail="Missing GitHub event header")

    if x_github_event != "issues":
        raise HTTPException(status_code=400, detail=f"Unsupported event: {x_github_event}")

    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")

    issue = payload.get("issue")
    repository = payload.get("repository")
    action = payload.get("action")

    if issue is None or repository is None:
        raise HTTPException(status_code=400, detail="Missing required fields: issue or repository")

    if action != "opened":
        raise HTTPException(status_code=400, detail=f"Unsupported action: {action}")

    issue_number = issue.get("number")
    title = issue.get("title")
    body = issue.get("body") or ""
    repo_name = repository.get("full_name")

    if issue_number is None or title is None or repo_name is None:
        raise HTTPException(status_code=400, detail="Missing required issue details")

    triage_result = triage_issue(repo_name, issue_number, title, body)

    await post_triage_comment(repo_name, issue_number, triage_result)
    await apply_labels(repo_name, issue_number, triage_result.suggested_labels)

    return {
        "received_event": x_github_event,
        "repo": repo_name,
        "issue_number": issue_number,
        "issue_title": title,
        "triage": triage_result.model_dump(),
    }
