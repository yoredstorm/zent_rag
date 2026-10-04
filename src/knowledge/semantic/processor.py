# =============================================================================
# SemanticWindowProcessor — comprensión por ventana con checkpoints (§49-53)
# =============================================================================
# Por cada ventana del plan:
#   1. reconstruct del texto de la ventana (bloques + char offsets);
#   2. fingerprint de contenido+versión: ventana sin cambios = SKIP;
#   3. comprensión determinista (extract) + LLM opcional (quote verificado);
#   4. SemanticState con carry-forward selectivo (selector);
#   5. persistencia del resultado + estado + status de la ventana.
#
# Una ventana fallida NO invalida la fuente: se marca FAILED y se sigue.
# Reprocesar solo re-hace las ventanas stale (checkpoint por ventana).
# =============================================================================
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from hashlib import sha256

from src.core.domain.knowledge_v2 import StructuredBlock, StructuredDocument
from src.knowledge.compiler.model import normalize_term
from src.knowledge.structure.base import token_count

from .contracts import (
    WINDOW_UNDERSTANDING_VERSION,
    SemanticState,
    SemanticWindowPlan,
    SemanticWindowResult,
    SemanticWindowSpec,
    WindowItem,
)
from .extract import extract_window_items
from .llm import WindowUnderstandingProvider
from .planner import indexable_blocks
from .selector import SemanticStateSelector
from .state import StateCaps, build_state
from .threads import (
    SemanticThread,
    advance_threads,
    cap_open_threads,
    rollback_threads,
)


def _setting(name: str, default):
    try:
        from src.core.config import get_settings

        settings = get_settings()
        return getattr(settings, name, default)
    except Exception:  # noqa: BLE001
        return default


@dataclass(frozen=True, kw_only=True)
class WindowProcessingOutcome:
    windows_total: int = 0
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    items_total: int = 0
    unresolved_total: int = 0
    llm_calls: int = 0
    llm_tokens: int = 0
    threads_opened: int = 0
    threads_resolved: int = 0
    threads_partial: int = 0
    threads_ambiguous: int = 0
    threads_open: int = 0
    state: SemanticState | None = None
    errors: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return self.windows_total > 0 and self.failed == 0 and (
            self.processed + self.skipped == self.windows_total
        )

    def to_dict(self) -> dict:
        return {
            "windows_total": self.windows_total,
            "processed": self.processed,
            "skipped": self.skipped,
            "failed": self.failed,
            "items_total": self.items_total,
            "unresolved_total": self.unresolved_total,
            "llm_calls": self.llm_calls,
            "llm_tokens": self.llm_tokens,
            "threads_opened": self.threads_opened,
            "threads_resolved": self.threads_resolved,
            "threads_partial": self.threads_partial,
            "threads_ambiguous": self.threads_ambiguous,
            "threads_open": self.threads_open,
            "complete": self.complete,
            "errors": list(self.errors[:10]),
        }


