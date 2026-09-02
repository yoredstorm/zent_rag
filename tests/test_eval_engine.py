# =============================================================================
# Tests — ZENT Evaluation Engine
# =============================================================================
# Unit: schema v2 + legacy, métricas deterministas, juez (parseo JSON),
# snapshot/version_id, regresión, runner con target fake.
# API: import de datasets, runs y comparación (DB real, auth portal admin).
# =============================================================================
from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient

_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from src.rag.evaluation.datasets import load_dataset
from src.rag.evaluation.judge import _extract_json
from src.rag.evaluation.metrics import (
    answer_keyword_coverage,
    citation_stats,
    retrieval_precision,
    retrieval_recall,
)
from src.rag.evaluation.regression import compare_runs
from src.rag.evaluation.snapshot import compute_version_id

# ---------------------------------------------------------------------------
# Dataset — schema v2 + normalización legacy
# ---------------------------------------------------------------------------


class TestDatasetSchema:
    def test_v2_schema_loads(self) -> None:
        dataset = load_dataset(
            [
                {
                    "id": "a-1",
                    "question": "¿Cuánto cuesta?",
                    "expected_answer": "Cuesta $4.990.",
                    "expected_sources": ["precio"],
                    "metadata": {"role": "admin", "top_k": 20},
                }
            ],
            name="mini",
        )
        assert dataset.case_count == 1
        assert dataset.cases[0].expected_answer == "Cuesta $4.990."

    def test_legacy_keys_normalized(self) -> None:
        dataset = load_dataset(
            [
                {
                    "id": "legacy-1",
                    "query": "pregunta legacy",
                    "expected_keywords": ["uno", "dos"],
                    "relevant_chunks": ["fragmento"],
                    "top_k": 10,
                    "role": "customer",
                }
            ]
        )
        case = dataset.cases[0]
        assert case.question == "pregunta legacy"
        assert case.legacy_keywords == ["uno", "dos"]
        assert case.expected_sources == ["fragmento"]
        assert case.metadata["top_k"] == 10
        assert case.metadata["role"] == "customer"

    def test_missing_question_rejected(self) -> None:
        with pytest.raises(ValueError, match="question"):
            load_dataset([{"id": "x"}])

    def test_duplicate_ids_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicado"):
            load_dataset(
                [
                    {"id": "dup", "question": "a"},
                    {"id": "dup", "question": "b"},
                ]
            )

    def test_auto_generated_ids(self) -> None:
        dataset = load_dataset(
            [{"question": "a"}, {"question": "b"}]
        )
        assert [c.id for c in dataset.cases] == ["case-001", "case-002"]


# ---------------------------------------------------------------------------
# Métricas deterministas
# ---------------------------------------------------------------------------


class TestDeterministicMetrics:
    def _chunks(self) -> list[dict]:
        return [
            {"content": "Paracetamol 500mg cuesta $4.990", "metadata": {}},
            {"content": "Ibuprofeno 400mg cuesta $6.490", "metadata": {}},
            {"content": "Shampoo herbal", "metadata": {}},
        ]

    def test_precision_recall(self) -> None:
        chunks = self._chunks()
        sources = ["paracetamol", "ibuprofeno"]
        assert retrieval_precision(chunks, sources) == pytest.approx(2 / 3, abs=0.01)
        assert retrieval_recall(chunks, sources) == 1.0

    def test_precision_empty_chunks(self) -> None:
        assert retrieval_precision([], ["x"]) == 0.0
        assert retrieval_recall([], ["x"]) == 0.0

    def test_citation_stats(self) -> None:
        chunks = self._chunks()
        stats = citation_stats(
            "El precio es $4.990 [Doc: 1]. Ver también [Doc: 9].",
            chunks,
            expected_sources=["paracetamol"],
        )
        assert stats["citations_parsed"] == 2
        assert stats["citations_grounded"] == 1
        assert stats["citations_correct"] == 1
        assert stats["accuracy"] == 0.5

    def test_citation_stats_no_citations(self) -> None:
        stats = citation_stats("Sin citas.", self._chunks())
        assert stats["citations_parsed"] == 0
        assert stats["accuracy"] is None

    def test_keyword_coverage(self) -> None:
        assert answer_keyword_coverage("Hola, precio $4.990", ["precio", "stock"]) == 0.5
        assert answer_keyword_coverage("Hola", []) is None


