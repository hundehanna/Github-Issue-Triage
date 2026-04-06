"""Tests for the GitHubClient service."""
import json

import httpx
import pytest

from app.models.triage import TriageResult
from app.services.github_client import GitHubClient, GITHUB_API_BASE, build_triage_comment


# ---------------------------------------------------------------------------
# Mock transport helpers
# ---------------------------------------------------------------------------

class _MockTransport(httpx.BaseTransport):
    """Single-response transport — records every request."""

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


class _MultiTransport(httpx.BaseTransport):
    """Returns responses from a queue; last response is repeated if queue is exhausted."""

    def __init__(self, responses: list[tuple[int, object]]):
        self._queue = list(responses)
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status_code, body = self._queue[0] if len(self._queue) == 1 else self._queue.pop(0)
        return httpx.Response(
            status_code=status_code,
            headers={"content-type": "application/json"},
            content=json.dumps(body).encode(),
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


def _make_multi_client(responses: list[tuple[int, object]], token: str = "fake-token", base_url: str = GITHUB_API_BASE):
    """Client backed by a multi-response transport (GET labels then POST apply)."""
    transport = _MultiTransport(responses)
    http_client = httpx.Client(
        transport=transport,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    return GitHubClient(token=token, base_url=base_url, _client=http_client), transport


def _sample_result(**kwargs) -> TriageResult:
    defaults = dict(
        repo="owner/repo",
        issue_number=1,
        category="Bug",
        priority="High",
        suggested_labels=["bug", "priority-high"],
        reason="Crash keyword matched",
    )
    defaults.update(kwargs)
    return TriageResult(**defaults)


# ---------------------------------------------------------------------------
# post_comment
# ---------------------------------------------------------------------------

class TestPostComment:
    def test_calls_correct_url(self):
        client, transport = _make_client(201, {"id": 1, "body": "Hello!"})
        client.post_comment("owner/repo", 7, "Hello!")
        assert transport.requests[0].url == f"{GITHUB_API_BASE}/repos/owner/repo/issues/7/comments"

    def test_sends_correct_body(self):
        client, transport = _make_client(201, {"id": 1})
        client.post_comment("owner/repo", 7, "Test comment")
        assert json.loads(transport.requests[0].content) == {"body": "Test comment"}

    def test_uses_post_method(self):
        client, transport = _make_client(201, {"id": 1})
        client.post_comment("owner/repo", 1, "hi")
        assert transport.requests[0].method == "POST"

    def test_includes_auth_header(self):
        client, transport = _make_client(201, {"id": 1}, token="my-token")
        client.post_comment("owner/repo", 1, "test")
        assert transport.requests[0].headers.get("Authorization") == "Bearer my-token"

    def test_includes_github_api_version_header(self):
        client, transport = _make_client(201, {"id": 1})
        client.post_comment("owner/repo", 1, "test")
        assert transport.requests[0].headers.get("X-GitHub-Api-Version") == "2022-11-28"

    def test_returns_response_json(self):
        expected = {"id": 99, "body": "Automated triage"}
        client, _ = _make_client(201, expected)
        assert client.post_comment("owner/repo", 1, "Automated triage") == expected

    def test_raises_on_404(self):
        client, _ = _make_client(404, {"message": "Not Found"})
        with pytest.raises(httpx.HTTPStatusError):
            client.post_comment("owner/repo", 999, "hello")

    def test_raises_on_401(self):
        client, _ = _make_client(401, {"message": "Bad credentials"})
        with pytest.raises(httpx.HTTPStatusError):
            client.post_comment("owner/repo", 1, "hello")


# ---------------------------------------------------------------------------
# apply_labels  (now calls ensure_labels_exist first → GET + POST)
# ---------------------------------------------------------------------------

class TestApplyLabels:
    def test_apply_makes_get_then_post(self):
        # GET returns existing labels, POST applies new ones
        client, transport = _make_multi_client([
            (200, [{"name": "bug"}]),          # GET existing labels
            (200, [{"name": "bug"}, {"name": "priority-high"}]),  # POST apply
        ])
        client.apply_labels("owner/repo", 7, ["bug", "priority-high"])
        assert transport.requests[0].method == "GET"
        assert transport.requests[1].method == "POST"

    def test_apply_posts_to_correct_url(self):
        client, transport = _make_multi_client([
            (200, [{"name": "bug"}]),
            (200, [{"name": "bug"}]),
        ])
        client.apply_labels("owner/repo", 7, ["bug"])
        post_req = transport.requests[1]
        assert str(post_req.url) == f"{GITHUB_API_BASE}/repos/owner/repo/issues/7/labels"

    def test_apply_sends_correct_body(self):
        # Both labels already exist → GET + POST apply (no create calls)
        client, transport = _make_multi_client([
            (200, [{"name": "bug"}, {"name": "priority-high"}]),  # GET — both exist
            (200, []),                                              # POST apply
        ])
        client.apply_labels("owner/repo", 1, ["bug", "priority-high"])
        assert json.loads(transport.requests[-1].content) == {"labels": ["bug", "priority-high"]}

    def test_returns_response_json(self):
        expected = [{"name": "bug"}, {"name": "priority-high"}]
        client, _ = _make_multi_client([
            (200, [{"name": "bug"}, {"name": "priority-high"}]),  # GET
            (200, expected),                                        # POST
        ])
        result = client.apply_labels("owner/repo", 1, ["bug", "priority-high"])
        assert result == expected

    def test_raises_on_422(self):
        client, _ = _make_multi_client([
            (200, []),
            (422, {"message": "Validation Failed"}),
        ])
        with pytest.raises(httpx.HTTPStatusError):
            client.apply_labels("owner/repo", 1, ["bad-label"])

    def test_accepts_empty_label_list(self):
        # ensure_labels_exist with empty list still does a GET, then POST
        client, transport = _make_multi_client([
            (200, []),  # GET
            (200, []),  # POST
        ])
        result = client.apply_labels("owner/repo", 1, [])
        assert result == []


# ---------------------------------------------------------------------------
# ensure_labels_exist
# ---------------------------------------------------------------------------

class TestEnsureLabelsExist:
    def test_creates_missing_label(self):
        # GET returns no labels; POST to create; no second call expected in this path
        client, transport = _make_multi_client([
            (200, []),           # GET existing → empty
            (201, {"name": "bug", "color": "d73a4a"}),  # POST create
        ])
        client.ensure_labels_exist("owner/repo", ["bug"])
        assert len(transport.requests) == 2
        assert transport.requests[1].method == "POST"
        assert json.loads(transport.requests[1].content)["name"] == "bug"

    def test_skips_existing_label(self):
        client, transport = _make_multi_client([
            (200, [{"name": "bug"}]),  # GET — label already exists
        ])
        client.ensure_labels_exist("owner/repo", ["bug"])
        # Only the GET should have been made; no POST
        assert len(transport.requests) == 1

    def test_uses_default_color_for_known_labels(self):
        client, transport = _make_multi_client([
            (200, []),
            (201, {"name": "bug"}),
        ])
        client.ensure_labels_exist("owner/repo", ["bug"])
        payload = json.loads(transport.requests[1].content)
        assert payload["color"] == "d73a4a"

    def test_uses_fallback_color_for_unknown_labels(self):
        client, transport = _make_multi_client([
            (200, []),
            (201, {"name": "custom-label"}),
        ])
        client.ensure_labels_exist("owner/repo", ["custom-label"])
        payload = json.loads(transport.requests[1].content)
        assert payload["color"] == "ededed"

    def test_creates_multiple_missing_labels(self):
        client, transport = _make_multi_client([
            (200, [{"name": "bug"}]),   # GET — bug exists
            (201, {"name": "priority-high"}),  # POST create priority-high
        ])
        client.ensure_labels_exist("owner/repo", ["bug", "priority-high"])
        assert len(transport.requests) == 2  # 1 GET + 1 POST


# ---------------------------------------------------------------------------
# build_triage_comment
# ---------------------------------------------------------------------------

class TestBuildTriageComment:
    def test_contains_category(self):
        result = _sample_result(category="Bug")
        comment = build_triage_comment(result)
        assert "Bug" in comment

    def test_contains_priority(self):
        result = _sample_result(priority="High")
        comment = build_triage_comment(result)
        assert "High" in comment

    def test_contains_labels(self):
        result = _sample_result(suggested_labels=["bug", "priority-high"])
        comment = build_triage_comment(result)
        assert "`bug`" in comment
        assert "`priority-high`" in comment

    def test_contains_reason(self):
        result = _sample_result(reason="Crash keyword matched")
        comment = build_triage_comment(result)
        assert "Crash keyword matched" in comment

    def test_bug_emoji(self):
        result = _sample_result(category="Bug")
        assert "🐛" in build_triage_comment(result)

    def test_feature_request_emoji(self):
        result = _sample_result(category="Feature Request", priority="Low", suggested_labels=["feature-request"])
        assert "✨" in build_triage_comment(result)

    def test_high_priority_emoji(self):
        result = _sample_result(priority="High")
        assert "🔴" in build_triage_comment(result)

    def test_low_priority_emoji(self):
        result = _sample_result(priority="Low")
        assert "🟢" in build_triage_comment(result)

    def test_is_markdown_table(self):
        result = _sample_result()
        comment = build_triage_comment(result)
        assert "|" in comment

    def test_contains_automated_footer(self):
        result = _sample_result()
        comment = build_triage_comment(result)
        assert "automatically" in comment.lower()


# ---------------------------------------------------------------------------
# Client init
# ---------------------------------------------------------------------------

class TestClientInit:
    def test_custom_base_url(self):
        custom_base = "https://github.example.com/api/v3"
        transport = _MockTransport(201, {"id": 1})
        http_client = httpx.Client(transport=transport, headers={
            "Authorization": "Bearer tok",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        gc = GitHubClient(token="tok", base_url=custom_base, _client=http_client)
        gc.post_comment("owner/repo", 1, "test")
        assert str(transport.requests[0].url).startswith(custom_base)

    def test_trailing_slash_stripped_from_base_url(self):
        transport = _MockTransport(201, {"id": 1})
        http_client = httpx.Client(transport=transport, headers={
            "Authorization": "Bearer tok",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        gc = GitHubClient(token="tok", base_url="https://api.github.com/", _client=http_client)
        gc.post_comment("owner/repo", 1, "test")
        assert "//repos" not in str(transport.requests[0].url)
