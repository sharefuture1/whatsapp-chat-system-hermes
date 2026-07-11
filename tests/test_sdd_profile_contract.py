"""AI 关系智能 P0 数据/API 契约规格测试。

这些测试冻结 FR-CON-005..010、FR-PLG-005..006 的 Approved 契约，
只校验 SDD，不依赖尚未实现的生产模型。
"""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SDD = ROOT / "docs" / "sdd"
DATA = (SDD / "03-data-model.md").read_text(encoding="utf-8")
API = (SDD / "04-api-and-events.md").read_text(encoding="utf-8")
REQ = (SDD / "01-product-requirements.md").read_text(encoding="utf-8")
ARCH = (SDD / "08-ai-relationship-and-multichannel.md").read_text(encoding="utf-8")


def normalized(text: str) -> str:
    return re.sub(r"[`*_\s-]+", " ", text.lower())


def section(text: str, heading: str) -> str:
    match = re.search(
        rf"^###\s+[^\n]*`?{re.escape(heading)}`?[^\n]*\n(.*?)(?=^###\s|^##\s|\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, f"missing section for {heading}"
    return match.group(1)


def assert_terms(text: str, *terms: str) -> None:
    haystack = normalized(text)
    missing = [term for term in terms if normalized(term) not in haystack]
    assert not missing, f"missing contract terms: {missing}"


def test_p0_requirements_are_approved_but_multichannel_remains_draft():
    for requirement in (
        "FR-CON-005", "FR-CON-006", "FR-CON-007", "FR-CON-008",
        "FR-CON-009", "FR-CON-010", "FR-PLG-005", "FR-PLG-006",
    ):
        assert re.search(rf"{requirement}\s+\[Approved\]", REQ)
    assert "P0" in ARCH and re.search(r"P0[^\n]*(Approved|已批准)", ARCH)
    assert re.search(r"P1[^\n]*(Draft|草案)", ARCH)
    assert re.search(r"P2[^\n]*(Draft|草案)", ARCH)


def test_relationship_tables_are_strongly_scoped_and_idempotent():
    for table in (
        "conversation_segments", "conversation_summaries", "profile_claims",
        "profile_claim_evidence", "profile_snapshots", "memory_items", "analysis_jobs",
    ):
        body = section(DATA, table)
        assert_terms(body, "account_id", "contact_id")

    segments = section(DATA, "conversation_segments")
    assert_terms(
        segments, "conversation_id", "start_message_id", "end_message_id",
        "analyzer_version", "content_hash", "UNIQUE",
    )

    summaries = section(DATA, "conversation_summaries")
    assert_terms(
        summaries, "conversation_id", "analyzer_version", "input_hash", "status",
        "stale", "version", "supersedes", "cursor",
    )


def test_claim_evidence_snapshot_and_memory_contracts():
    claims = section(DATA, "profile_claims")
    assert_terms(
        claims, "claim_key", "value_json", "source_type", "confidence", "status",
        "sensitivity", "manual_lock", "analyzer_version", "version", "optimistic lock",
    )

    evidence = section(DATA, "profile_claim_evidence")
    assert_terms(evidence, "claim_id", "evidence_type", "evidence_id", "UNIQUE")

    snapshots = section(DATA, "profile_snapshots")
    assert_terms(snapshots, "version", "is_current", "UNIQUE", "O(1)")

    memory = section(DATA, "memory_items")
    assert_terms(
        memory, "memory_key", "search_text", "expires_at", "importance",
        "embedding_ref", "account_id", "contact_id", "status", "updated_at", "INDEX",
    )


def test_analysis_job_queue_is_concurrency_safe_and_bounded():
    jobs = section(DATA, "analysis_jobs")
    assert_terms(
        jobs, "pending", "claimed", "running", "retry", "completed", "failed", "dead",
        "cancelled", "priority", "available_at", "lease_owner", "lease_expires_at",
        "attempts", "max_attempts", "idempotency_key", "input_hash", "progress_total",
        "progress_completed", "progress_failed", "parent_job_id",
        "FOR UPDATE SKIP LOCKED", "backpressure", "tenant", "account", "budget",
    )
    assert_terms(DATA, "short transaction", "AI call", "CAS", "compare-and-swap")


def test_storage_engine_and_hot_path_rules_are_explicit():
    assert_terms(DATA, "PostgreSQL", "production", "SQLite", "test", "single-node")
    assert_terms(DATA, "JSONB", "pgvector", "optional", "hot path", "JSON scan")


def test_ai_relationship_api_is_async_keyset_and_optimistic():
    assert re.search(r"POST\s+/api/v1/.+(summary|profile|analy)", API)
    assert_terms(API, "202", "job_id", "Idempotency-Key")
    assert_terms(API, "opaque", "keyset", "cursor", "offset", "forbidden")
    assert re.search(r"PATCH\s+/api/v1/.+claims", API)
    assert_terms(API, "If-Match", "version", "409")
    assert_terms(API, "account_id", "contact_id", "conversation_id", "scope")
