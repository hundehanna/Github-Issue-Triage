"""Tests for the GitHubClient service."""
import json

import httpx
import pytest

from app.services.github_client import GitHubClient, GITHUB_API_BASE


# ---------------------------------------------------------------------------
# Mock transport helpers
# ---------------------------------------------------------------------------

class _MockTransport(httpx.BaseTransport):
    """Minimal HTTPX transport that captures requests and returns a canned response."""

    def __init__(self, status_code: int, body: object):
        self.status_code = status_code
        self.body = body
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            status_code=self.status_code,
            headers={"content-type": "application/json"},
            content=json.dumps(self.body).encode(),
            request=request,
        )


def _make_client(status_code: int, body: object, token: str = "fake-token", base_url: str = GITHUB_API_BASE):
    transport = _MockTransport(status_code, body)
    http_client = httpx.Client(
        transport=transport,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    return GitHubClient(token=token, base_url=base_url, _client=http_client), transport


# ---------------------------------------------------------------------------
# post_comment
# ---------------------------------------------------------------------------

class TestPostComment:
    def test_calls_correct_url(self):
        client, transport = _make_client(201, {"id": 1, "body": "Hello!"})
        client.post_comment("owner/repo", 7, "Hello!")
        req = transport.requests[0]
        assert req.url == f"{GITHUB_API_BASE}/repos/owner/repo/issues/7/comments"

    def test_sends_correct_body(self):
        client, transport = _make_client(201, {"id": 1})
        client.post_comment("owner/repo", 7, "Test comment")
        req = transport.requests[0]
        assert json.loads(req.content) == {"body": "Test comment"}

    def test_uses_post_method(self):
        client, transport = _make_client(201, {"id": 1})
        client.post_comment("owner/repo", 1, "hi")
        assert transport.requests[0].method == "POST"

    def test_includes_auth_header(self):
        client, transport = _make_client(201, {"id": 1}, token="my-token")
        client.post_comment("owner/repo", 1, "test")
        req = transport.requests[0]
        assert req.headers.get("Authorization") == "Bearer my-token"

    def test_includes_github_api_version_header(self):
        client, transport = _make_client(201, {"id": 1})
        client.post_comment("owner/repo", 1, "test")
        req = transport.requests[0]
        assert req.headers.get("X-GitHub-Api-Version") == "2022-11-28"

    def test_returns_response_json(self):
        expected = {"id": 99, "body": "Automated triage"}
        client, _ = _make_client(201, expected)
        result = client.post_comment("owner/repo", 1, "Automated triage")
        assert result == expected

    def test_raises_on_404(self):
        client, _ = _make_client(404, {"message": "Not Found"})
        with pytest.raises(httpx.HTTPStatusError):
            client.post_comment("owner/repo", 999, "hello")

    def test_raises_on_401(self):
        client, _ = _make_client(401, {"message": "Bad credentials"})
        with pytest.raises(httpx.HTTPStatusError):
            client.post_comment("owner/repo", 1, "hello")


# ---------------------------------------------------------------------------
# apply_labels
# ---------------------------------------------------------------------------

class TestApplyLabels:
    def test_calls_correct_url(self):
        client, transport = _make_client(200, [{"name": "bug"}])
        client.apply_labels("owner/repo", 7, ["bug"])
        req = transport.requests[0]
        assert req.url == f"{GITHUB_API_BASE}/repos/owner/repo/issues/7/labels"

    def test_sends_correct_body(self):
        client, transport = _make_client(200, [])
        client.apply_labels("owner/repo", 1, ["bug", "priority-high"])
        req = transport.requests[0]
        assert json.loads(req.content) == {"labels": ["bug", "priority-high"]}

    def test_uses_post_method(self):
        client, transport = _make_client(200, [])
        client.apply_labels("owner/repo", 1, ["bug"])
        assert transport.requests[0].method == "POST"

    def test_returns_response_json(self):
        expected = [{"name": "bug"}, {"name": "priority-high"}]
        client, _ = _make_client(200, expected)
        result = client.apply_labels("owner/repo", 1, ["bug", "priority-high"])
        assert result == expected

    def test_raises_on_422(self):
        client, _ = _make_client(422, {"message": "Validation Failed"})
        with pytest.raises(httpx.HTTPStatusError):
            client.apply_labels("owner/repo", 1, ["nonexistent-label"])

    def test_accepts_empty_label_list(self):
        client, transport = _make_client(200, [])
        result = client.apply_labels("owner/repo", 1, [])
        assert result == []
        assert json.loads(transport.requests[0].content) == {"labels": []}


# ---------------------------------------------------------------------------
# Client initialisation
# ---------------------------------------------------------------------------

class TestClientInit:
    def test_custom_base_url(self):
        custom_base = "https://github.example.com/api/v3"
        client, transport = _make_client(201, {"id": 1}, base_url=custom_base)
        # Re-create with the custom base_url passed to GitHubClient
        transport2 = _MockTransport(201, {"id": 1})
        http_client = httpx.Client(transport=transport2, headers={
            "Authorization": "Bearer tok",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        gc = GitHubClient(token="tok", base_url=custom_base, _client=http_client)
        gc.post_comment("owner/repo", 1, "test")
        assert str(transport2.requests[0].url).startswith(custom_base)

    def test_trailing_slash_stripped_from_base_url(self):
        transport = _MockTransport(201, {"id": 1})
        http_client = httpx.Client(transport=transport, headers={
            "Authorization": "Bearer tok",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        gc = GitHubClient(token="tok", base_url="https://api.github.com/", _client=http_client)
        gc.post_comment("owner/repo", 1, "test")
        url_str = str(transport.requests[0].url)
        # Should not have double slashes after scheme
        assert "//repos" not in url_str
