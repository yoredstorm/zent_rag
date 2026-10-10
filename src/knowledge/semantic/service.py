# =============================================================================
# SemanticIngestionService — manifiesto + plan de ventanas, fail-soft
# =============================================================================
# El engine llama a este servicio en los puntos reales de la ingesta:
#   begin -> parsed -> indexed -> finished | failed
#
# Reglas:
#   - Un fallo del servicio JAMÁS rompe la ingesta (se loguea y continúa).
#   - off: no se escribe nada (comportamiento actual intacto).
#   - shadow: manifiesto + plan persistidos (observabilidad), sin cambios de flujo.
#   - active: además, reanudación selectiva cuando la fuente no cambió y la
#     versión del pipeline es la misma (reprocesar lo mínimo).
# =============================================================================
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID

from src.core.domain.knowledge_v2 import StructuredDocument
from src.infrastructure.observability.logging_config import get_logger
from src.knowledge.reconstruction.contracts import SCHEMA_VERSION as RECONSTRUCTION_VERSION
from src.knowledge.structure.base import token_count
from src.knowledge.understanding.versions import (
    PARSER_VERSION,
    UNDERSTANDING_SCHEMA_VERSION,
)

from .contracts import (
    SEMANTIC_INGESTION_VERSION,
    SEMANTIC_STATE_VERSION,
    STAGE_FLAGS,
    STATE_SELECTOR_VERSION,
    WINDOW_PLAN_VERSION,
    WINDOW_UNDERSTANDING_VERSION,
    IngestionStage,
    SemanticWindowPlan,
    SourceIngestionManifest,
    StageStatus,
    manifest_with,
    set_stage,
    window_result_from_dict,
)
from .fabric import (
    FABRIC_VERSION,
    FabricRetrievalContext,
    SemanticFabricBuilder,
    build_retrieval_context,
    projection_fingerprint,
)
from .global_model import GLOBAL_MODEL_VERSION, GlobalModelBuilder
from .planner import SemanticWindowPlanner
from .processor import SemanticWindowProcessor, WindowProcessingOutcome
from .regional import REGIONAL_VERSION, RegionalModelBuilder
from .stitcher import STITCH_VERSION, SemanticStitcher, StitchOutcome, stitch_fingerprint
from .threads import THREAD_VERSION

logger = get_logger(__name__)

_MODES = ("off", "shadow", "active", "canary")


def _settings():
    try:
        from src.core.config import get_settings

        return get_settings()
    except Exception:  # noqa: BLE001
        return None


def _setting(name: str, default):
    settings = _settings()
    if settings is None:
        return default
    return getattr(settings, name, default)


def semantic_versions() -> dict:
    """Versiones que definen si un manifiesto sigue vigente (selectivo)."""
    return {
        "semantic_ingestion_version": SEMANTIC_INGESTION_VERSION,
        "window_plan_version": WINDOW_PLAN_VERSION,
        "window_understanding_version": WINDOW_UNDERSTANDING_VERSION,
        "state_version": SEMANTIC_STATE_VERSION,
        "selector_version": STATE_SELECTOR_VERSION,
        "thread_version": THREAD_VERSION,
        "stitch_version": STITCH_VERSION,
        "regional_version": REGIONAL_VERSION,
        "global_version": GLOBAL_MODEL_VERSION,
        "fabric_version": FABRIC_VERSION,
        "parser_version": PARSER_VERSION,
        "understanding_version": UNDERSTANDING_SCHEMA_VERSION,
        "reconstruction_version": RECONSTRUCTION_VERSION,
        # Fase 3: la comprensión por ventana YA procesa y es etapa requerida.
        # Fase 5 agrega "stitching"; Fase 7 agrega "global" (invalida
        # manifiestos viejos una sola vez, como manda la invalidación selectiva).
        "required_stages": [
            "parsing",
            "indexing",
            "semantic_windows",
            "stitching",
            "global",
        ],
        "semantic_required": True,
    }


def raw_fingerprint(data: bytes) -> str:
    return hashlib.sha256(data or b"").hexdigest()


