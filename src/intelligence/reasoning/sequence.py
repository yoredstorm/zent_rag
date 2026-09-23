# =============================================================================
# Timeline Builder (§22) + State Transition Analyzer (§23/§24)
# =============================================================================
# El número de secuencia NO es la cronología. Se conservan tres órdenes y se
# registra el criterio usado para ordenar; nunca se reordena en silencio.
#
# La cadena de transiciones se representa como eslabones con evento y regla,
# no como un texto libre.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass

from src.core.domain.reasoning import (
    UNKNOWN_STATE,
    Fact,
    ScenarioEvent,
    StateTransition,
    StateTransitionSet,
    StructuredScenario,
    Timeline,
    TimelineEvent,
    TimelineOrder,
    TransitionLink,
    TransitionStatus,
)

_SEQUENCE_DIGITS = "0123456789"


def _numeric(value: str) -> int | None:
    text = (value or "").strip()
    if not text or not all(char in _SEQUENCE_DIGITS for char in text):
        return None
    try:
        return int(text)
    except ValueError:
        return None


@dataclass
class TimelineBuilder:
    """Construye el timeline conservando los tres órdenes."""

    def build(self, scenario: StructuredScenario) -> Timeline:
        events = list(scenario.events)
        original = tuple(event.index for event in events)
        if not events:
            return Timeline(complete=False)

        with_effective = [event for event in events if event.effective_date is not None]
        unknown_dates = tuple(
            event.index for event in events if event.effective_date is None
        )
        if with_effective:
            effective = tuple(
                event.index
                for event in sorted(
                    events,
                    key=lambda item: (
                        item.effective_date is None,
                        item.effective_date,
                        item.index,
                    ),
                )
            )
            criterion = "effective_date"
        else:
            # Sin fechas: el orden de entrada es el único criterio disponible.
            effective = original
            criterion = "input_order_no_dates"

        logical, logical_criterion = self._logical_order(events, effective)

        timeline_events = tuple(
            TimelineEvent(
                scenario_index=index,
                position=position,
                order_used=TimelineOrder.LOGICAL if logical_criterion else TimelineOrder.EFFECTIVE,
                criterion=logical_criterion or criterion,
                event=next((item for item in events if item.index == index), None),
            )
            for position, index in enumerate(logical)
        )
        return Timeline(
            original_order=original,
            effective_order=effective,
            logical_order=logical,
            events=timeline_events,
            criteria={
                "effective": criterion,
                "logical": logical_criterion or "not_proven",
                # Sin fechas la secuencia es válida como orden de entrada, pero
                # la cronología NO queda probada: se declara, no se asume.
                "chronology_proven": bool(with_effective),
            },
            complete=bool(events),
            unknown_dates=unknown_dates,
        )

    @staticmethod
    def _logical_order(
        events: list[ScenarioEvent], effective: tuple[int, ...]
    ) -> tuple[tuple[int, ...], str]:
        """Orden lógico si puede probarse con la numeración de secuencia.

        Solo se declara probado cuando la numeración de secuencia es
        consistente con el orden efectivo. Si no, se devuelve el efectivo.
        """
        numbers = {
            event.index: _numeric(event.sequence)
            for event in events
            if event.sequence
        }
        ordered_numbers = [numbers.get(index) for index in effective]
        known = [value for value in ordered_numbers if value is not None]
        if len(known) < 2 or len(known) != len(ordered_numbers):
            return effective, ""
        if all(known[i] <= known[i + 1] for i in range(len(known) - 1)):
            return effective, "sequence_monotonic_in_effective_order"
        # La numeración contradice el orden efectivo: no se inventa el lógico.
        return effective, ""


@dataclass
class StateTransitionAnalyzer:
    """Deriva transiciones a partir de eventos, reglas y hechos."""

    def analyze(
        self,
        *,
        scenario: StructuredScenario,
        timeline: Timeline | None,
        rules: list[Fact],
        facts: list[Fact] | None = None,
    ) -> StateTransitionSet:
        events = list(scenario.events)
        if timeline and timeline.logical_order:
            order = list(timeline.logical_order)
        else:
            order = [event.index for event in events]
        by_index = {event.index: event for event in events}
        ordered_events = [by_index[index] for index in order if index in by_index]

        rule_refs = tuple(
            str(rule.id) for rule in rules if rule.usable_as_premise
        )
        transitions: list[StateTransition] = []
        links: list[TransitionLink] = []
        gaps: list[str] = []
        previous_value: str | None = None
        subject = ""

        for event in ordered_events:
            value = (event.sequence or "").strip()
            if not value:
                continue
            if not subject:
                subject = (event.entity_identifiers or ("unknown",))[0]
            before = previous_value or UNKNOWN_STATE
            status = TransitionStatus.CONFIRMED if rule_refs else TransitionStatus.UNRESOLVED
            transitions.append(
                StateTransition(
                    subject=subject,
                    before=before,
                    event_ref=event.raw_ref,
                    after=value,
                    rule_refs=rule_refs,
                    evidence_refs=event.raw_ref and (event.raw_ref,) or (),
                    status=status,
                    confidence=0.8 if rule_refs else 0.4,
                )
            )
            if previous_value is not None:
                links.append(
                    TransitionLink(
                        from_value=previous_value,
                        to_value=value,
                        event_ref=event.raw_ref,
                        rule_refs=rule_refs,
                        confidence=0.8 if rule_refs else 0.4,
                        status=status,
                    )
                )
            previous_value = value

        if not rule_refs:
            gaps.append("no_rule_supports_transitions")
        if not ordered_events:
            gaps.append("no_events")

        resolved = bool(transitions) and all(
            item.status in (TransitionStatus.CONFIRMED, TransitionStatus.SUPPORTED)
            for item in transitions
        )
        return StateTransitionSet(
            subject=subject,
            transitions=tuple(transitions),
            chain=tuple(links),
            gaps=tuple(gaps),
            resolved=resolved,
        )


def chain_values(transitions: StateTransitionSet) -> list[str]:
    """Valores de la cadena para comparaciones (5, 6, 7, 10, ...)."""
    if not transitions.chain:
        return [item.after for item in transitions.transitions]
    return [transitions.chain[0].from_value] + [
        link.to_value for link in transitions.chain
    ]


def find_sequence_gaps(transitions: StateTransitionSet) -> list[tuple[str, str]]:
    """Pares consecutivos donde la numeración no es contigua.

    No afirma que falte un cierre: sólo informa dónde hay un salto, que es
    material para las hipótesis.
    """
    values = chain_values(transitions)
    gaps: list[tuple[str, str]] = []
    for previous, current in zip(values, values[1:]):
        before, after = _numeric(previous), _numeric(current)
        if before is None or after is None:
            continue
        if after - before > 1:
            gaps.append((previous, current))
    return gaps


def sequence_was_renumbered(transitions: StateTransitionSet, *, rules: list[Fact]) -> bool:
    """¿Las reglas indican que la numeración se reasignó para abrir espacio?"""
    for rule in rules:
        statement = (rule.statement or "").lower()
        if not rule.usable_as_premise:
            continue
        if "renumber" in statement or "renumer" in statement:
            return True
    return False


__all__ = [
    "StateTransitionAnalyzer",
    "TimelineBuilder",
    "chain_values",
    "find_sequence_gaps",
    "sequence_was_renumbered",
]
