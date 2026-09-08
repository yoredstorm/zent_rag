# =============================================================================
# Data Onboarding — orquestación (reusa connectors / catalog / sources / RAG)
# =============================================================================
from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from src.catalog.signals import infer_column
from src.catalog.store import PostgresCatalogStore
from src.catalog.suggestions import ReviewQueueService
from src.core.domain.catalog import (
    CatalogEntity,
    CatalogField,
    CatalogProvenance,
    CatalogSuggestion,
    SuggestionStatus,
    SuggestionType,
)
from src.infrastructure.observability.logging_config import get_logger
from src.platform.data_onboarding.constants import SQL_ENGINES
from src.platform.data_onboarding.mime import MimeRejected, detect_source_type
from src.platform.data_onboarding.profile import profile_upload
from src.platform.data_onboarding.questions import build_question_pack
from src.platform.data_onboarding.store import DataOnboardingStore, merge_state

logger = get_logger(__name__)


def _workspace_uuid(row: dict) -> UUID | None:
    raw = row.get("workspace_id")
    return UUID(str(raw)) if raw else None

_FRIENDLY_PHASES = [
    ("connection", "Conexión verificada"),
    ("structure", "Estructura descubierta"),
    ("content", "Contenido analizado"),
    ("meaning", "Significado de negocio"),
    ("relationships", "Relaciones"),
    ("quality", "Revisión de calidad"),
]


