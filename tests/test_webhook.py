"""Tests for the GitHub webhook endpoint."""
import hashlib
import hmac
import json
import os

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_PAYLOAD = {
    "action": "opened",
    "issue": {
        "number": 42,
        "title": "App crashes on startup",
        "body": "The app fails to start on Windows 11.",
    },
    "repository": {
        "full_name": "owner/repo",
    },
}


def _sign(payload_bytes: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _post(payload: dict, headers: dict | None = None) -> object:
    body = json.dumps(payload).encode()
    base_headers = {"x-github-event": "issues", "content-type": "application/json"}
    if headers:
        base_headers.update(headers)
    return client.post("/webhooks/github", content=body, headers=base_headers)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_webhook_opened_issue_returns_200():
    response = _post(SAMPLE_PAYLOAD)
    assert response.status_code == 200


def test_webhook_response_contains_triage():
    response = _post(SAMPLE_PAYLOAD)
    data = response.json()
    assert "triage" in data
    assert data["triage"]["category"] == "Bug"


def test_webhook_response_fields():
    response = _post(SAMPLE_PAYLOAD)
    data = response.json()
    assert data["repo"] == "owner/repo"
    assert data["issue_number"] == 42
    assert data["issue_title"] == "App crashes on startup"
    assert data["received_event"] == "issues"


def test_webhook_empty_body_defaults_to_empty_string():
    payload = {**SAMPLE_PAYLOAD, "issue": {**SAMPLE_PAYLOAD["issue"], "body": None}}
    response = _post(payload)
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Non-opened actions are gracefully ignored (not errors)
# ---------------------------------------------------------------------------

def test_non_opened_action_returns_200():
    payload = {**SAMPLE_PAYLOAD, "action": "closed"}
    response = _post(payload)
    assert response.status_code == 200
    assert "ignored" in response.json().get("detail", "").lower() or "action" in response.json()


# ---------------------------------------------------------------------------
# Missing / bad headers
# ---------------------------------------------------------------------------

def test_missing_github_event_header_returns_400():
    body = json.dumps(SAMPLE_PAYLOAD).encode()
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400


def test_unsupported_event_type_returns_400():
    response = _post(SAMPLE_PAYLOAD, headers={"x-github-event": "push"})
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Payload validation
# ---------------------------------------------------------------------------

def test_missing_issue_field_returns_400():
    payload = {"action": "opened", "repository": {"full_name": "owner/repo"}}
    response = _post(payload)
    assert response.status_code == 400


def test_missing_repository_field_returns_400():
    payload = {"action": "opened", "issue": {"number": 1, "title": "Bug", "body": ""}}
    response = _post(payload)
    assert response.status_code == 400


def test_missing_issue_number_returns_400():
    payload = {
        "action": "opened",
        "issue": {"title": "Bug", "body": ""},
        "repository": {"full_name": "owner/repo"},
    }
    response = _post(payload)
    assert response.status_code == 400


def test_missing_issue_title_returns_400():
    payload = {
        "action": "opened",
        "issue": {"number": 1, "body": ""},
        "repository": {"full_name": "owner/repo"},
    }
    response = _post(payload)
    assert response.status_code == 400


def test_invalid_json_returns_400():
    response = client.post(
        "/webhooks/github",
        content=b"not-json",
        headers={"x-github-event": "issues", "content-type": "application/json"},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Webhook signature verification
# ---------------------------------------------------------------------------

class TestSignatureVerification:
    SECRET = "super-secret"

    def setup_method(self):
        os.environ["GITHUB_WEBHOOK_SECRET"] = self.SECRET

    def teardown_method(self):
        os.environ.pop("GITHUB_WEBHOOK_SECRET", None)

    def _signed_post(self, payload: dict, secret: str | None = None) -> object:
        body = json.dumps(payload).encode()
        sig = _sign(body, secret or self.SECRET)
        return client.post(
            "/webhooks/github",
            content=body,
            headers={
                "x-github-event": "issues",
                "content-type": "application/json",
                "x-hub-signature-256": sig,
            },
        )

    def test_valid_signature_passes(self):
        response = self._signed_post(SAMPLE_PAYLOAD)
        assert response.status_code == 200

    def test_invalid_signature_returns_401(self):
        body = json.dumps(SAMPLE_PAYLOAD).encode()
        response = client.post(
            "/webhooks/github",
            content=body,
            headers={
                "x-github-event": "issues",
                "content-type": "application/json",
                "x-hub-signature-256": "sha256=invalidsignature",
            },
        )
        assert response.status_code == 401

    def test_missing_signature_header_returns_400(self):
        body = json.dumps(SAMPLE_PAYLOAD).encode()
        response = client.post(
            "/webhooks/github",
            content=body,
            headers={"x-github-event": "issues", "content-type": "application/json"},
        )
        assert response.status_code == 400

    def test_wrong_secret_returns_401(self):
        response = self._signed_post(SAMPLE_PAYLOAD, secret="wrong-secret")
        assert response.status_code == 401
