from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from andromeda.api.dependencies.knowledge_review import require_knowledge_review_access
from andromeda.api.main import create_app
from andromeda.infrastructure.database import Base
from andromeda.modules.auth.contracts.public import Account


def test_knowledge_manual_write_api_is_typed_and_scoped() -> None:
    schema = create_app("sqlite:///:memory:").openapi()
    paths = schema["paths"]

    assert (
        paths["/university-admin/universities/{university_id}/knowledge/claims"][
            "post"
        ]["operationId"]
        == "submit_manual_knowledge_claim_candidate"
    )
    assert (
        paths[
            "/university-admin/universities/{university_id}/knowledge/claims/{claim_id}/metadata"
        ]["put"]["operationId"]
        == "correct_manual_knowledge_claim_metadata"
    )
    policy_operation = paths[
        "/university-admin/universities/{university_id}/knowledge/policy-rules"
    ]["post"]
    assert policy_operation["operationId"] == "submit_manual_policy_rule_candidate"
    assert policy_operation["responses"]["202"]
    assert "ManualPolicyRuleCandidateRequest" in str(schema["components"]["schemas"])

    assert (
        paths["/ops/knowledge/review-queue"]["get"]["operationId"]
        == "list_knowledge_review_queue"
    )
    assert (
        paths["/ops/knowledge/review-actions"]["post"]["operationId"]
        == "apply_knowledge_review_action"
    )
    assert (
        paths["/ops/knowledge/review-preview"]["post"]["operationId"]
        == "preview_knowledge_policy_review"
    )
    assert "ReviewDecisionRequest" in str(schema["components"]["schemas"])
    review_request = schema["components"]["schemas"]["ReviewDecisionRequest"]
    assert {"policyPreviewFingerprint", "policyPreviewContext"}.issubset(
        set(review_request["properties"])
    )
    assert {"editedProposition", "canonicalSubjectId"}.issubset(
        set(review_request["properties"])
    )
    assert "PolicyHypotheticalPreview" in str(schema["components"]["schemas"])


def test_knowledge_review_queue_requires_authenticated_account() -> None:
    client = TestClient(create_app("sqlite:///:memory:"))

    response = client.get("/ops/knowledge/review-queue")
    preview_response = client.post(
        "/ops/knowledge/review-preview",
        json={
            "target": {
                "kind": "policy_rule",
                "object_id": "policy-rule:fourth-exam",
                "revision": 1,
                "revision_hash": "a" * 64,
            },
            "context": {
                "university_id": "university:bmstu",
                "admission_year": 2028,
                "valid_as_of": "2027-12-15T12:00:00Z",
            },
        },
    )

    assert response.status_code == 401
    assert preview_response.status_code == 401


def test_knowledge_review_queue_returns_a_bounded_typed_empty_read_model(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'knowledge-review.db').as_posix()}"
    app = create_app(database_url)
    Base.metadata.create_all(app.state.engine)
    app.dependency_overrides[require_knowledge_review_access] = lambda: Account(
        account_id="account:" + "a" * 32,
        email="reviewer@example.test",
        created_at=datetime.now(UTC),
    )

    response = TestClient(app).get("/ops/knowledge/review-queue?limit=7")

    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "truncated": False}