# ---------------------------------------------------------------------------
# Juez — parseo de JSON
# ---------------------------------------------------------------------------


class TestJudgeParsing:
    def test_extracts_plain_json(self) -> None:
        assert _extract_json('{"score": 0.8}') == {"score": 0.8}

    def test_extracts_json_from_noise(self) -> None:
        parsed = _extract_json("Sure, here it is:\n```json\n{\"score\": 0.5, \"hallucinated\": false}\n```")
        assert parsed == {"score": 0.5, "hallucinated": False}

    def test_invalid_returns_none(self) -> None:
        assert _extract_json("no json here") is None


# ---------------------------------------------------------------------------
# Snapshot — version_id estable
# ---------------------------------------------------------------------------


class TestVersionId:
    def test_stable_across_key_order(self) -> None:
        a = compute_version_id({"prompt": {"hash": "x"}, "model": "m", "embedding": "e"})
        b = compute_version_id({"embedding": "e", "prompt": {"hash": "x"}, "model": "m"})
        assert a == b

    def test_changes_when_model_changes(self) -> None:
        a = compute_version_id({"prompt": {"hash": "x"}, "model": "gpt-4o-mini"})
        b = compute_version_id({"prompt": {"hash": "x"}, "model": "deepseek-v3"})
        assert a != b

    def test_ignores_non_version_fields(self) -> None:
        a = compute_version_id({"prompt": {}, "model": "m", "app": {"git_commit": "abc"}})
        b = compute_version_id({"prompt": {}, "model": "m", "app": {"git_commit": "xyz"}})
        assert a == b


# ---------------------------------------------------------------------------
# Regresión
# ---------------------------------------------------------------------------


def _run_summary(
    composite: float,
    faithfulness: float | None = None,
    hallucination: float | None = None,
    avg_cost: float | None = None,
    p95_ms: float | None = None,
) -> dict:
    return {
        "run_id": str(uuid4()),
        "version_id": "v",
        "quality": {
            "composite_score": composite,
            "faithfulness": faithfulness,
            "hallucination_rate": hallucination,
        },
        "performance": {
            "avg_cost": avg_cost,
            "latency": {"p95_ms": p95_ms},
        },
    }


