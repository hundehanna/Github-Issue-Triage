from fastapi import FastAPI, Header, Request, HTTPException

app = FastAPI(title="GitHub Issue Triage")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/webhooks/github")
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
):
    payload = await request.json()

    # For now, just echo event type + a couple useful fields for debugging
    issue = payload.get("issue", {})
    repo = payload.get("repository", {})

    return {
        "received_event": x_github_event,
        "repo": repo.get("full_name"),
        "issue_number": issue.get("number"),
        "issue_title": issue.get("title"),
    }
