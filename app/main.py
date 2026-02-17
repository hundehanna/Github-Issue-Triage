from fastapi import FastAPI

app = FastAPI(title="GitHub Issue Triage")

@app.get("/health")
def health():
    return {"status": "ok"}