class TestRegression:
    def test_quality_drop_fails(self) -> None:
        report = compare_runs(
            _run_summary(0.80, faithfulness=0.9, hallucination=0.0, avg_cost=0.001, p95_ms=500),
            _run_summary(0.90, faithfulness=0.9, hallucination=0.0, avg_cost=0.001, p95_ms=500),
        )
        assert report["overall"] == "fail"
        dims = {d["dimension"]: d for d in report["dimensions"]}
        assert dims["quality"]["status"] == "fail"

    def test_better_version_passes(self) -> None:
        report = compare_runs(
            _run_summary(0.92, faithfulness=0.95, hallucination=0.0, avg_cost=0.001, p95_ms=400),
            _run_summary(0.90, faithfulness=0.9, hallucination=0.05, avg_cost=0.001, p95_ms=500),
        )
        assert report["overall"] == "pass"

    def test_hallucination_increase_fails(self) -> None:
        report = compare_runs(
            _run_summary(0.9, faithfulness=0.9, hallucination=0.3, avg_cost=0.001, p95_ms=500),
            _run_summary(0.9, faithfulness=0.9, hallucination=0.1, avg_cost=0.001, p95_ms=500),
        )
        dims = {d["dimension"]: d for d in report["dimensions"]}
        assert dims["hallucination"]["status"] == "fail"

    def test_cost_increase_fails(self) -> None:
        report = compare_runs(
            _run_summary(0.9, faithfulness=0.9, hallucination=0.0, avg_cost=0.002, p95_ms=500),
            _run_summary(0.9, faithfulness=0.9, hallucination=0.0, avg_cost=0.001, p95_ms=500),
        )
        dims = {d["dimension"]: d for d in report["dimensions"]}
        assert dims["cost"]["status"] == "fail"

    def test_latency_increase_fails(self) -> None:
        report = compare_runs(
            _run_summary(0.9, faithfulness=0.9, hallucination=0.0, avg_cost=0.001, p95_ms=800),
            _run_summary(0.9, faithfulness=0.9, hallucination=0.0, avg_cost=0.001, p95_ms=500),
        )
        dims = {d["dimension"]: d for d in report["dimensions"]}
        assert dims["latency"]["status"] == "fail"

    def test_missing_metrics_unknown(self) -> None:
        report = compare_runs(
            _run_summary(0.9),
            _run_summary(0.9),
        )
        dims = {d["dimension"]: d for d in report["dimensions"]}
        assert dims["faithfulness"]["status"] == "unknown"
        assert report["overall"] in ("pass", "unknown")


# ---------------------------------------------------------------------------
# Runner — end-to-end con target fake (sin LLM)
# ---------------------------------------------------------------------------


class _FakeTarget:
    target_type = "rag"
    target_name = "fake"
    target_id = None

    async def execute(self, question: str, metadata: dict):
        from src.rag.evaluation.targets import TargetResult

        return TargetResult(
            answer="El paracetamol cuesta $4.990 [Doc: 1].",
            retrieved=[
                {"content": "Paracetamol 500mg cuesta $4.990", "metadata": {}, "score": 0.9},
                {"content": "Shampoo herbal", "metadata": {}, "score": 0.4},
            ],
            retrieval_latency_ms=10.0,
            llm_latency_ms=200.0,
            total_latency_ms=250.0,
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            model="fake-model",
            cost=0.001,
        )


class TestRunner:
    @pytest.mark.asyncio
    async def test_runner_aggregates_quality_and_perf(self) -> None:
        from src.rag.evaluation.runner import EvalRunner

        dataset = load_dataset(
            [
                {
                    "id": "c1",
                    "question": "¿Cuánto cuesta el paracetamol?",
                    "expected_sources": ["paracetamol"],
                    "metadata": {"role": "admin", "expected_keywords": ["paracetamol", "precio"]},
                }
            ],
            name="fake-ds",
        )
        runner = EvalRunner(_FakeTarget(), judge=None)
        summary = await runner.run(dataset)

        assert summary["total_cases"] == 1
        assert summary["failed_cases"] == 0
        assert summary["quality"]["retrieval_precision"] == 0.5
        assert summary["quality"]["retrieval_recall"] == 1.0
        assert summary["quality"]["answer_relevance"] == 0.5  # fallback keywords
        assert summary["quality"]["composite_score"] > 0
        assert summary["performance"]["latency"]["avg_ms"] == 250.0
        assert summary["performance"]["latency"]["p50_ms"] == 250.0
        assert summary["performance"]["avg_cost"] == 0.001
        assert summary["performance"]["total_tokens"] == 150
        assert summary["cases"][0]["scores"]["composite"] > 0

    @pytest.mark.asyncio
    async def test_runner_judge_disabled_metrics_none(self) -> None:
        from src.rag.evaluation.runner import EvalRunner

        dataset = load_dataset([{"id": "c1", "question": "q"}], name="fake-ds")
        runner = EvalRunner(_FakeTarget(), judge=None)
        summary = await runner.run(dataset)
        assert summary["quality"]["faithfulness"] is None
        assert summary["quality"]["hallucination_rate"] is None
        assert summary["quality"]["judge_enabled"] is False


