import pytest

from app.models.triage import TriageResult
from app.services.issue_processor import triage_issue


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _triage(title: str, body: str = "") -> TriageResult:
    return triage_issue("owner/repo", 1, title, body)


# ---------------------------------------------------------------------------
# Category classification
# ---------------------------------------------------------------------------

class TestCategoryClassification:
    def test_bug_from_title(self):
        result = _triage("App crashes on startup")
        assert result.category == "Bug"

    def test_bug_keyword_error(self):
        result = _triage("Getting an error when saving")
        assert result.category == "Bug"

    def test_bug_keyword_exception(self):
        result = _triage("Unhandled exception in parser")
        assert result.category == "Bug"

    def test_bug_keyword_traceback(self):
        result = _triage("traceback in log file")
        assert result.category == "Bug"

    def test_bug_keyword_fail(self):
        result = _triage("Build fail on CI")
        assert result.category == "Bug"

    def test_bug_keyword_broken(self):
        result = _triage("The login is broken")
        assert result.category == "Bug"

    def test_feature_request(self):
        result = _triage("Feature: add dark mode")
        assert result.category == "Feature Request"

    def test_feature_enhancement(self):
        result = _triage("Enhancement: improve search")
        assert result.category == "Feature Request"

    def test_feature_request_keyword(self):
        result = _triage("Request: export to CSV")
        assert result.category == "Feature Request"

    def test_feature_proposal(self):
        result = _triage("Proposal for new API endpoint")
        assert result.category == "Feature Request"

    def test_feature_would_like(self):
        result = _triage("I would like a dark mode option")
        assert result.category == "Feature Request"

    def test_documentation(self):
        result = _triage("Update documentation for v2")
        assert result.category == "Documentation"

    def test_documentation_docs(self):
        result = _triage("Fix docs typo on homepage")
        assert result.category == "Documentation"

    def test_documentation_readme(self):
        result = _triage("README missing install instructions")
        assert result.category == "Documentation"

    def test_documentation_typo(self):
        result = _triage("Typo in the getting started guide")
        assert result.category == "Documentation"

    def test_documentation_example(self):
        result = _triage("Add example usage for the API")
        assert result.category == "Documentation"

    def test_question(self):
        result = _triage("Question: how to configure OAuth?")
        assert result.category == "Question"

    def test_question_how_to(self):
        result = _triage("How to run tests locally?")
        assert result.category == "Question"

    def test_question_help(self):
        result = _triage("Help: can't get the server running")
        assert result.category == "Question"

    def test_question_clarify(self):
        result = _triage("Clarify the deployment process")
        assert result.category == "Question"

    def test_question_why_does(self):
        result = _triage("Why does the test suite take so long?")
        assert result.category == "Question"

    def test_other_no_keywords(self):
        result = _triage("Random title with no matching terms")
        assert result.category == "Other"

    def test_keyword_in_body(self):
        result = _triage("Unexpected behavior", "I get a crash when I open the app")
        assert result.category == "Bug"

    def test_first_matching_category_wins(self):
        # "bug" comes before "feature" in the rule list
        result = _triage("bug report: feature request format")
        assert result.category == "Bug"


# ---------------------------------------------------------------------------
# Priority
# ---------------------------------------------------------------------------

class TestPriority:
    def test_high_priority_urgent(self):
        result = _triage("Urgent: service is down")
        assert result.priority == "High"

    def test_high_priority_critical(self):
        result = _triage("Critical error in production")
        assert result.priority == "High"

    def test_high_priority_blocking(self):
        result = _triage("Blocking our release")
        assert result.priority == "High"

    def test_high_priority_blocker(self):
        result = _triage("Login blocker")
        assert result.priority == "High"

    def test_high_priority_production(self):
        result = _triage("Production database is corrupted")
        assert result.priority == "High"

    def test_high_priority_security(self):
        result = _triage("Security vulnerability in auth module")
        assert result.priority == "High"

    def test_high_priority_crash(self):
        result = _triage("App crash on launch")
        assert result.priority == "High"

    def test_low_priority_nice_to_have(self):
        result = _triage("Nice to have: better error messages")
        assert result.priority == "Low"

    def test_low_priority_minor(self):
        result = _triage("Minor spacing issue in footer")
        assert result.priority == "Low"

    def test_low_priority_nit(self):
        result = _triage("Nit: rename variable for clarity")
        assert result.priority == "Low"

    def test_low_priority_cosmetic(self):
        result = _triage("Cosmetic change to button colour")
        assert result.priority == "Low"

    def test_low_priority_typo(self):
        result = _triage("Typo in README")
        assert result.priority == "Low"

    def test_medium_priority_default(self):
        result = _triage("Add pagination to the list view")
        assert result.priority == "Medium"

    def test_high_priority_keyword_in_body(self):
        result = _triage("Service issue", "This is blocking the team from deploying.")
        assert result.priority == "High"


# ---------------------------------------------------------------------------
# Suggested labels
# ---------------------------------------------------------------------------

class TestSuggestedLabels:
    def test_bug_high_labels(self):
        result = _triage("Critical crash in parser")
        assert "bug" in result.suggested_labels
        assert "priority-high" in result.suggested_labels

    def test_feature_medium_labels(self):
        result = _triage("Feature request: add CSV export")
        assert "feature-request" in result.suggested_labels
        assert "priority-medium" in result.suggested_labels

    def test_documentation_low_labels(self):
        result = _triage("Typo in docs")
        assert "documentation" in result.suggested_labels
        assert "priority-low" in result.suggested_labels

    def test_other_labels(self):
        result = _triage("Something else entirely")
        assert "other" in result.suggested_labels

    def test_labels_are_list(self):
        result = _triage("A bug report")
        assert isinstance(result.suggested_labels, list)
        assert len(result.suggested_labels) >= 1


# ---------------------------------------------------------------------------
# Reason field
# ---------------------------------------------------------------------------

class TestReason:
    def test_reason_contains_matched_keyword(self):
        result = _triage("App crash on launch")
        assert "crash" in result.reason

    def test_reason_no_keywords(self):
        result = _triage("Unrelated title")
        assert result.reason == "No specific keywords matched."

    def test_reason_is_string(self):
        result = _triage("Any issue")
        assert isinstance(result.reason, str)


# ---------------------------------------------------------------------------
# TriageResult model validation
# ---------------------------------------------------------------------------

class TestTriageResultModel:
    def test_model_fields_present(self):
        result = _triage("Bug report", "Something crashed")
        assert result.repo == "owner/repo"
        assert result.issue_number == 1

    def test_invalid_issue_number_raises(self):
        with pytest.raises(Exception):
            TriageResult(
                repo="owner/repo",
                issue_number=0,  # must be >= 1
                category="Bug",
                priority="High",
                suggested_labels=["bug"],
                reason="test",
            )

    def test_invalid_category_raises(self):
        with pytest.raises(Exception):
            TriageResult(
                repo="owner/repo",
                issue_number=1,
                category="Invalid",  # not a valid literal
                priority="High",
                suggested_labels=["bug"],
                reason="test",
            )

    def test_invalid_priority_raises(self):
        with pytest.raises(Exception):
            TriageResult(
                repo="owner/repo",
                issue_number=1,
                category="Bug",
                priority="Critical",  # not a valid literal
                suggested_labels=["bug"],
                reason="test",
            )
