# =============================================================================
# Onboarding vivo — clasificación de errores del job.
# =============================================================================
from types import SimpleNamespace

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