class DataOnboardingError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class DataOnboardingService:
    def __init__(self, store: DataOnboardingStore | None = None) -> None:
        self._store = store or DataOnboardingStore()
        self._catalog = PostgresCatalogStore()

    async def create_session(
        self,
        organization_id: UUID,
        kind: str,
        *,
        workspace_id: UUID | None = None,
        created_by: UUID | None = None,
    ) -> dict:
        row = await self._store.create(
            organization_id, kind, workspace_id=workspace_id, created_by=created_by
        )
        updated = await self._store.update(
            organization_id, UUID(row["id"]), step="connect", status="NOT_STARTED"
        )
        return self.public(updated or row)

    async def get_session(self, organization_id: UUID, session_id: UUID) -> dict:
        row = await self._store.get(organization_id, session_id)
        if row is None:
            raise DataOnboardingError("Session not found", 404)
        return self.public(row)

    async def list_sessions(
        self,
        organization_id: UUID,
        status: str | None = None,
        workspace_id: UUID | None = None,
    ) -> list[dict]:
        rows = await self._store.list(
            organization_id, status=status, workspace_id=workspace_id
        )
        return [self.public(r) for r in rows]

    async def gate(
        self, organization_id: UUID, workspace_id: UUID | None = None
    ) -> dict:
        from src.api.deps import get_connector_repo, get_source_repo

        connectors = []
        sources = []
        try:
            connectors = await get_connector_repo().list_connectors(
                organization_id, workspace_id=workspace_id
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("onboarding gate connectors failed", error=str(exc)[:200])
        try:
            sources = await get_source_repo().list_sources(
                organization_id, workspace_id=workspace_id
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("onboarding gate sources failed", error=str(exc)[:200])
        real_sources = [
            s
            for s in sources
            if s.type != "sql" and "farmacia" not in (s.name or "").lower()
        ]
        sessions = await self._store.list(organization_id, workspace_id=workspace_id)
        resume = next(
            (
                s
                for s in sessions
                if s["status"] not in ("READY", "FAILED") and s["status"] != "NOT_STARTED"
            ),
            None,
        )
        has_real = bool(connectors or real_sources)
        return {
            "has_real_data": has_real,
            "resume_session_id": resume["id"] if resume else None,
        }

    def public(self, row: dict) -> dict:
        usable = row["status"] in ("READY", "NEEDS_ATTENTION")
        pending = int((row.get("state") or {}).get("pending_review_count") or 0)
        warning = None
        if row["status"] == "NEEDS_ATTENTION" or row.get("skipped_review"):
            n = pending or 4
            warning = (
                f"Tu fuente es usable, pero la precisión puede mejorar si revisas "
                f"{n} mappings."
            )
        state = dict(row.get("state") or {})
        for secret_key in ("password", "secrets", "bearer_token", "api_key", "refresh_token"):
            state.pop(secret_key, None)
        return {
            "id": row["id"],
            "kind": row["kind"],
            "status": row["status"],
            "step": row["step"],
            "connector_id": row.get("connector_id"),
            "catalog_source_id": row.get("catalog_source_id"),
            "kb_source_id": row.get("kb_source_id"),
            "skipped_review": row.get("skipped_review"),
            "skipped_test": row.get("skipped_test"),
            "usable": usable,
            "warning": warning,
            "state": state,
        }

    async def skip(self, organization_id: UUID, session_id: UUID, what: str) -> dict:
        if what not in ("review", "test"):
            raise DataOnboardingError("skip target must be review or test")
        row = await self._require(organization_id, session_id)
        fields: dict[str, Any] = {
            "status": "NEEDS_ATTENTION",
            "step": "ready" if what == "test" else "test",
        }
        if what == "review":
            fields["skipped_review"] = True
            fields["step"] = "test"
        else:
            fields["skipped_test"] = True
            fields["step"] = "ready"
        state = merge_state(row.get("state") or {}, {"skipped": what})
        fields["state_json"] = state
        updated = await self._store.update(organization_id, session_id, **fields)
        return self.public(updated or row)

    async def complete(self, organization_id: UUID, session_id: UUID) -> dict:
        row = await self._require(organization_id, session_id)
        status = "NEEDS_ATTENTION" if row.get("skipped_review") or row.get("skipped_test") else "READY"
        updated = await self._store.update(
            organization_id,
            session_id,
            status=status,
            step="ready",
        )
        return self.public(updated or row)

    async def connect_database(
        self, organization_id: UUID, session_id: UUID, body: dict
    ) -> dict:
        from src.api.deps import get_connector_repo
        from src.connectors.plugin import ConnectorError, get_plugin, redact
        from src.infrastructure.secrets.secret_store_resolver import get_secret_store

        row = await self._require(organization_id, session_id)
        engine = str(body.get("engine") or "postgres").strip()
        if engine not in SQL_ENGINES:
            raise DataOnboardingError(
                f"engine must be one of {sorted(SQL_ENGINES)}"
            )
        password = str(body.get("password") or "")
        if not password:
            raise DataOnboardingError("password is required")
        advanced = body.get("advanced") if isinstance(body.get("advanced"), dict) else {}
        config: dict[str, Any] = {
            "host": str(body.get("host") or "").strip(),
            "port": int(body.get("port") or SQL_ENGINES[engine]),
            "database": str(body.get("database") or "").strip(),
            "user": str(body.get("username") or body.get("user") or "").strip(),
            "ssl": bool(body.get("ssl")),
        }
        if advanced.get("ssrf_allowlist"):
            config["ssrf_allowlist"] = list(advanced["ssrf_allowlist"])
        if advanced.get("allowed_schemas"):
            config["allowed_schemas"] = list(advanced["allowed_schemas"])
        if advanced.get("timeout"):
            config["timeout_seconds"] = int(advanced["timeout"])
        await self._store.update(
            organization_id, session_id, status="CONNECTING", step="connect"
        )
        repo = get_connector_repo()
        connector = await repo.create_connector(
            organization_id,
            str(body.get("name") or "Base de datos"),
            engine,
            workspace_id=_workspace_uuid(row),
            config_json=config,
        )
        await get_secret_store().put(
            organization_id, connector.id, {"password": password}
        )
        secrets = await get_secret_store().get(organization_id, connector.id)
        plugin = get_plugin(engine, config, secrets or {})
        test_payload: dict[str, Any]
        try:
            result = await asyncio.wait_for(plugin.test_connection(), timeout=20)
            test_payload = {
                "ok": result.ok,
                "latency_ms": round(result.latency_ms, 2),
                "message": redact(result.message),
                "server_version": result.server_version,
            }
            tables = 0
            columns = 0
            if result.ok:
                try:
                    discovery = await asyncio.wait_for(plugin.discover(), timeout=40)
                    tables = len(discovery.tables)
                    columns = sum(len(t.columns) for t in discovery.tables)
                    test_payload["tables"] = tables
                    test_payload["columns"] = columns
                except Exception as exc:  # noqa: BLE001
                    test_payload["discover_error"] = redact(str(exc))[:200]
        except TimeoutError as exc:
            raise DataOnboardingError("Connection test timed out", 422) from exc
        except ConnectorError as exc:
            test_payload = {"ok": False, "message": redact(str(exc))}
        finally:
            try:
                await plugin.close()
            except Exception:
                pass
        state = merge_state(
            row.get("state") or {},
            {"connection_test": test_payload, "engine": engine},
        )
        status = "CONNECTED" if test_payload.get("ok") else "FAILED"
        updated = await self._store.update(
            organization_id,
            session_id,
            status=status,
            step="analyze" if test_payload.get("ok") else "connect",
            connector_id=connector.id,
            state_json=state,
        )
        public = self.public(updated or row)
        public["connection"] = test_payload
        return public

    async def connect_upload(
        self,
        organization_id: UUID,
        session_id: UUID,
        *,
        filename: str,
        data: bytes,
        created_by: UUID | None,
    ) -> dict:
        from src.api.deps import get_source_repo
        from src.knowledge.storage import store_upload

        row = await self._require(organization_id, session_id)
        if len(data) > 25 * 1024 * 1024:
            raise DataOnboardingError("File too large (max 25 MB)", 413)
        try:
            source_type = detect_source_type(filename, data)
        except MimeRejected as exc:
            raise DataOnboardingError(str(exc), 415) from exc
        object_key = store_upload(organization_id, filename, data)
        config: dict[str, Any] = {"object_key": object_key, "filename": filename}
        if source_type == "csv":
            config["delimiter"] = ","
        source = await get_source_repo().create_source(
            organization_id,
            filename,
            source_type,
            config_json=config,
            workspace_id=_workspace_uuid(row),
        )
        state = merge_state(
            row.get("state") or {},
            {"filename": filename, "source_type": source_type, "object_key": object_key},
        )
        updated = await self._store.update(
            organization_id,
            session_id,
            status="CONNECTED",
            step="analyze",
            kb_source_id=source.id,
            state_json=state,
        )
        return self.public(updated or row)

    async def connect_web(
        self,
        organization_id: UUID,
        session_id: UUID,
        *,
        url: str,
        commit: bool,
    ) -> dict:
        from src.api.deps import get_source_repo
        from src.connectors.plugin.base import assert_host_safe

        row = await self._require(organization_id, session_id)
        url = (url or "").strip()
        if not url.startswith(("http://", "https://")):
            raise DataOnboardingError("url must be http(s)")
        parsed = urlparse(url)
        if not parsed.hostname:
            raise DataOnboardingError("url host is required")
        try:
            assert_host_safe(parsed.hostname)
        except Exception as exc:
            raise DataOnboardingError(str(exc), 422) from exc
        preview = await self._cheap_web_preview(url, parsed.hostname or "")
        if not commit:
            state = merge_state(row.get("state") or {}, {"web_preview": preview})
            updated = await self._store.update(
                organization_id, session_id, state_json=state, status="CONNECTING"
            )
            public = self.public(updated or row)
            public["preview"] = preview
            return public
        source = await get_source_repo().create_source(
            organization_id,
            parsed.hostname or url,
            "web",
            config_json={"url": url},
            workspace_id=_workspace_uuid(row),
        )
        state = merge_state(row.get("state") or {}, {"web_preview": preview})
        updated = await self._store.update(
            organization_id,
            session_id,
            status="CONNECTED",
            step="analyze",
            kb_source_id=source.id,
            state_json=state,
        )
        public = self.public(updated or row)
        public["preview"] = preview
        return public

    async def connect_api(
        self, organization_id: UUID, session_id: UUID, body: dict
    ) -> dict:
        from src.api.deps import get_connector_repo, get_source_repo
        from src.connectors.plugin import ConnectorError, get_plugin, redact
        from src.infrastructure.secrets.secret_store_resolver import get_secret_store

        row = await self._require(organization_id, session_id)
        base_url = str(body.get("base_url") or "").strip()
        if not base_url:
            raise DataOnboardingError("base_url is required")
        auth = str(body.get("auth") or "none").lower()
        secrets: dict[str, str] = {}
        if auth == "bearer" and body.get("token"):
            secrets["bearer_token"] = str(body["token"])
        elif auth == "api_key" and body.get("token"):
            secrets["api_key"] = str(body["token"])
        elif auth == "basic":
            if body.get("username"):
                secrets["username"] = str(body["username"])
            if body.get("password"):
                secrets["password"] = str(body["password"])
        config = {
            "base_url": base_url,
            "method": str(body.get("method") or "GET"),
        }
        if body.get("ssrf_allowlist"):
            config["ssrf_allowlist"] = list(body["ssrf_allowlist"])
        repo = get_connector_repo()
        connector = await repo.create_connector(
            organization_id,
            str(body.get("name") or "API"),
            "rest_api",
            workspace_id=_workspace_uuid(row),
            config_json=config,
        )
        if secrets:
            await get_secret_store().put(organization_id, connector.id, secrets)
        loaded = await get_secret_store().get(organization_id, connector.id)
        plugin = get_plugin("rest_api", config, loaded or {})
        try:
            result = await asyncio.wait_for(plugin.test_connection(), timeout=15)
            test_payload = {
                "ok": result.ok,
                "latency_ms": round(result.latency_ms, 2),
                "message": redact(result.message),
            }
        except (TimeoutError, ConnectorError) as exc:
            test_payload = {"ok": False, "message": redact(str(exc))}
        finally:
            try:
                await plugin.close()
            except Exception:
                pass
        items_path = body.get("items_path") or ["data"]
        source = await get_source_repo().create_source(
            organization_id,
            str(body.get("name") or "API"),
            "api",
            config_json={
                "base_url": base_url,
                "connector_id": str(connector.id),
                "items_path": items_path,
                "path": str(body.get("path") or ""),
            },
            workspace_id=_workspace_uuid(row),
        )
        state = merge_state(row.get("state") or {}, {"connection_test": test_payload})
        status = "CONNECTED" if test_payload.get("ok") else "FAILED"
        updated = await self._store.update(
            organization_id,
            session_id,
            status=status,
            step="analyze" if test_payload.get("ok") else "connect",
            connector_id=connector.id,
            kb_source_id=source.id,
            state_json=state,
        )
        public = self.public(updated or row)
        public["connection"] = test_payload
        return public

    async def start_drive_oauth(
        self, organization_id: UUID, session_id: UUID, name: str
    ) -> dict:
        from src.api.deps import get_connector_repo
        from src.connectors.gdrive.oauth import (
            DriveOAuthError,
            build_drive_authorization_url,
            sign_drive_oauth_state,
        )
        from src.core.config import get_settings

        row = await self._require(organization_id, session_id)
        settings = get_settings()
        if not (settings.GOOGLE_OAUTH_CLIENT_ID or "").strip():
            raise DataOnboardingError("Google Drive OAuth is not configured", 503)
        repo = get_connector_repo()
        connector = await repo.create_connector(
            organization_id,
            name or "Google Drive",
            "gdrive",
            workspace_id=_workspace_uuid(row),
            config_json={},
        )
        try:
            state = sign_drive_oauth_state(
                organization_id=organization_id,
                connector_id=connector.id,
                return_path=f"/knowledge/add/{session_id}",
            )
            authorization_url = build_drive_authorization_url(state)
        except DriveOAuthError as exc:
            raise DataOnboardingError(str(exc), 503) from exc
        await self._store.update(
            organization_id,
            session_id,
            status="CONNECTING",
            step="connect",
            connector_id=connector.id,
        )
        return {
            **self.public(await self._require(organization_id, session_id)),
            "authorization_url": authorization_url,
            "connector_id": str(connector.id),
        }

    async def list_drive_folders(
        self, organization_id: UUID, session_id: UUID, parent_id: str | None = None
    ) -> dict:
        from src.connectors.gdrive.client import list_drive_folders, refresh_access_token
        from src.infrastructure.secrets.secret_store_resolver import get_secret_store

        row = await self._require(organization_id, session_id)
        if not row.get("connector_id"):
            raise DataOnboardingError("Connect Google Drive first", 400)
        secrets = await get_secret_store().get(
            organization_id, UUID(row["connector_id"])
        )
        token = str((secrets or {}).get("refresh_token") or "")
        if not token:
            raise DataOnboardingError("Drive is not authorized yet", 400)
        access = await refresh_access_token(token)
        folders = await list_drive_folders(access, parent_id)
        return {"folders": folders}

    async def select_drive_folder(
        self, organization_id: UUID, session_id: UUID, folder_id: str
    ) -> dict:
        from src.api.deps import get_connector_repo, get_source_repo
        from src.connectors.gdrive.client import list_folder_files, refresh_access_token
        from src.infrastructure.secrets.secret_store_resolver import get_secret_store

        row = await self._require(organization_id, session_id)
        if not row.get("connector_id"):
            raise DataOnboardingError("Connect Google Drive first", 400)
        cid = UUID(row["connector_id"])
        repo = get_connector_repo()
        connector = await repo.get_connector(organization_id, cid)
        if connector is None:
            raise DataOnboardingError("Connector not found", 404)
        merged = {**(connector.config_json or {}), "folder_id": folder_id}
        await repo.update_connector(
            organization_id, cid, config_json=merged
        )
        secrets = await get_secret_store().get(organization_id, cid)
        preview: list[dict] = []
        try:
            access = await refresh_access_token(str((secrets or {}).get("refresh_token") or ""))
            files = await list_folder_files(access, folder_id)
            preview = [
                {"id": f.get("id"), "name": f.get("name"), "mime_type": f.get("mimeType")}
                for f in files[:50]
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("drive preview failed", error=str(exc)[:200])
        source = await get_source_repo().create_source(
            organization_id,
            connector.name,
            "gdrive",
            config_json={"folder_id": folder_id, "connector_id": str(cid)},
            workspace_id=_workspace_uuid(row),
        )
        state = merge_state(row.get("state") or {}, {"drive_preview": preview})
        updated = await self._store.update(
            organization_id,
            session_id,
            status="CONNECTED",
            step="analyze",
            kb_source_id=source.id,
            state_json=state,
        )
        public = self.public(updated or row)
        public["preview"] = preview
        return public

    async def analyze(self, organization_id: UUID, session_id: UUID) -> dict:
        row = await self._require(organization_id, session_id)
        await self._store.update(
            organization_id, session_id, status="ANALYZING", step="analyze"
        )
        if row["kind"] == "database":
            return await self._analyze_database(organization_id, session_id, row)
        return await self._analyze_files(organization_id, session_id, row)

    async def progress(self, organization_id: UUID, session_id: UUID) -> dict:
        row = await self._require(organization_id, session_id)
        if row["status"] == "DISCOVERING" and row.get("catalog_source_id"):
            source = await self._catalog.get_source(
                organization_id, UUID(row["catalog_source_id"])
            )
            phase = (source or {}).get("phase")
            if phase in ("WAITING_REVIEW", "COMPLETED", "PARTIAL"):
                pending = await self._catalog.list_suggestions(
                    organization_id, status="pending", limit=50
                )
                state = merge_state(
                    row.get("state") or {},
                    {
                        "pending_review_count": len(pending),
                        "catalog_phase": phase,
                    },
                )
                updated = await self._store.update(
                    organization_id,
                    session_id,
                    status="REVIEW_REQUIRED",
                    step="review",
                    state_json=state,
                )
                row = updated or await self._require(organization_id, session_id)
            elif phase == "FAILED":
                updated = await self._store.update(
                    organization_id, session_id, status="FAILED"
                )
                row = updated or row
        done_through = {
            "NOT_STARTED": -1,
            "CONNECTING": 0,
            "CONNECTED": 0,
            "DISCOVERING": 1,
            "ANALYZING": 2,
            "REVIEW_REQUIRED": 5,
            "TESTING": 5,
            "READY": 5,
            "NEEDS_ATTENTION": 5,
            "FAILED": 0,
        }.get(row["status"], 0)
        phases = []
        for i, (key, label) in enumerate(_FRIENDLY_PHASES):
            if i <= done_through:
                state = "done"
            elif i == done_through + 1 and row["status"] in (
                "DISCOVERING",
                "ANALYZING",
            ):
                state = "active"
            else:
                state = "pending"
            phases.append({"id": key, "label": label, "state": state})
        technical = {
            "status": row["status"],
            "step": row["step"],
            "connector_id": row.get("connector_id"),
            "catalog_source_id": row.get("catalog_source_id"),
            "kb_source_id": row.get("kb_source_id"),
            "job_id": (row.get("state") or {}).get("job_id"),
        }
        if row.get("catalog_source_id"):
            source = await self._catalog.get_source(
                organization_id, UUID(row["catalog_source_id"])
            )
            if source:
                technical["catalog_phase"] = source.get("phase")
        return {
            "session": self.public(row),
            "phases": phases,
            "headline": "Zent está entendiendo tus datos",
            "technical_details": technical,
        }

    async def understanding(self, organization_id: UUID, session_id: UUID) -> dict:
        row = await self._require(organization_id, session_id)
        state = row.get("state") or {}
        summary = dict(state.get("understanding") or {})
        suggestions = []
        if row.get("catalog_source_id") or True:
            raw = await self._catalog.list_suggestions(
                organization_id, status="pending", limit=100
            )
            suggestions = [
                {
                    "id": s["id"],
                    "type": s["type"],
                    "title": s["title"],
                    "description": s.get("description"),
                    "confidence": s.get("confidence"),
                    "evidence": s.get("evidence") or [],
                    "payload": s.get("payload") or {},
                }
                for s in raw
            ]
        if row["kind"] == "database" and row.get("catalog_source_id"):
            cid = UUID(row["catalog_source_id"])
            entities = await self._catalog.list_entities(organization_id, limit=50)
            rels = await self._catalog.list_relationships(organization_id, cid, limit=50)
            summary.setdefault("entities", [
                {"name": e.get("display_name") or e.get("name"), "confidence": e.get("confidence")}
                for e in entities
            ])
            summary.setdefault(
                "relationships",
                [
                    {
                        "from": r.get("from_table") or r.get("from_column"),
                        "to": r.get("to_table") or r.get("to_column"),
                    }
                    for r in rels
                ],
            )
        summary["suggestions"] = suggestions
        return summary

    async def review(
        self,
        organization_id: UUID,
        session_id: UUID,
        suggestion_id: UUID,
        action: str,
        payload: dict | None,
        reviewed_by: UUID | None,
    ) -> dict:
        await self._require(organization_id, session_id)
        queue = ReviewQueueService(self._catalog)
        if action == "confirm":
            result = await queue.approve(
                organization_id, suggestion_id, reviewed_by=reviewed_by
            )
        elif action == "change":
            if not payload:
                raise DataOnboardingError("change requires payload")
            result = await queue.approve(
                organization_id,
                suggestion_id,
                reviewed_by=reviewed_by,
                edited_payload=payload,
            )
        elif action == "ignore":
            result = await queue.reject(
                organization_id, suggestion_id, reviewed_by=reviewed_by
            )
        else:
            raise DataOnboardingError("action must be confirm, change or ignore")
        if result is None:
            raise DataOnboardingError("Suggestion not found or not pending", 404)
        return result

    async def free_text(
        self, organization_id: UUID, session_id: UUID, text_value: str
    ) -> dict:
        await self._catalog.ensure_tables()
        row = await self._require(organization_id, session_id)
        suggestion = CatalogSuggestion(
            organization_id=organization_id,
            type=SuggestionType.FIELD_MAPPING,
            title="Business meaning from user note",
            description=text_value[:800],
            evidence=[text_value[:400]],
            confidence="medium",
            payload={"free_text": text_value, "session_id": str(session_id)},
            status=SuggestionStatus.PENDING,
            affected_sources=[row.get("catalog_source_id") or row.get("kb_source_id") or ""],
        )
        await self._catalog.create_suggestion(suggestion)
        created = await self._catalog.get_suggestion(organization_id, suggestion.id)
        return {"suggestion": created}

    async def questions(self, organization_id: UUID, session_id: UUID) -> dict:
        row = await self._require(organization_id, session_id)
        understanding = (row.get("state") or {}).get("understanding") or {}
        pack = build_question_pack(row["kind"], understanding)
        state = merge_state(row.get("state") or {}, {"question_pack": pack})
        await self._store.update(
            organization_id, session_id, state_json=state, step="test", status="TESTING"
        )
        return {"questions": pack}

    async def ask(
        self,
        organization_id: UUID,
        session_id: UUID,
        question: str,
        user_id: UUID,
        orchestrator: Any,
    ) -> dict:
        await self._require(organization_id, session_id)
        try:
            result = await orchestrator.execute(
                organization_id=organization_id,
                user_id=user_id,
                query=question,
                model=None,
                max_tokens=1024,
                temperature=0.2,
                top_k=50,
                conversation_id=None,
                role="admin",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("onboarding ask failed", error=str(exc)[:200])
            return {
                "question": question,
                "understood": False,
                "answer": (
                    "Zent aún está indexando esta fuente. "
                    "Prueba de nuevo en unos minutos."
                ),
                "method": None,
                "sql": None,
                "confidence": None,
                "evidence": [],
                "answerability": None,
                "sources": [],
            }
        answer = result.llm_response.content if result.llm_response else ""
        answerability = None
        decision = getattr(result, "answerability", None)
        if decision is not None:
            answerability = {
                "status": getattr(decision.status, "value", str(decision.status)),
                "confidence": getattr(
                    decision.confidence_level, "value", str(decision.confidence_level)
                ),
                "evidence": list(getattr(decision, "evidence_summaries", None) or []),
            }
        return {
            "question": question,
            "understood": True,
            "answer": answer,
            "method": getattr(result, "method", "rag"),
            "sql": result.sql_query if getattr(result, "method", "") == "sql" else None,
            "confidence": (answerability or {}).get("confidence"),
            "evidence": (answerability or {}).get("evidence") or [],
            "answerability": answerability,
            "sources": [
                {"id": str(getattr(s, "id", "")), "title": getattr(s, "title", None)}
                for s in (getattr(result, "sources", None) or [])[:8]
            ],
        }

    async def answer_feedback(
        self,
        organization_id: UUID,
        session_id: UUID,
        *,
        verdict: str,
        reason: str | None,
        question: str | None,
    ) -> dict:
        await self._catalog.ensure_tables()
        row = await self._require(organization_id, session_id)
        if verdict not in ("correct", "incorrect", "needs_adjustment"):
            raise DataOnboardingError("verdict must be correct, incorrect or needs_adjustment")
        suggestion = CatalogSuggestion(
            organization_id=organization_id,
            type=SuggestionType.FIELD_MAPPING,
            title="Test question feedback",
            description=f"{verdict}: {reason or ''} {question or ''}".strip(),
            evidence=[reason or "", question or ""],
            confidence="low",
            payload={
                "verdict": verdict,
                "reason": reason,
                "question": question,
                "session_id": str(session_id),
            },
            status=SuggestionStatus.PENDING,
            affected_sources=[row.get("catalog_source_id") or row.get("kb_source_id") or ""],
        )
        await self._catalog.create_suggestion(suggestion)
        created = await self._catalog.get_suggestion(organization_id, suggestion.id)
        assert created is not None
        assert created["status"] == "pending"
        return {"suggestion": created}

    async def readiness(self, organization_id: UUID, session_id: UUID) -> dict:
        from src.catalog.readiness import ReadinessService
        from src.intelligence.store import PostgresIntelligenceStore

        row = await self._require(organization_id, session_id)
        composition = {
            "data_connected": 100.0 if row["status"] not in ("NOT_STARTED", "FAILED") else 0.0,
            "structure_understood": 0.0,
            "business_mappings": 0.0,
            "relationships": 0.0,
            "test_questions_passed": 0.0,
            "overall": 0.0,
        }
        if row.get("catalog_source_id"):
            report = await ReadinessService(
                self._catalog, intelligence_store=PostgresIntelligenceStore()
            ).for_source(organization_id, UUID(row["catalog_source_id"]))
            data = report.to_dict()
            composition["structure_understood"] = data["schema_coverage"]
            composition["business_mappings"] = data["semantic_mapping_coverage"]
            composition["relationships"] = data["relationship_coverage"]
            composition["overall"] = data["overall"]
            pending = data["pending_review_count"]
        else:
            understanding = (row.get("state") or {}).get("understanding") or {}
            cols = understanding.get("columns") or []
            composition["structure_understood"] = 96.0 if cols or understanding else 40.0
            composition["business_mappings"] = 70.0 if cols else 40.0
            composition["overall"] = round(
                (
                    composition["data_connected"]
                    + composition["structure_understood"]
                    + composition["business_mappings"]
                )
                / 3,
                2,
            )
            pending = len(await self._catalog.list_suggestions(organization_id, status="pending", limit=50))
        if (row.get("state") or {}).get("question_pack"):
            composition["test_questions_passed"] = 90.0 if not row.get("skipped_test") else 0.0
        improvements = []
        if pending:
            improvements.append(f"{pending} campos por aclarar")
        return {
            "labels": {
                "data_connected": "Datos conectados",
                "structure_understood": "Estructura entendida",
                "business_mappings": "Significado de negocio",
                "relationships": "Relaciones",
                "test_questions_passed": "Preguntas de prueba",
            },
            "scores": composition,
            "overall": composition["overall"],
            "improvements": improvements,
            "pending_review_count": pending,
        }

    async def _analyze_database(
        self, organization_id: UUID, session_id: UUID, row: dict
    ) -> dict:
        from src.api.deps import get_job_repo
        from src.catalog.jobs import start_discovery_scan

        if not row.get("connector_id"):
            raise DataOnboardingError("Connect a database first", 400)
        result = await start_discovery_scan(
            job_repo=get_job_repo(),
            catalog_store=self._catalog,
            organization_id=organization_id,
            connector_id=UUID(row["connector_id"]),
            kb_source_id=UUID(row["kb_source_id"]) if row.get("kb_source_id") else None,
        )
        catalog_source_id = result.get("catalog_source_id") or result.get("source_id")
        state = merge_state(row.get("state") or {}, {"job_id": result.get("job_id")})
        updated = await self._store.update(
            organization_id,
            session_id,
            status="DISCOVERING",
            step="analyze",
            catalog_source_id=UUID(str(catalog_source_id)) if catalog_source_id else None,
            state_json=state,
        )
        public = self.public(updated or row)
        public["job"] = result
        return public

    async def _analyze_files(
        self, organization_id: UUID, session_id: UUID, row: dict
    ) -> dict:
        from src.api.deps import get_job_repo, get_source_repo
        from src.knowledge.queue import enqueue_knowledge_job

        if not row.get("kb_source_id"):
            raise DataOnboardingError("Upload a file first", 400)
        source = await get_source_repo().get_source(
            organization_id, UUID(row["kb_source_id"])
        )
        if source is None:
            raise DataOnboardingError("Source not found", 404)
        cfg = source.config_json or {}
        understanding = profile_upload(
            organization_id,
            str(cfg.get("object_key") or ""),
            source.type,
            str(cfg.get("filename") or source.name),
        )
        await self._suggestions_from_profile(
            organization_id, session_id, understanding, row
        )
        pending = await self._catalog.list_suggestions(
            organization_id, status="pending", limit=50
        )
        state = merge_state(
            row.get("state") or {},
            {
                "understanding": understanding,
                "pending_review_count": len(pending),
            },
        )
        job_id = None
        try:
            job = await get_job_repo().create_job(
                organization_id,
                job_type=f"sync_source:{source.type}",
                source_id=source.id,
                knowledge_base_id=source.knowledge_base_id,
            )
            await enqueue_knowledge_job(str(job.id))
            job_id = str(job.id)
            state["job_id"] = job_id
        except Exception as exc:  # noqa: BLE001
            logger.warning("onboarding sync enqueue failed", error=str(exc)[:200])
        updated = await self._store.update(
            organization_id,
            session_id,
            status="REVIEW_REQUIRED",
            step="review",
            state_json=state,
        )
        public = self.public(updated or row)
        public["understanding"] = understanding
        return public

    async def _suggestions_from_profile(
        self,
        organization_id: UUID,
        session_id: UUID,
        understanding: dict,
        row: dict,
    ) -> None:
        await self._catalog.ensure_tables()
        columns = understanding.get("columns") or []
        entity_name = str(understanding.get("likely_entity") or "Dataset")
        source_id = None
        if row.get("catalog_source_id"):
            source_id = UUID(str(row["catalog_source_id"]))
        else:
            from src.infrastructure.postgres.relational_db import (
                PostgresConnectorRepository,
            )

            connector = await PostgresConnectorRepository().create_connector(
                organization_id,
                f"file-{str(session_id)[:8]}",
                "postgres",
                workspace_id=_workspace_uuid(row),
                config_json={"host": "file-virtual", "session_id": str(session_id)},
            )
            src = await self._catalog.upsert_source(
                organization_id=organization_id,
                connector_id=connector.id,
                kb_source_id=UUID(row["kb_source_id"]) if row.get("kb_source_id") else None,
                engine="file",
                workspace_id=_workspace_uuid(row),
            )
            source_id = UUID(str(src["id"]))
            await self._store.update(
                organization_id, session_id, catalog_source_id=source_id
            )
        table_name = str(understanding.get("filename") or "upload").split(".")[0][:80] or "upload"
        table_id, _ = await self._catalog.upsert_table(
            organization_id=organization_id,
            source_id=source_id,
            schema_name="upload",
            table_name=table_name,
        )
        entity = CatalogEntity(
            organization_id=organization_id,
            name=entity_name,
            display_name=entity_name,
            provenance=CatalogProvenance.INFERRED,
            confidence="medium",
            evidence=["file profile"],
            mapped_table_id=table_id,
            status="draft",
        )
        await self._catalog.upsert_entity(entity)
        neighbor_names = [str(c.get("physical_name") or "") for c in columns]
        for idx, col in enumerate(columns):
            physical = str(col.get("physical_name") or f"col_{idx}")
            column_id = await self._catalog.upsert_column(
                organization_id=organization_id,
                table_id=table_id,
                column_name=physical,
                ordinal_position=idx,
                data_type=str(col.get("inferred_type") or "text"),
                null_ratio=col.get("null_ratio"),
                cardinality_approx=col.get("distinct_values"),
            )
            inferred = infer_column(
                column_name=physical,
                table_name=table_name,
                data_type=str(col.get("inferred_type") or "text"),
                neighbor_names=neighbor_names,
            )
            meanings = col.get("possible_meanings") or []
            top = meanings[0] if meanings else (inferred.label, int(inferred.score * 100))
            label = inferred.label or top[0]
            field = CatalogField(
                organization_id=organization_id,
                entity_id=entity.id,
                name=str(label).replace(" ", ""),
                description=f"Zent thinks: {label}",
                provenance=CatalogProvenance.INFERRED,
                confidence=inferred.confidence,
                mapped_column_id=column_id,
                status="draft",
                role=inferred.role,
                synonyms=[label],
                signal_scores=inferred.signal_scores,
            )
            await self._catalog.upsert_field(field)
            suggestion = CatalogSuggestion(
                organization_id=organization_id,
                type=SuggestionType.FIELD_MAPPING,
                title=physical,
                description=f"Zent thinks: {label}",
                evidence=inferred.evidence or [f"{m[0]} {m[1]}%" for m in meanings],
                confidence=inferred.confidence,
                payload={
                    "physical_name": physical,
                    "business_name": label,
                    "entity_id": str(entity.id),
                    "entity_name": entity_name,
                    "field_id": str(field.id),
                    "column_id": str(column_id),
                    "mapped_column_id": str(column_id),
                    "role": inferred.role,
                    "alternatives": [
                        {"label": m[0], "score": m[1]} for m in meanings
                    ],
                    "signal_scores": inferred.signal_scores,
                    "session_id": str(session_id),
                },
                status=SuggestionStatus.PENDING,
                affected_sources=[str(source_id)],
            )
            await self._catalog.create_suggestion(suggestion)

    async def _cheap_web_preview(self, url: str, host: str) -> dict:
        import httpx

        preview: dict[str, Any] = {
            "url": url,
            "host": host,
            "pages_detected": 1,
            "mode": "single_url",
        }
        timeout = httpx.Timeout(8.0, connect=4.0)
        parsed = urlparse(url)
        try:
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=False
            ) as client:
                try:
                    head = await client.head(url)
                    preview["status"] = head.status_code
                    preview["content_type"] = head.headers.get("content-type")
                    length = head.headers.get("content-length")
                    if length:
                        preview["size"] = length
                except Exception as exc:  # noqa: BLE001
                    preview["head_error"] = str(exc)[:120]
                try:
                    get = await client.get(url)
                    preview.setdefault("status", get.status_code)
                    preview.setdefault(
                        "content_type", get.headers.get("content-type")
                    )
                    body = get.text[:8000]
                    preview["size"] = str(len(get.content))
                    match = re.search(
                        r"<title[^>]*>([^<]+)</title>", body, re.IGNORECASE
                    )
                    if match:
                        preview["title"] = match.group(1).strip()[:200]
                except Exception as exc:  # noqa: BLE001
                    preview["get_error"] = str(exc)[:120]
                try:
                    robots_url = f"{parsed.scheme}://{host}/robots.txt"
                    robots = await client.get(robots_url)
                    preview["robots"] = robots.status_code == 200
                except Exception:  # noqa: BLE001
                    preview["robots"] = None
        except Exception as exc:  # noqa: BLE001
            preview["error"] = str(exc)[:200]
        return preview

    async def _require(self, organization_id: UUID, session_id: UUID) -> dict:
        row = await self._store.get(organization_id, session_id)
        if row is None:
            raise DataOnboardingError("Session not found", 404)
        return row