class SemanticWindowProcessor:
    """Procesa ventanas semánticas con checkpoint e idempotencia."""

    def __init__(
        self,
        store: object,
        *,
        selector: SemanticStateSelector | None = None,
        caps: StateCaps | None = None,
        llm_provider: WindowUnderstandingProvider | None = None,
        llm_max_calls: int | None = None,
        max_items: int | None = None,
    ) -> None:
        self._store = store
        self._selector = selector or SemanticStateSelector()
        self._caps = caps or StateCaps()
        self._llm = llm_provider
        self._llm_max_calls = (
            max(0, int(llm_max_calls))
            if llm_max_calls is not None
            else max(0, int(_setting("KNOWLEDGE_SEMANTIC_WINDOW_LLM_MAX_CALLS", 24) or 0))
        )
        self._max_items = (
            max(1, int(max_items))
            if max_items is not None
            else max(1, int(_setting("KNOWLEDGE_SEMANTIC_WINDOW_MAX_ITEMS", 400) or 400))
        )
        self._max_open_threads = max(
            0, int(_setting("KNOWLEDGE_SEMANTIC_THREAD_MAX_OPEN", 512) or 0)
        )

    @property
    def llm_enabled(self) -> bool:
        return self._llm is not None and self._llm_max_calls > 0

    async def process(
        self,
        document: StructuredDocument,
        plan: SemanticWindowPlan,
        *,
        enrichment=None,
        compiled=None,
        reset: bool = False,
    ) -> WindowProcessingOutcome:
        if plan.window_count <= 0:
            return WindowProcessingOutcome(windows_total=0, state=None)
        if reset:
            await self._safe_delete_artifacts(document)
        blocks = indexable_blocks(document)
        processed = skipped = failed = 0
        items_total = 0
        llm_calls = 0
        llm_tokens = 0
        threads_opened = threads_resolved = threads_partial = threads_ambiguous = 0
        errors: list[str] = []
        current_state: SemanticState | None = None
        threads_enabled = self._threads_enabled()
        threads_map: dict[str, SemanticThread] = (
            await self._safe_list_threads(document) if threads_enabled else {}
        )

        for spec in plan.windows:
            window_blocks = _window_blocks(blocks, spec)
            if not window_blocks:
                skipped += 1
                continue
            text = "\n\n".join(block.text for block in window_blocks if block.text)
            tokens = sum(max(1, token_count(block.text)) for block in window_blocks)
            fingerprint = _window_fingerprint(text)
            previous_state = current_state
            if previous_state is None and spec.window_index > 0:
                previous_state = await self._safe_get_state(
                    document, spec.window_index - 1
                )
            first = window_blocks[0]
            section_id = (
                str(first.metadata.get("parent_section_id"))
                if first.metadata.get("parent_section_id")
                else None
            )
            next_block = (
                blocks[spec.unit_end + 1]
                if 0 <= spec.unit_end + 1 < len(blocks)
                else None
            )
            section_continues = bool(
                next_block is not None
                and section_id is not None
                and str(next_block.metadata.get("parent_section_id") or "") == section_id
            )
            slice_ = self._selector.select(
                previous_state,
                window_text=text,
                window_index=spec.window_index,
                section_id=section_id,
            )
            existing = await self._safe_get_result(document, spec.window_index)
            if (
                existing is not None
                and existing.get("fingerprint") == fingerprint
                and existing.get("carry_fingerprint") == slice_.fingerprint
                and existing.get("status") in ("complete", "partial")
            ):
                skipped += 1
                stored = await self._safe_get_state(document, spec.window_index)
                if stored is not None:
                    current_state = stored
                items_total += int(existing.get("item_count") or 0)
                continue

            # La ventana se va a reprocesar: deshacer sus efectos en threads
            # (los abiertos en esta ventana se re-derivan; los resueltos aquí
            # vuelven a OPEN y se re-evalúan con la ventana actual).
            if threads_enabled:
                threads_map = rollback_threads(
                    threads_map, from_window=spec.window_index
                )

            try:
                result = await self._process_window(
                    document,
                    spec,
                    window_blocks=window_blocks,
                    text=text,
                    tokens=tokens,
                    fingerprint=fingerprint,
                    slice_fingerprint=slice_.fingerprint,
                    enrichment=enrichment,
                    compiled=compiled,
                    section_continues=section_continues,
                )
                state = build_state(
                    organization_id=document.organization_id,
                    source_id=document.source_id,
                    workspace_id=document.workspace_id,
                    document_id=document.id,
                    window_index=spec.window_index,
                    result=result,
                    previous=previous_state,
                    slice_=slice_,
                    caps=self._caps,
                    window_section_id=section_id,
                )
                await self._safe_save_result(document, result)
                await self._safe_save_state(document, state)
                await self._safe_set_window_status(
                    document, spec.window_index, result.status
                )
                if threads_enabled:
                    threads_map, touched, thread_stats = advance_threads(
                        threads_map, result, window_section_id=section_id
                    )
                    threads_map, capped = cap_open_threads(
                        threads_map, max_open=self._max_open_threads
                    )
                    await self._safe_save_threads(
                        document, [*touched, *capped]
                    )
                    threads_opened += thread_stats.opened
                    threads_resolved += thread_stats.resolved
                    threads_partial += thread_stats.partial
                    threads_ambiguous += thread_stats.ambiguous
                processed += 1
                items_total += len(result.items)
                llm_calls += int(result.quality.get("llm_calls") or 0)
                llm_tokens += int(result.quality.get("llm_tokens") or 0)
                _observe_window(
                    llm_tokens=int(result.quality.get("llm_tokens") or 0),
                )
                current_state = state
            except Exception as exc:  # noqa: BLE001 — una ventana no tumba la fuente
                failed += 1
                message = f"window {spec.window_index}: {type(exc).__name__}: {exc}"
                errors.append(message[:300])
                await self._safe_save_failure(document, spec, fingerprint, message)
                await self._safe_set_window_status(
                    document, spec.window_index, "failed"
                )

        unresolved_total = 0
        if current_state is not None:
            unresolved_total = len(current_state.unresolved_references) + len(
                current_state.open_continuations
            )
        return WindowProcessingOutcome(
            windows_total=plan.window_count,
            processed=processed,
            skipped=skipped,
            failed=failed,
            items_total=items_total,
            unresolved_total=unresolved_total,
            llm_calls=llm_calls,
            llm_tokens=llm_tokens,
            threads_opened=threads_opened,
            threads_resolved=threads_resolved,
            threads_partial=threads_partial,
            threads_ambiguous=threads_ambiguous,
            threads_open=sum(1 for item in threads_map.values() if item.is_open),
            state=current_state,
            errors=tuple(errors),
        )

    # ------------------------------------------------------------------
    async def _process_window(
        self,
        document: StructuredDocument,
        spec: SemanticWindowSpec,
        *,
        window_blocks: list[StructuredBlock],
        text: str,
        tokens: int,
        fingerprint: str,
        slice_fingerprint: str,
        enrichment,
        compiled,
        section_continues: bool = False,
    ) -> SemanticWindowResult:
        items: list[WindowItem] = extract_window_items(
            document=document,
            window_blocks=window_blocks,
            window_index=spec.window_index,
            enrichment=enrichment,
            compiled=compiled,
            max_items=self._max_items,
            section_continues=section_continues,
        )
        llm_calls = 0
        llm_tokens = 0
        llm_items = 0
        error: str | None = None
        if self.llm_enabled and text.strip():
            llm_result = await self._llm.extract(text=text)  # type: ignore[union-attr]
            llm_calls = int(llm_result.calls)
            llm_tokens = int(llm_result.prompt_tokens + llm_result.completion_tokens)
            if llm_result.error:
                error = f"llm: {llm_result.error}"
            llm_items = len(llm_result.items)
            items.extend(
                self._llm_item(entry, window_blocks, spec.window_index)
                for entry in llm_result.items
            )
        status = "partial" if error else "complete"
        return SemanticWindowResult(
            window_index=spec.window_index,
            organization_id=document.organization_id,
            source_id=document.source_id,
            workspace_id=document.workspace_id,
            document_id=document.id,
            status=status,
            items=tuple(items),
            block_ids=tuple(str(block.id) for block in window_blocks),
            char_start=spec.char_start,
            char_end=spec.char_end,
            tokens_estimated=tokens,
            fingerprint=fingerprint,
            carry_fingerprint=slice_fingerprint,
            provenance={
                "window_reason": spec.reason,
                "target_tokens": spec.target_tokens,
                "hard_limit_tokens": spec.hard_limit_tokens,
                "block_range": [spec.unit_start, spec.unit_end],
                "selector_version": self._selector.version,
            },
            quality={
                "items": len(items),
                "deterministic_items": len(items) - llm_items,
                "llm_items": llm_items,
                "llm_calls": llm_calls,
                "llm_tokens": llm_tokens,
            },
            error=error,
        )

    def _llm_item(
        self,
        entry: dict,
        window_blocks: list[StructuredBlock],
        window_index: int,
    ) -> WindowItem:
        quote = str(entry.get("quote") or "")
        block_id = None
        for block in window_blocks:
            if quote and quote in " ".join((block.text or "").split()):
                block_id = str(block.id)
                break
        return WindowItem(
            kind=str(entry.get("kind") or "concept"),
            key=f"llm:{normalize_term(str(entry.get('label') or ''))}",
            label=str(entry.get("label") or ""),
            text=str(entry.get("text") or ""),
            confidence=float(entry.get("confidence") or 0.5),
            method="llm",
            block_ids=(block_id,) if block_id else (),
            attributes={
                "quote": quote,
                "source": "llm",
                "window_index": window_index,
            },
        )

    # ------------------------------------------------------------------
    def _threads_enabled(self) -> bool:
        try:
            return bool(
                _setting("KNOWLEDGE_SEMANTIC_THREADS_ENABLED", True)
            )
        except Exception:  # noqa: BLE001
            return True

    async def _safe_list_threads(self, document) -> dict[str, SemanticThread]:
        try:
            threads = await self._store.list_threads(
                document.organization_id, document_id=document.id
            )
            return {thread.thread_key: thread for thread in threads}
        except Exception:  # noqa: BLE001 — sin threads persistidos, arranca vacío
            return {}

    async def _safe_save_threads(
        self, document, threads: list[SemanticThread]
    ) -> None:
        if not threads:
            return
        try:
            await self._store.save_threads(
                document.organization_id,
                workspace_id=document.workspace_id,
                source_id=document.source_id,
                document_id=document.id,
                threads=threads,
            )
        except Exception as exc:  # noqa: BLE001 — el checkpoint es best-effort
            _log_warning("semantic threads save failed", document, exc)

    async def _safe_get_result(self, document, window_index: int):
        try:
            return await self._store.get_window_result(
                document.organization_id,
                document_id=document.id,
                window_index=window_index,
            )
        except Exception:  # noqa: BLE001
            return None

    async def _safe_get_state(self, document, window_index: int):
        try:
            return await self._store.get_state(
                document.organization_id,
                document_id=document.id,
                window_index=window_index,
            )
        except Exception:  # noqa: BLE001
            return None

    async def _safe_save_result(
        self, document, result: SemanticWindowResult
    ) -> None:
        try:
            await self._store.save_window_result(
                document.organization_id,
                workspace_id=document.workspace_id,
                source_id=document.source_id,
                document_id=document.id,
                result=result,
            )
        except Exception as exc:  # noqa: BLE001 — el checkpoint es best-effort
            _log_warning("window result save failed", document, exc)

    async def _safe_save_state(self, document, state: SemanticState) -> None:
        try:
            await self._store.save_state(
                document.organization_id,
                workspace_id=document.workspace_id,
                source_id=document.source_id,
                document_id=document.id,
                state=state,
            )
        except Exception as exc:  # noqa: BLE001
            _log_warning("window state save failed", document, exc)

    async def _safe_save_failure(
        self,
        document,
        spec: SemanticWindowSpec,
        fingerprint: str,
        message: str,
    ) -> None:
        try:
            await self._store.save_window_result(
                document.organization_id,
                workspace_id=document.workspace_id,
                source_id=document.source_id,
                document_id=document.id,
                result=SemanticWindowResult(
                    window_index=spec.window_index,
                    organization_id=document.organization_id,
                    source_id=document.source_id,
                    workspace_id=document.workspace_id,
                    document_id=document.id,
                    status="failed",
                    fingerprint=fingerprint,
                    error=message[:1000],
                ),
            )
        except Exception as exc:  # noqa: BLE001
            _log_warning("window failure save failed", document, exc)

    async def _safe_set_window_status(self, document, window_index: int, status: str) -> None:
        try:
            await self._store.update_window_status(
                document.organization_id,
                document_id=document.id,
                window_index=window_index,
                status=status,
            )
        except Exception as exc:  # noqa: BLE001
            _log_warning("window status update failed", document, exc)

    async def _safe_delete_artifacts(self, document) -> None:
        try:
            await self._store.delete_window_artifacts(
                document.organization_id, document_id=document.id
            )
        except Exception as exc:  # noqa: BLE001
            _log_warning("window artifact reset failed", document, exc)