# ---------------------------------------------------------------------------
# API — import, runs y comparación (auth portal admin, DB real)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def portal_admin_auth(async_client: AsyncClient) -> dict[str, str]:
    email = f"eval_{uuid4().hex[:10]}@example.com"
    signup = await async_client.post(
        "/api/v1/auth/signup",
        json={
            "company_name": "Eval Engine Co",
            "email": email,
            "password": "secure-pass-123",
        },
    )
    assert signup.status_code == 200, signup.text
    data = signup.json()
    return {
        "Authorization": f"Bearer {data['access_token']}",
        "X-Organization-Id": data["organization_id"],
    }


_DATASET_CASES = [
    {
        "id": "api-001",
        "question": "¿Cuánto cuesta el paracetamol?",
        "expected_sources": ["paracetamol"],
        "metadata": {"role": "admin", "top_k": 20},
    },
    {
        "id": "api-002",
        "question": "¿Qué recomiendan para el resfrío?",
        "expected_sources": ["antigripal"],
        "metadata": {"role": "customer", "top_k": 10},
    },
]


class TestEvalEngineApi:
    @pytest.mark.asyncio
    async def test_dataset_import_and_list(
        self, async_client: AsyncClient, portal_admin_auth: dict[str, str]
    ) -> None:
        response = await async_client.post(
            "/api/v1/eval/datasets/import",
            json={"name": f"api-ds-{uuid4().hex[:6]}", "cases": _DATASET_CASES},
            headers=portal_admin_auth,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "imported"
        assert data["case_count"] == 2

        listing = await async_client.get(
            "/api/v1/eval/datasets", headers=portal_admin_auth
        )
        assert listing.status_code == 200, listing.text
        names = [d["name"] for d in listing.json()["datasets"]]
        assert data["name"] in names

    @pytest.mark.asyncio
    async def test_dataset_import_requires_admin(
        self, async_client: AsyncClient, trial_auth: dict[str, str]
    ) -> None:
        response = await async_client.post(
            "/api/v1/eval/datasets/import",
            json={"name": "no-admin", "cases": _DATASET_CASES},
            headers={**trial_auth, "X-Organization-Id": trial_auth["X-Organization-Id"]},
        )
        assert response.status_code == 403, response.text

    @pytest.mark.asyncio
    async def test_run_detail_and_compare(
        self, async_client: AsyncClient, portal_admin_auth: dict[str, str]
    ) -> None:
        imported = await async_client.post(
            "/api/v1/eval/datasets/import",
            json={"name": f"regress-{uuid4().hex[:6]}", "cases": _DATASET_CASES},
            headers=portal_admin_auth,
        )
        dataset_id = imported.json()["dataset_id"]

        run_body = {
            "dataset_id": dataset_id,
            "target_type": "rag",
            "judge_enabled": False,
        }
        run1 = await async_client.post(
            "/api/v1/eval/runs", json=run_body, headers=portal_admin_auth
        )
        assert run1.status_code == 200, run1.text
        assert run1.json()["total_cases"] == 2
        assert "version_id" in run1.json()
        assert run1.json()["quality"]["composite_score"] is not None
        run1_id = run1.json()["run_id"]

        run2 = await async_client.post(
            "/api/v1/eval/runs", json=run_body, headers=portal_admin_auth
        )
        assert run2.status_code == 200, run2.text
        run2_id = run2.json()["run_id"]

        listing = await async_client.get(
            "/api/v1/eval/runs", headers=portal_admin_auth
        )
        assert listing.status_code == 200
        assert len(listing.json()["runs"]) >= 2

        detail = await async_client.get(
            f"/api/v1/eval/runs/{run1_id}", headers=portal_admin_auth
        )
        assert detail.status_code == 200, detail.text
        assert len(detail.json()["cases"]) == 2
        case0 = detail.json()["cases"][0]
        assert case0["question"]
        assert "expected_sources" in case0
        assert "retrieved" in case0
        assert case0.get("actual") or case0.get("answer")
        assert "scores" in case0
        assert "latency_ms" in case0 or "latency_ms" in (case0.get("metrics") or {})
        assert "cost" in case0 or "cost" in (case0.get("metrics") or {})
        quality = detail.json().get("quality") or {}
        for key in ("faithfulness", "hallucination_rate", "retrieval_precision"):
            assert key in quality

        report = await async_client.post(
            f"/api/v1/eval/runs/{run2_id}/compare",
            json={"baseline_run_id": run1_id},
            headers=portal_admin_auth,
        )
        assert report.status_code == 200, report.text
        body = report.json()
        assert body["overall"] in ("pass", "warn", "fail", "unknown")
        assert len(body["dimensions"]) == 5

    @pytest.mark.asyncio
    async def test_run_unknown_dataset_404(
        self, async_client: AsyncClient, portal_admin_auth: dict[str, str]
    ) -> None:
        response = await async_client.post(
            "/api/v1/eval/runs",
            json={"dataset_id": str(uuid4()), "target_type": "rag", "judge_enabled": False},
            headers=portal_admin_auth,
        )
        assert response.status_code == 404, response.text

    @pytest.mark.asyncio
    async def test_platform_eval_summary_counts_without_case_text(
        self, async_client: AsyncClient, portal_admin_auth: dict[str, str]
    ) -> None:
        imported = await async_client.post(
            "/api/v1/eval/datasets/import",
            json={"name": f"plat-{uuid4().hex[:6]}", "cases": _DATASET_CASES},
            headers=portal_admin_auth,
        )
        dataset_id = imported.json()["dataset_id"]
        await async_client.post(
            "/api/v1/eval/runs",
            json={
                "dataset_id": dataset_id,
                "target_type": "rag",
                "judge_enabled": False,
            },
            headers=portal_admin_auth,
        )
        from src.platform.auth.passwords import hash_password

        email = f"padmin-{uuid4().hex[:8]}@zent.example"
        password = "platform-admin-pass-1"
        from sqlalchemy import text

        from src.infrastructure.postgres.relational_db import ensure_platform_admin_schema
        from src.infrastructure.postgres.session import get_async_session

        await ensure_platform_admin_schema()
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO users (id, organization_id, external_id, email_hash, "
                    "role, email, password_hash, is_platform_admin) "
                    "VALUES (gen_random_uuid(), NULL, :ext, :eh, 'platform', "
                    ":email, :ph, true)"
                ),
                {
                    "ext": f"platform-{uuid4().hex[:12]}",
                    "eh": __import__("hashlib").sha256(email.encode()).hexdigest(),
                    "email": email,
                    "ph": hash_password(password),
                },
            )
            # RBAC granular (migración 023): el admin legacy es super_admin.
            await session.execute(
                text(
                    "INSERT INTO user_platform_roles (user_id, role_id) "
                    "SELECT u.id, pr.id FROM users u CROSS JOIN platform_roles pr "
                    "WHERE lower(u.email) = lower(:email) AND pr.name = 'super_admin' "
                    "ON CONFLICT DO NOTHING"
                ),
                {"email": email},
            )
            await session.commit()
        finally:
            await session.close()
        login = await async_client.post(
            "/api/v1/auth/platform/login",
            json={"email": email, "password": password},
        )
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
        resp = await async_client.get(
            "/api/v1/platform/eval/summary",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["run_count"] >= 1
        assert "organizations" in payload
        blob = resp.text.lower()
        assert "cuánto cuesta el paracetamol" not in blob
        assert "paracetamol" not in blob
        tenant = await async_client.get(
            "/api/v1/platform/eval/summary",
            headers=portal_admin_auth,
        )
        assert tenant.status_code == 403, tenant.text
