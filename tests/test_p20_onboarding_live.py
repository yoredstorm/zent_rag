# =============================================================================
# Onboarding vivo — clasificación de errores del job.
# =============================================================================
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.platform.data_onboarding.service import _error_details, _job_error


def test_ssrf_error_has_actionable_hint() -> None:
    code, hint = _error_details(
        "ConnectorError: Blocked private network IP: 192.168.65.254 "
        "(add host to connector config ssrf_allowlist to allow)"
    )
    assert code == "PRIVATE_HOST_BLOCKED"
    assert "Hosts permitidos" in (hint or "")


def test_connection_error_is_source_unreachable() -> None:
    code, hint = _error_details("Connection failed: timeout")
    assert code == "SOURCE_UNREACHABLE"
    assert "host" in (hint or "").lower()


def test_job_error_reads_error_summary() -> None:
    job = SimpleNamespace(error_summary={"error": "boom"})
    assert _job_error(job) == "boom"
    assert _job_error(SimpleNamespace(error_summary={})) is None


@pytest.mark.asyncio
async def test_discovery_scan_keeps_workspace(monkeypatch) -> None:
    from src.catalog.jobs import start_discovery_scan

    seen: dict = {}

    class _Store:
        async def upsert_source(self, **kwargs):
            seen.update(kwargs)
            return {"id": "11111111-1111-1111-1111-111111111111"}

        async def update_source(self, *args, **kwargs):  # pragma: no cover
            return None

    class _Jobs:
        async def create_job(self, *args, **kwargs):
            return SimpleNamespace(id="22222222-2222-2222-2222-222222222222")

        async def update_job(self, *args, **kwargs):
            return None

    async def _noop(_job_id):  # pragma: no cover - solo evita Redis
        return None

    monkeypatch.setattr("src.knowledge.queue.enqueue_knowledge_job", _noop)
    org = uuid4()
    workspace = uuid4()
    result = await start_discovery_scan(
        job_repo=_Jobs(),
        catalog_store=_Store(),
        organization_id=org,
        connector_id=uuid4(),
        workspace_id=workspace,
    )

    assert seen["workspace_id"] == workspace
    assert result["catalog_source_id"] == "11111111-1111-1111-1111-111111111111"

