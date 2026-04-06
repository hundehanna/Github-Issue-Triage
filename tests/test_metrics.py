"""Tests for Phase 4: metrics, feedback endpoint, and logging config."""
import json

import pytest
from fastapi.testclient import TestClient

from app.models.triage import TriageResult
from app.services.metrics import TriageMetrics, track_triage_duration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(**kwargs) -> TriageResult:
    defaults = dict(
        repo="owner/repo",
        issue_number=1,
        category="Bug",
        priority="High",
        suggested_labels=["bug", "priority-high"],
        reason="crash matched",
    )
    defaults.update(kwargs)
    return TriageResult(**defaults)


# ---------------------------------------------------------------------------
# TriageMetrics unit tests
# ---------------------------------------------------------------------------

class TestTriageMetrics:
    def setup_method(self):
        self.m = TriageMetrics()

    def test_initial_state_is_zero(self):
        d = self.m.to_dict()
        assert d["total_triaged"] == 0
        assert d["errors"] == 0
        assert d["avg_latency_ms"] == 0.0

    def test_record_triage_increments_total(self):
        self.m.record_triage(_result(), used_llm=False, latency_ms=10.0)
        assert self.m.to_dict()["total_triaged"] == 1

    def test_record_triage_tracks_llm_vs_keyword(self):
        self.m.record_triage(_result(), used_llm=True, latency_ms=100.0)
        self.m.record_triage(_result(), used_llm=False, latency_ms=5.0)
        d = self.m.to_dict()
        assert d["llm_used"] == 1
        assert d["keyword_fallback"] == 1

    def test_record_triage_tracks_category(self):
        self.m.record_triage(_result(category="Bug"), used_llm=False, latency_ms=1.0)
        self.m.record_triage(_result(category="Question"), used_llm=False, latency_ms=1.0)
        d = self.m.to_dict()
        assert d["by_category"]["Bug"] == 1
        assert d["by_category"]["Question"] == 1

    def test_record_triage_tracks_priority(self):
        self.m.record_triage(_result(priority="High"), used_llm=False, latency_ms=1.0)
        self.m.record_triage(_result(priority="Low"), used_llm=False, latency_ms=1.0)
        d = self.m.to_dict()
        assert d["by_priority"]["High"] == 1
        assert d["by_priority"]["Low"] == 1

    def test_avg_latency_calculated_correctly(self):
        self.m.record_triage(_result(), used_llm=False, latency_ms=100.0)
        self.m.record_triage(_result(), used_llm=False, latency_ms=200.0)
        assert self.m.avg_latency_ms == 150.0

    def test_record_error_increments_errors(self):
        self.m.record_error()
        self.m.record_error()
        assert self.m.to_dict()["errors"] == 2

    def test_record_feedback(self):
        self.m.record_feedback("correct")
        self.m.record_feedback("correct")
        self.m.record_feedback("incorrect")
        d = self.m.to_dict()
        assert d["feedback"]["correct"] == 2
        assert d["feedback"]["incorrect"] == 1

    def test_reset_clears_all(self):
        self.m.record_triage(_result(), used_llm=True, latency_ms=50.0)
        self.m.record_error()
        self.m.record_feedback("correct")
        self.m.reset()
        d = self.m.to_dict()
        assert d["total_triaged"] == 0
        assert d["errors"] == 0
        assert d["feedback"] == {}


# ---------------------------------------------------------------------------
# track_triage_duration context manager
# ---------------------------------------------------------------------------

class TestTrackTriageDuration:
    def test_records_elapsed_time(self):
        with track_triage_duration() as info:
            pass
        assert "latency_ms" in info
        assert info["latency_ms"] >= 0

    def test_latency_is_non_negative_float(self):
        with track_triage_duration() as info:
            pass
        assert isinstance(info["latency_ms"], float)
        assert info["latency_ms"] >= 0


# ---------------------------------------------------------------------------
# /metrics endpoint
# ---------------------------------------------------------------------------

class TestMetricsEndpoint:
    def setup_method(self):
        from app.services.metrics import metrics
        metrics.reset()

    def test_metrics_endpoint_returns_200(self):
        from app.main import app
        client = TestClient(app)
        response = client.get("/metrics")
        assert response.status_code == 200

    def test_metrics_endpoint_returns_expected_keys(self):
        from app.main import app
        client = TestClient(app)
        data = client.get("/metrics").json()
        for key in ("total_triaged", "llm_used", "keyword_fallback", "errors",
                    "avg_latency_ms", "by_category", "by_priority", "feedback"):
            assert key in data

    def test_metrics_reflects_triage_call(self):
        from app.main import app
        from app.services.metrics import metrics
        client = TestClient(app)

        # Trigger a real triage via webhook
        payload = json.dumps({
            "action": "opened",
            "issue": {"number": 1, "title": "App crashes", "body": ""},
            "repository": {"full_name": "owner/repo"},
        }).encode()
        client.post("/webhooks/github", content=payload,
                    headers={"x-github-event": "issues", "content-type": "application/json"})

        data = client.get("/metrics").json()
        assert data["total_triaged"] == 1


# ---------------------------------------------------------------------------
# /feedback endpoint
# ---------------------------------------------------------------------------

class TestFeedbackEndpoint:
    def setup_method(self):
        from app.services.metrics import metrics
        metrics.reset()

    @pytest.fixture
    def client(self):
        from app.main import app
        return TestClient(app)

    def test_valid_feedback_correct(self, client):
        resp = client.post("/feedback/owner/repo/42", json={"verdict": "correct"})
        assert resp.status_code == 200
        assert resp.json()["verdict"] == "correct"
        assert resp.json()["recorded"] is True

    def test_valid_feedback_incorrect(self, client):
        resp = client.post("/feedback/owner/repo/42", json={"verdict": "incorrect"})
        assert resp.status_code == 200

    def test_valid_feedback_overridden(self, client):
        resp = client.post("/feedback/owner/repo/42", json={"verdict": "overridden"})
        assert resp.status_code == 200

    def test_invalid_verdict_returns_400(self, client):
        resp = client.post("/feedback/owner/repo/42", json={"verdict": "bad-verdict"})
        assert resp.status_code == 400

    def test_feedback_recorded_in_metrics(self, client):
        from app.services.metrics import metrics
        client.post("/feedback/owner/repo/1", json={"verdict": "correct"})
        client.post("/feedback/owner/repo/2", json={"verdict": "incorrect"})
        assert metrics.feedback_counts["correct"] == 1
        assert metrics.feedback_counts["incorrect"] == 1

    def test_feedback_response_contains_repo_and_issue(self, client):
        resp = client.post("/feedback/myorg/myrepo/99", json={"verdict": "correct"})
        data = resp.json()
        assert data["repo"] == "myorg/myrepo"
        assert data["issue_number"] == 99

    def test_feedback_with_note(self, client):
        resp = client.post("/feedback/owner/repo/1",
                           json={"verdict": "overridden", "note": "Changed to documentation"})
        assert resp.status_code == 200
