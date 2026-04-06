import hashlib
import hmac
import json
import logging
import os

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from app.logging_config import configure_logging
from app.services.github_client import GitHubClient, build_triage_comment
from app.services.issue_processor import triage_issue
from app.services.metrics import metrics

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="GitHub Issue Triage")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _verify_signature(payload_bytes: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub webhook HMAC-SHA256 signature."""
    expected = "sha256=" + hmac.new(
        secret.encode(), payload_bytes, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _format_triage_comment(result) -> str:
    return build_triage_comment(result)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def get_metrics():
    """Return current in-process triage metrics."""
    return metrics.to_dict()


class FeedbackPayload(BaseModel):
    verdict: str  # "correct" | "incorrect" | "overridden"
    note: str = ""


@app.post("/feedback/{repo_owner}/{repo_name}/{issue_number}")
def post_feedback(repo_owner: str, repo_name: str, issue_number: int, body: FeedbackPayload):
    """Record maintainer feedback on a triage result.

    verdict must be one of: correct, incorrect, overridden
    """
    valid = {"correct", "incorrect", "overridden"}
    if body.verdict not in valid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid verdict '{body.verdict}'. Must be one of: {', '.join(sorted(valid))}",
        )
    repo = f"{repo_owner}/{repo_name}"
    logger.info(
        "Feedback received — repo=%s issue=%d verdict=%s note=%r",
        repo,
        issue_number,
        body.verdict,
        body.note,
    )
    metrics.record_feedback(body.verdict)
    return {"repo": repo, "issue_number": issue_number, "verdict": body.verdict, "recorded": True}


@app.post("/webhooks/github")
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
):
    webhook_secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    raw_body = await request.body()

    if webhook_secret:
        if x_hub_signature_256 is None:
            raise HTTPException(status_code=400, detail="Missing signature header")
        if not _verify_signature(raw_body, x_hub_signature_256, webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid signature")

    if x_github_event is None:
        raise HTTPException(status_code=400, detail="Missing GitHub event header")

    if x_github_event != "issues":
        raise HTTPException(status_code=400, detail=f"Unsupported event: {x_github_event}")

    try:
        payload = json.loads(raw_body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")

    issue = payload.get("issue")
    repository = payload.get("repository")
    action = payload.get("action")

    if issue is None or repository is None:
        raise HTTPException(status_code=400, detail="Missing required fields: issue or repository")

    if action != "opened":
        return {"received_event": x_github_event, "action": action, "detail": "Action ignored"}

    issue_number = issue.get("number")
    title = issue.get("title")
    body = issue.get("body") or ""
    repo_name = repository.get("full_name")

    if issue_number is None or title is None or repo_name is None:
        raise HTTPException(status_code=400, detail="Missing required issue details")

    logger.info("Triaging issue #%d in %s", issue_number, repo_name)

    triage_result = triage_issue(repo_name, issue_number, title, body)

    github_token = os.getenv("GITHUB_TOKEN")
    if github_token:
        client = GitHubClient(token=github_token)
        try:
            client.apply_labels(repo_name, issue_number, triage_result.suggested_labels)
            client.post_comment(repo_name, issue_number, _format_triage_comment(triage_result))
            logger.info("Applied labels and posted comment on issue #%d", issue_number)
        except Exception as exc:
            logger.error("GitHub API error for issue #%d: %s", issue_number, exc)

    return {
        "received_event": x_github_event,
        "repo": repo_name,
        "issue_number": issue_number,
        "issue_title": title,
        "triage": triage_result.model_dump(),
    }