def _observe_semantics(*, organization_id, outcome) -> None:
    """Métricas best-effort de ventanas/threads (nunca frenan la ingesta)."""
    try:
        from src.infrastructure.observability.metrics import (
            knowledge_semantic_threads_total,
            knowledge_semantic_windows_total,
        )

        org = str(organization_id)
        for status, value in (
            ("processed", outcome.processed),
            ("skipped", outcome.skipped),
            ("failed", outcome.failed),
        ):
            if value:
                knowledge_semantic_windows_total.labels(
                    organization_id=org, status=status
                ).inc(int(value))
        for status, value in (
            ("opened", outcome.threads_opened),
            ("resolved", outcome.threads_resolved),
            ("ambiguous", outcome.threads_ambiguous),
        ):
            if value:
                knowledge_semantic_threads_total.labels(
                    organization_id=org, status=status
                ).inc(int(value))
    except Exception:  # noqa: BLE001
        return


def _checkpoint(manifest: SourceIngestionManifest, stage: str, payload: dict):
    """Fase 2: checkpoint por etapa (physical/semantic/stitching/regional/global).

    Se persiste en el manifiesto; un retry reanuda desde el último checkpoint
    real sin reprocesar lo completo.
    """
    checkpoints = dict(manifest.details.get("checkpoints") or {})
    checkpoints[str(stage)] = {
        **dict(payload or {}),
        "at": datetime.now(timezone.utc).isoformat(),
    }
    return manifest_with(
        manifest, details={**manifest.details, "checkpoints": checkpoints}
    )


def _observe_fabric(*, organization_id, projection) -> None:
    """Métricas best-effort de nodos del fabric por tipo."""
    try:
        from src.infrastructure.observability.metrics import (
            knowledge_semantic_fabric_nodes_total,
        )

        counts: dict[str, int] = {}
        for node in projection.nodes:
            counts[node.node_type] = counts.get(node.node_type, 0) + 1
        org = str(organization_id)
        for node_type, value in counts.items():
            knowledge_semantic_fabric_nodes_total.labels(
                organization_id=org, node_type=node_type
            ).inc(int(value))
    except Exception:  # noqa: BLE001
        return