def _window_blocks(
    blocks: list[StructuredBlock], spec: SemanticWindowSpec
) -> list[StructuredBlock]:
    window = list(blocks[spec.unit_start : spec.unit_end + 1])
    if not window:
        return []
    if spec.first_block_id == spec.last_block_id and (
        spec.char_start is not None or spec.char_end is not None
    ):
        text = window[0].text or ""
        start = int(spec.char_start or 0)
        end = int(spec.char_end) if spec.char_end is not None else len(text)
        trimmed = text[max(0, start) : max(0, end)]
        return [dataclasses.replace(window[0], text=trimmed)]
    return window


def _window_fingerprint(text: str) -> str:
    material = f"{WINDOW_UNDERSTANDING_VERSION}|{' '.join((text or '').split())}"
    return sha256(material.encode("utf-8")).hexdigest()


def _log_warning(message: str, document, exc: Exception) -> None:
    try:
        from src.infrastructure.observability.logging_config import get_logger

        get_logger(__name__).warning(
            message,
            document_id=str(getattr(document, "id", "")),
            error=str(exc)[:250],
        )
    except Exception:  # noqa: BLE001
        return


def _observe_window(*, llm_tokens: int) -> None:
    """Métricas best-effort: jamás frenan la comprensión."""
    try:
        from src.infrastructure.observability.metrics import (
            knowledge_ingest_tokens_total,
        )

        if llm_tokens > 0:
            knowledge_ingest_tokens_total.labels(kind="semantic_window").inc(
                int(llm_tokens)
            )
    except Exception:  # noqa: BLE001
        return


__all__ = ["SemanticWindowProcessor", "WindowProcessingOutcome"]
