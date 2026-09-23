# =============================================================================
# Ports — CompanyDiscoveryRepository (candidatos + corridas)
# =============================================================================
# Puerto del motor de descubrimiento. organization_id obligatorio en toda
# operación. Storage-agnostic igual que el Company Graph: el motor no conoce
# SQL ni ningún motor externo.
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from src.core.domain.company_discovery import (
    CandidateKind,
    DiscoveryCandidate,
    DiscoveryRun,
    DiscoverySourceKind,
    DiscoveryStage,
)


class CompanyDiscoveryRepository(ABC):
    """Candidatos descubiertos y corridas del motor."""

    # -- Candidatos ----------------------------------------------------
    @abstractmethod
    async def upsert_candidate(
        self, candidate: DiscoveryCandidate
    ) -> tuple[DiscoveryCandidate, bool]:
        """Inserta o acumula por (org, kind, natural_key).

        Devuelve (candidato persistido, es_nuevo). Nunca pierde evidencia
        previa: el llamante entrega el candidato ya fusionado.
        """
        ...

    @abstractmethod
    async def get_candidate(
        self, organization_id: UUID, candidate_id: UUID
    ) -> DiscoveryCandidate | None:
        """Candidato o None. Nunca cruza organization_id."""
        ...

    @abstractmethod
    async def get_by_natural_key(
        self, organization_id: UUID, kind: CandidateKind, natural_key: str
    ) -> DiscoveryCandidate | None:
        """Candidato por clave canónica de dedupe (scoped)."""
        ...

    @abstractmethod
    async def find_candidates(
        self,
        organization_id: UUID,
        *,
        kinds: tuple[CandidateKind, ...] = (),
        stages: tuple[DiscoveryStage, ...] = (),
        source_kinds: tuple[DiscoverySourceKind, ...] = (),
        min_confidence: float | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DiscoveryCandidate]:
        """Búsqueda paginada y filtrada (scoped)."""
        ...

    @abstractmethod
    async def count_candidates(
        self,
        organization_id: UUID,
        *,
        kinds: tuple[CandidateKind, ...] = (),
        stages: tuple[DiscoveryStage, ...] = (),
    ) -> int:
        """Conteo para paginación y métricas."""
        ...

    @abstractmethod
    async def update_candidate_state(
        self,
        candidate: DiscoveryCandidate,
    ) -> DiscoveryCandidate:
        """Persiste etapa/revisión/materialización de un candidato."""
        ...

    @abstractmethod
    async def stats(self, organization_id: UUID) -> dict:
        """Conteos por tipo y etapa (observabilidad §24)."""
        ...

    # -- Corridas / jobs ----------------------------------------------
    @abstractmethod
    async def enqueue_run(
        self,
        organization_id: UUID,
        *,
        trigger: str,
        source_kinds: tuple[DiscoverySourceKind, ...] = (),
    ) -> DiscoveryRun:
        """Encola una corrida pendiente."""
        ...

    @abstractmethod
    async def start_run(
        self,
        organization_id: UUID,
        *,
        trigger: str,
        source_kinds: tuple[DiscoverySourceKind, ...] = (),
    ) -> DiscoveryRun:
        """Abre una corrida en estado RUNNING (ejecución en este request)."""
        ...

    @abstractmethod
    async def claim_pending_run(self) -> DiscoveryRun | None:
        """Toma una corrida pendiente (FOR UPDATE SKIP LOCKED) o None."""
        ...

    @abstractmethod
    async def save_run(self, run: DiscoveryRun) -> DiscoveryRun:
        """Persiste el estado final de una corrida."""
        ...

    @abstractmethod
    async def list_runs(
        self, organization_id: UUID, *, limit: int = 20, offset: int = 0
    ) -> list[DiscoveryRun]:
        """Corridas del tenant, más recientes primero."""
        ...
