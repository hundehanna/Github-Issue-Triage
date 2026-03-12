from fastapi import FastAPI, Header, HTTPException, Request

from app.services.issue_processor import triage_issue

app = FastAPI(title="GitHub Issue Triage")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/webhooks/github")
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
):
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

    return {
        "received_event": x_github_event,
        "repo": repo_name,
        "issue_number": issue_number,
        "issue_title": title,
        "triage": triage_result.model_dump(),
    }