class SemanticIngestionService:
    """Manifiesto por fuente + plan de ventanas (Fases 1-2)."""

    def __init__(
        self,
        store: object,
        *,
        planner: SemanticWindowPlanner | None = None,
        mode: str | None = None,
        llm_provider: object | None = None,
        processor: SemanticWindowProcessor | None = None,
        stitcher: SemanticStitcher | None = None,
        regional_builder: RegionalModelBuilder | None = None,
        global_builder: GlobalModelBuilder | None = None,
        fabric_builder: SemanticFabricBuilder | None = None,
    ) -> None:
        self._store = store
        self._planner = planner or SemanticWindowPlanner()
        self._mode = mode
        self._processor = processor or SemanticWindowProcessor(
            store, llm_provider=llm_provider  # type: ignore[arg-type]
        )
        self._stitcher = stitcher or SemanticStitcher()
        self._regional = regional_builder or RegionalModelBuilder()
        self._global = global_builder or GlobalModelBuilder()
        self._fabric = fabric_builder or SemanticFabricBuilder()

    @property
    def mode(self) -> str:
        value = self._mode
        if value is None:
            value = str(
                _setting("KNOWLEDGE_SEMANTIC_INGESTION_MODE", "off") or "off"
            ).strip().lower()
        return value if value in _MODES else "off"

    def mode_for(self, *, organization_id=None, workspace_id=None) -> str:
        from .rollout import resolve_semantic_mode

        return resolve_semantic_mode(
            organization_id=organization_id,
            workspace_id=workspace_id,
            global_mode=self.mode,
        )

    def allows(self, *, organization_id=None, workspace_id=None) -> bool:
        return self.mode_for(
            organization_id=organization_id, workspace_id=workspace_id
        ) != "off"

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    @property
    def active(self) -> bool:
        return self.mode == "active"

    @property
    def canary_percentage(self) -> int:
        try:
            value = int(
                _setting("KNOWLEDGE_SEMANTIC_INGESTION_CANARY_PERCENTAGE", 0) or 0
            )
        except (TypeError, ValueError):
            value = 0
        return max(0, min(100, value))

    def should_process(
        self,
        *,
        organization_id,
        source_id,
        external_id: str,
        workspace_id=None,
    ) -> bool:
        """Canary: selección determinista por org+source+external_id.

        shadow/active procesan siempre; canary solo el porcentaje configurado;
        off nunca. El rollout de workspace/org pisa el modo global.
        """
        mode = self.mode_for(
            organization_id=organization_id, workspace_id=workspace_id
        )
        if mode == "off":
            return False
        if mode != "canary":
            return True
        percentage = self.canary_percentage
        if percentage <= 0:
            return False
        if percentage >= 100:
            return True
        digest = hashlib.sha256(
            f"{organization_id}|{source_id}|{external_id}".encode("utf-8")
        ).digest()
        bucket = int.from_bytes(digest[:4], "big") % 100
        return bucket < percentage

    @property
    def planner(self) -> SemanticWindowPlanner:
        return self._planner

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------
    async def begin(
        self,
        *,
        organization_id: UUID,
        source_id: UUID | None,
        workspace_id: UUID | None,
        external_id: str,
        source_type: str,
        raw_data: bytes,
        versions: dict | None = None,
        document_id: UUID | None = None,
        force: bool = False,
    ) -> bool:
        """Registra el inicio. True = fuente ya completa y vigente (SKIP)."""
        scoped = self.mode_for(
            organization_id=organization_id, workspace_id=workspace_id
        )
        if scoped == "off" or source_id is None:
            return False
        raw_hash = raw_fingerprint(raw_data)
        current_versions = dict(versions or semantic_versions())
        try:
            existing = await self._store.get_manifest(
                organization_id, source_id=source_id, external_id=external_id
            )
        except Exception as exc:  # noqa: BLE001 — el manifiesto nunca frena
            logger.warning(
                "Semantic ingestion manifest lookup failed",
                external_id=external_id,
                error=str(exc)[:200],
            )
            return False
        if (
            not force
            and scoped == "active"
            and existing is not None
            and existing.raw_fingerprint == raw_hash
            and existing.versions == current_versions
            and existing.pipeline_complete
        ):
            logger.info(
                "Semantic ingestion resume: source unchanged and complete",
                external_id=external_id,
                source_id=str(source_id),
            )
            return True
        now = datetime.now(timezone.utc)
        if existing is None:
            manifest = SourceIngestionManifest(
                organization_id=organization_id,
                source_id=source_id,
                workspace_id=workspace_id,
                document_id=document_id,
                external_id=external_id,
                source_type=source_type,
                raw_fingerprint=raw_hash,
                total_bytes=len(raw_data or b""),
                versions=current_versions,
                started_at=now,
            )
        elif existing.raw_fingerprint != raw_hash:
            # Fuente nueva: reset de etapas y contadores, historial de versión
            # anterior preservado en details.
            history = list(existing.details.get("previous_versions") or ())
            history.append(
                {
                    "raw_fingerprint": existing.raw_fingerprint,
                    "content_hash": existing.content_hash,
                    "coverage_ratio": existing.coverage_ratio,
                    "at": existing.updated_at.isoformat()
                    if existing.updated_at
                    else None,
                }
            )
            manifest = manifest_with(
                existing,
                raw_fingerprint=raw_hash,
                total_bytes=len(raw_data or b""),
                content_hash="",
                document_id=document_id,
                parsing_complete=False,
                semantic_complete=False,
                stitching_complete=False,
                global_synthesis_complete=False,
                indexing_complete=False,
                pipeline_complete=False,
                completed_at=None,
                started_at=now,
                versions=current_versions,
                stages={},
                details={"previous_versions": history[-5:]},
            )
        else:
            manifest = manifest_with(
                existing,
                total_bytes=len(raw_data or b""),
                versions=current_versions,
                pipeline_complete=False,
                completed_at=None,
            )
        manifest = set_stage(manifest, IngestionStage.PARSING, StageStatus.RUNNING)
        await self._save(manifest, external_id=external_id)
        return False

    async def parsed(self, document: StructuredDocument) -> SemanticWindowPlan | None:
        """Marca parsing/understanding y planifica ventanas (soft boundaries)."""
        if not self.allows(
            organization_id=document.organization_id,
            workspace_id=document.workspace_id,
        ):
            return None
        manifest = await self._load(document)
        if manifest is None:
            return None
        blocks = list(document.blocks or ())
        estimated = sum(max(1, token_count(block.text)) for block in blocks)
        manifest = manifest_with(
            manifest,
            document_id=document.id,
            content_hash=str(document.content_hash or ""),
            structural_units=len(blocks),
            estimated_tokens=estimated,
            parsing_complete=True,
        )
        manifest = set_stage(manifest, IngestionStage.PARSING, StageStatus.COMPLETE)
        manifest = set_stage(
            manifest, IngestionStage.UNDERSTANDING, StageStatus.COMPLETE
        )
        plan: SemanticWindowPlan | None = None
        try:
            plan = self._planner.plan(document)
        except Exception as exc:  # noqa: BLE001 — el plan nunca frena la ingesta
            logger.warning(
                "Semantic window planning failed",
                document_id=str(getattr(document, "id", "")),
                error=str(exc)[:250],
            )
        if plan is not None and plan.window_count > 0 and document.id is not None:
            try:
                await self._store.save_window_plan(
                    document.organization_id,
                    source_id=document.source_id,
                    workspace_id=document.workspace_id,
                    document_id=document.id,
                    plan=plan,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Semantic window plan persist failed",
                    document_id=str(document.id),
                    error=str(exc)[:250],
                )
            manifest = manifest_with(
                manifest,
                windows_total=plan.window_count,
                details={
                    **manifest.details,
                    "window_plan": {
                        "fingerprint": plan.fingerprint,
                        "version": plan.version,
                        "model": plan.model,
                        "model_source": plan.model_source,
                        "profile": plan.profile,
                        "hard_limit_tokens": plan.hard_limit_tokens,
                        "target_tokens": plan.target_tokens,
                        "windows": plan.window_count,
                        "soft_extensions": plan.soft_extensions,
                        "split_units": plan.split_units,
                    },
                },
            )
            manifest = set_stage(
                manifest, IngestionStage.SEMANTIC_WINDOWS, "planned"
            )
        manifest = _checkpoint(
            manifest,
            "physical",
            {
                "document_id": str(document.id),
                "structural_units": len(blocks),
                "estimated_tokens": estimated,
                "windows_total": manifest.windows_total,
            },
        )
        await self._save(manifest, external_id=document.external_id)
        return plan

    async def indexed(
        self,
        document: StructuredDocument,
        *,
        indexed_units: int,
        window_plan: SemanticWindowPlan | None = None,
    ) -> None:
        if not self.allows(
            organization_id=document.organization_id,
            workspace_id=document.workspace_id,
        ):
            return
        manifest = await self._load(document)
        if manifest is None:
            return
        manifest = manifest_with(
            manifest,
            processed_units=int(indexed_units or 0),
            indexing_complete=bool(indexed_units is not None and indexed_units >= 0),
            windows_total=(
                window_plan.window_count
                if window_plan is not None and window_plan.window_count
                else manifest.windows_total
            ),
        )
        manifest = set_stage(manifest, IngestionStage.INDEXING, StageStatus.COMPLETE)
        await self._save(manifest, external_id=document.external_id)

    async def process_windows(
        self,
        document: StructuredDocument,
        *,
        plan: SemanticWindowPlan | None = None,
        enrichment=None,
        compiled=None,
        reset: bool = False,
    ) -> WindowProcessingOutcome | None:
        """Fase 3: comprensión local por ventana + SemanticState (checkpoint).

        Fail-soft: un fallo del procesador no frena la ingesta; el manifiesto
        refleja PARTIAL/FAILED y el próximo sync reanuda las ventanas stale.
        """
        if not self.allows(
            organization_id=document.organization_id,
            workspace_id=document.workspace_id,
        ):
            return None
        if plan is None:
            try:
                plan = self._planner.plan(document)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Semantic window plan (processing) failed",
                    document_id=str(getattr(document, "id", "")),
                    error=str(exc)[:250],
                )
                return None
        outcome: WindowProcessingOutcome | None = None
        try:
            outcome = await self._processor.process(
                document,
                plan,
                enrichment=enrichment,
                compiled=compiled,
                reset=reset,
            )
        except Exception as exc:  # noqa: BLE001 — nunca frena la ingesta
            logger.warning(
                "Semantic window processing failed",
                document_id=str(getattr(document, "id", "")),
                error=str(exc)[:300],
            )
            return None
        manifest = await self._load(document)
        if manifest is None:
            return outcome
        if plan.window_count == 0:
            semantic_complete = True
            stage_status = StageStatus.COMPLETE
        else:
            semantic_complete = outcome.complete
            stage_status = (
                StageStatus.COMPLETE
                if outcome.failed == 0
                else StageStatus.PARTIAL
            )
        manifest = manifest_with(
            manifest,
            windows_processed=outcome.processed + outcome.skipped,
            semantic_units=outcome.items_total,
            unresolved_units=outcome.unresolved_total,
            semantic_complete=semantic_complete,
            details={
                **manifest.details,
                "window_processing": {
                    **outcome.to_dict(),
                    "llm_tokens": outcome.llm_tokens,
                    "state_fingerprint": (
                        outcome.state.fingerprint if outcome.state else None
                    ),
                },
            },
        )
        manifest = set_stage(
            manifest, IngestionStage.SEMANTIC_WINDOWS, stage_status
        )
        manifest = _checkpoint(
            manifest,
            "semantic",
            {
                "windows_processed": outcome.processed + outcome.skipped,
                "windows_total": plan.window_count,
                "failed": outcome.failed,
                "last_window": (
                    plan.windows[-1].window_index if plan.windows else -1
                ),
                "threads_open": outcome.threads_open,
            },
        )
        await self._save(manifest, external_id=document.external_id)
        _observe_semantics(
            organization_id=document.organization_id, outcome=outcome
        )
        await self._run_stitching(document, outcome=outcome, plan=plan)
        return outcome

    async def _run_stitching(
        self,
        document: StructuredDocument,
        *,
        outcome: WindowProcessingOutcome,
        plan: SemanticWindowPlan | None = None,
    ) -> StitchOutcome | None:
        """Fase 5: unidades + relaciones + cierre de threads (checkpoint)."""
        try:
            rows = await self._store.list_window_results(
                document.organization_id,
                document_id=document.id,
                include_items=True,
            )
            results = [window_result_from_dict(row) for row in rows]
            threads = await self._store.list_threads(
                document.organization_id, document_id=document.id
            )
            stitch = self._stitcher.stitch(
                document=document, results=results, threads=threads
            )
            await self._store.replace_stitch(
                document.organization_id,
                workspace_id=document.workspace_id,
                source_id=document.source_id,
                document_id=document.id,
                units=list(stitch.units),
                relations=list(stitch.relations),
            )
            if stitch.threads_updated:
                await self._store.save_threads(
                    document.organization_id,
                    workspace_id=document.workspace_id,
                    source_id=document.source_id,
                    document_id=document.id,
                    threads=list(stitch.threads_updated),
                )
            # Fase 6: modelos regionales (capítulo/sección/documento).
            regional_models = self._regional.build(
                document=document,
                plan=plan,
                results=results,
                units=list(stitch.units),
                relations=list(stitch.relations),
                threads=(
                    list(stitch.threads_updated) if stitch.threads_updated else threads
                ),
            )
            await self._store.replace_regional_models(
                document.organization_id,
                workspace_id=document.workspace_id,
                source_id=document.source_id,
                document_id=document.id,
                models=regional_models,
            )
            # Fase 7: síntesis global estructurada (no resumen).
            global_model = self._global.build(
                document=document,
                regions=regional_models,
                units=list(stitch.units),
                relations=list(stitch.relations),
                threads=(
                    list(stitch.threads_updated) if stitch.threads_updated else threads
                ),
            )
            await self._store.replace_global_model(
                document.organization_id,
                workspace_id=document.workspace_id,
                source_id=document.source_id,
                document_id=document.id,
                model=global_model,
            )
            # Fase 8: Semantic Fabric (nodos/aristas) + identidad cross-source.
            labels = [unit.label for unit in stitch.units if unit.label][:500]
            existing_nodes = await self._store.find_fabric_nodes_by_labels(
                document.organization_id,
                labels,
                exclude_document_id=document.id,
            )
            projection = self._fabric.project(
                document=document,
                global_model=global_model,
                units=list(stitch.units),
                relations=list(stitch.relations),
                existing_nodes=existing_nodes,
            )
            _observe_fabric(
                organization_id=document.organization_id, projection=projection
            )
            await self._store.replace_fabric(
                document.organization_id,
                workspace_id=document.workspace_id,
                source_id=document.source_id,
                document_id=document.id,
                nodes=list(projection.nodes),
                edges=list(projection.edges),
            )
            await self._store.save_identity_candidates(
                document.organization_id,
                candidates=list(projection.identity_candidates),
            )
        except Exception as exc:  # noqa: BLE001 — el stitch nunca frena la ingesta
            logger.warning(
                "Semantic stitching failed",
                document_id=str(getattr(document, "id", "")),
                error=str(exc)[:300],
            )
            return None
        manifest = await self._load(document)
        if manifest is None:
            return stitch
        complete = outcome.complete
        # Fase 15: fingerprints por etapa (invalidación selectiva auditable).
        stage_fingerprints = {
            "windows": hashlib.sha256(
                "|".join(
                    f"{result.window_index}:{result.fingerprint}"
                    for result in sorted(results, key=lambda item: item.window_index)
                ).encode("utf-8")
            ).hexdigest(),
            "stitch": stitch_fingerprint(stitch),
            "regional": hashlib.sha256(
                "|".join(model.fingerprint for model in regional_models).encode(
                    "utf-8"
                )
            ).hexdigest(),
            "global": global_model.fingerprint,
            "fabric": projection_fingerprint(projection),
        }
        manifest = _checkpoint(
            manifest,
            "stitching",
            {
                "units": len(stitch.units),
                "relations": len(stitch.relations),
                "threads_closed": stitch.threads_closed,
                "fingerprint": stage_fingerprints["stitch"],
            },
        )
        manifest = _checkpoint(
            manifest,
            "regional",
            {
                "regions": len(regional_models),
                "fingerprint": stage_fingerprints["regional"],
            },
        )
        manifest = _checkpoint(
            manifest,
            "global",
            {"fingerprint": stage_fingerprints["global"]},
        )
        manifest = _checkpoint(
            manifest,
            "fabric",
            {
                "nodes": len(projection.nodes),
                "edges": len(projection.edges),
                "identity_candidates": len(projection.identity_candidates),
                "fingerprint": stage_fingerprints["fabric"],
            },
        )
        manifest = manifest_with(
            manifest,
            stitching_complete=complete,
            global_synthesis_complete=complete,
            details={
                **manifest.details,
                "stage_fingerprints": stage_fingerprints,
                "stitching": stitch.to_dict(),
                "regional_models": {
                    "count": len(regional_models),
                    "regions": [
                        model.region_id for model in regional_models[:64]
                    ],
                    "version": REGIONAL_VERSION,
                },
                "global_model": {
                    "glossary": len(global_model.glossary),
                    "clusters": len(global_model.semantic_clusters),
                    "unresolved": len(global_model.unresolved_items),
                    "cross_region_relations": global_model.stats.get(
                        "cross_region_relations", 0
                    ),
                    "fingerprint": global_model.fingerprint,
                    "version": GLOBAL_MODEL_VERSION,
                },
                "fabric": {
                    **projection.to_dict(),
                    "identity_candidates": len(projection.identity_candidates),
                },
            },
        )
        manifest = set_stage(
            manifest,
            IngestionStage.STITCHING,
            StageStatus.COMPLETE if complete else StageStatus.PARTIAL,
        )
        manifest = set_stage(
            manifest,
            IngestionStage.GLOBAL,
            StageStatus.COMPLETE if complete else StageStatus.PARTIAL,
        )
        await self._save(manifest, external_id=document.external_id)
        return stitch

    async def finished(
        self, document: StructuredDocument, *, compiled: bool | None = None
    ) -> None:
        """Cierra el manifiesto: pipeline completo si las etapas requeridas corrieron."""
        if not self.allows(
            organization_id=document.organization_id,
            workspace_id=document.workspace_id,
        ):
            return
        manifest = await self._load(document)
        if manifest is None:
            return
        required = manifest.versions.get("required_stages")
        if required is None:
            required = ["parsing", "indexing"]
            if manifest.versions.get("semantic_required"):
                required += ["semantic_windows", "stitching", "global"]
        complete = True
        for stage in required:
            flag = STAGE_FLAGS.get(str(stage))
            if flag is None:
                continue
            if not bool(getattr(manifest, flag, False)):
                complete = False
                break
        manifest = manifest_with(
            manifest,
            pipeline_complete=bool(complete),
            completed_at=(
                datetime.now(timezone.utc) if complete else manifest.completed_at
            ),
        )
        if compiled is not False:
            manifest = set_stage(
                manifest, IngestionStage.COMPILING, StageStatus.COMPLETE
            )
        await self._save(manifest, external_id=document.external_id)

    async def knowledge_probes(
        self, document: StructuredDocument
    ) -> tuple[list[dict], dict] | None:
        """Fase 14: probes V2 derivados del fabric (nodos + dependencias)."""
        if not self.allows(
            organization_id=document.organization_id,
            workspace_id=document.workspace_id,
        ):
            return None
        try:
            nodes = await self._store.list_fabric_nodes(
                document.organization_id, document_id=document.id, limit=20000
            )
            edges = await self._store.list_fabric_edges(
                document.organization_id, document_id=document.id, limit=50000
            )
        except Exception as exc:  # noqa: BLE001 — acceptance nunca frena la ingesta
            logger.warning(
                "Knowledge acceptance probes failed",
                document_id=str(getattr(document, "id", "")),
                error=str(exc)[:250],
            )
            return None
        if not nodes:
            return None
        from .acceptance_v2 import build_knowledge_probes

        return build_knowledge_probes(
            document=document, nodes=nodes, edges=edges
        )

    async def fabric_context(
        self, document: StructuredDocument
    ) -> FabricRetrievalContext | None:
        """Fase 9: contexto de fabric para enriquecer retrieval units.

        off = sin enriquecimiento; shadow = ids/vecindad en payload (los
        retrievers actuales los ignoran); active = además labels en sparse.
        Fail-soft: sin fabric persistido devuelve None.
        """
        if not self.allows(
            organization_id=document.organization_id,
            workspace_id=document.workspace_id,
        ):
            return None
        from .rollout import resolve_fabric_mode

        mode = resolve_fabric_mode(
            organization_id=document.organization_id,
            workspace_id=document.workspace_id,
            global_semantic_mode=self.mode,
            global_fabric_mode=str(
                _setting("KNOWLEDGE_SEMANTIC_FABRIC_UNITS_MODE", "shadow") or "shadow"
            ),
        )
        if mode == "off":
            return None
        try:
            nodes = await self._store.list_fabric_nodes(
                document.organization_id,
                document_id=document.id,
                limit=20000,
            )
            edges = await self._store.list_fabric_edges(
                document.organization_id,
                document_id=document.id,
                limit=50000,
            )
        except Exception as exc:  # noqa: BLE001 — el enriquecimiento es opcional
            logger.warning(
                "Semantic fabric context failed",
                document_id=str(getattr(document, "id", "")),
                error=str(exc)[:250],
            )
            return None
        if not nodes:
            return None
        return build_retrieval_context(
            nodes, edges, document_id=document.id, mode=mode
        )

    async def failed(
        self,
        *,
        organization_id: UUID,
        source_id: UUID | None,
        external_id: str,
        error: str,
    ) -> None:
        if not self.enabled or source_id is None:
            return
        try:
            manifest = await self._store.get_manifest(
                organization_id, source_id=source_id, external_id=external_id
            )
            if manifest is None:
                return
            stage = (
                IngestionStage.INDEXING
                if manifest.parsing_complete
                else IngestionStage.PARSING
            )
            manifest = set_stage(manifest, stage, StageStatus.FAILED)
            details = dict(manifest.details)
            failures = list(details.get("failures") or ())
            failures.append(
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "stage": str(stage),
                    "error": str(error)[:500],
                }
            )
            details["failures"] = failures[-10:]
            details["last_error"] = str(error)[:500]
            manifest = manifest_with(
                manifest,
                pipeline_complete=False,
                details=details,
            )
            await self._save(manifest, external_id=external_id)
        except Exception as exc:  # noqa: BLE001 — nunca frena la ingesta
            logger.debug("Semantic ingestion failure mark failed", error=str(exc)[:200])

    # ------------------------------------------------------------------
    async def _load(self, document: StructuredDocument) -> SourceIngestionManifest | None:
        if document.source_id is None:
            return None
        try:
            # Sin document_id: el manifiesto es por (source, external_id); el id
            # del documento cambia al re-parsear y no debe partir el historial.
            return await self._store.get_manifest(
                document.organization_id,
                source_id=document.source_id,
                external_id=document.external_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Semantic ingestion manifest load failed",
                document_id=str(getattr(document, "id", "")),
                error=str(exc)[:200],
            )
            return None

    async def _save(self, manifest: SourceIngestionManifest, *, external_id: str) -> None:
        try:
            await self._store.upsert_manifest(manifest)
        except Exception as exc:  # noqa: BLE001 — la ingesta continúa
            logger.warning(
                "Semantic ingestion manifest save failed",
                external_id=external_id,
                error=str(exc)[:250],
            )


__all__ = [
    "SemanticIngestionService",
    "raw_fingerprint",
    "semantic_versions",
]
