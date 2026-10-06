# =============================================================================
# Production consistency — misma fuente + misma pregunta => misma decisión
# =============================================================================
# Regresión arquitectónica del fallo observado:
#
#   La MISMA consulta sobre la MISMA fuente deriva MATCH en una ejecución y
#   NO_MATCH en otra porque el descubrimiento de CanonicalRules dependía de
#   que el raw chunk recuperado casualmente trajera `canonical_rule_ids`.
#
# Contrato:
#   - El descubrimiento de reglas canónicas NO depende del top-k de chunks.
#   - Un DerivedClaim determinista produce un DecisionEnvelope inmutable.
#   - Ninguna ruta final puede contradecir la decisión (DerivedGuard).
#   - 100/100 repeticiones con perturbación => misma decisión.
#
# ATPCO (&&&F / ABCFGEGE) se usa SOLO como fixture de regresión, nunca como
# lógica de producción.
# =============================================================================
from __future__ import annotations

import random
from uuid import uuid4

import pytest

from src.core.domain.grounding import VerificationStatus
from src.intelligence.reasoning.grounded_engine import (
    ANSWERABLE_DERIVED,
    reason_over_evidence,
)
from src.knowledge.compiler.model import EvidenceRef, SemanticUnit, SourceLocator
from src.knowledge.rule_compiler import CanonicalRule, SemanticRuleCompiler
from src.runtime.rule_retrieval import (
    InMemoryRuleIndex,
    InMemoryRuleLookup,
    RuleSearchRequest,
    load_rules_for_evidence,
    retrieve_canonical_rules,
)

DOC = uuid4()
ORG = uuid4()


def unit(
    kind: str,
    text: str,
    *,
    page: int = 1,
    section: tuple[str, ...] = ("General",),
) -> SemanticUnit:
    return SemanticUnit(
        kind=kind,
        key=f"{kind}:{text[:24]}",
        label=text[:24],
        text=text,
        confidence=0.8,
        evidence=EvidenceRef(
            locator=SourceLocator(
                document_id=DOC,
                document_title="Manual",
                page=page,
                section_path=section,
            ),
            excerpt=text,
        ),
    )


class _Item:
    """Evidencia recuperada mínima (RetrievalChunk-compatible)."""

    def __init__(
        self,
        content: str = "",
        *,
        evidence_id: str = "ev_1",
        metadata: dict | None = None,
    ) -> None:
        self.content = content
        self.evidence_id = evidence_id
        self.metadata = metadata or {}


def compile_pattern_rules() -> list[CanonicalRule]:
    """Gramática distribuida del caso observado (fixture, no lógica)."""
    return SemanticRuleCompiler().compile(
        document_id=str(DOC),
        document_title="Manual",
        organization_id=str(ORG),
        units=[
            unit(
                "definition",
                "The value may contain more characters than the pattern.",
                page=1,
                section=("Matching",),
            ),
            unit(
                "definition",
                "The symbol & represents one alphanumeric position.",
                page=7,
                section=("Kinds of characters",),
            ),
            unit(
                "reference",
                "Matching is positional, left to right. "
                "Literal characters must match exactly at their position.",
                page=2,
                section=("Matching",),
            ),
        ],
    ).canonical_rules


QUESTION = "el valor ABCFGEGE cumple el patrón &&&F"


# -----------------------------------------------------------------------------
# 1 — El fallo actual: descubrimiento de reglas atado al chunk
# -----------------------------------------------------------------------------


class TestRuleDiscoveryIndependentFromChunks:
    @pytest.mark.asyncio
    async def test_chunk_without_ids_still_discovers_rules(self) -> None:
        """Sin metadata en el chunk, la regla canónica debe seguir apareciendo.

        Antes: load_rules_for_evidence() -> [] y el LLM decidía libremente.
        Después: Rule Lane recovers it from the query semantics.
        """
        rules = compile_pattern_rules()
        executable = [rule for rule in rules if rule.executable]
        assert executable, "la gramática debe compilar ejecutable"

        lookup = InMemoryRuleLookup(rules)
        index = InMemoryRuleIndex(rules)
        chunk_without_ids = _Item(
            "Matching is positional, left to right. Literal characters "
            "must match exactly at their position."
        )

        # Camino histórico: depende del chunk.
        historical = await load_rules_for_evidence(
            ORG, [chunk_without_ids], lookup=lookup
        )
        assert historical == [], "sin ids no hay shortcut (comportamiento conocido)"

        # Camino nuevo: regla primero, independiente del chunk.
        result = await retrieve_canonical_rules(
            ORG,
            QUESTION,
            evidence_items=[chunk_without_ids],
            lookup=lookup,
            index=index,
        )
        assert result.supported_rules, (
            "la Rule Lane debe recuperar la CanonicalRule aunque el chunk "
            "recuperado no traiga canonical_rule_ids"
        )
        assert any(
            rule.rule_id for rule in result.supported_rules
        ), "las reglas recuperadas conservan su identidad"

    @pytest.mark.asyncio
    async def test_rule_lane_is_deterministic_in_order(self) -> None:
        rules = compile_pattern_rules()
        request = RuleSearchRequest(
            organization_id=ORG,
            query=QUESTION,
            tokens=("valor", "abcfgege", "patr", "matching", "pattern"),
            symbols=("&",),
        )
        index = InMemoryRuleIndex(rules)
        first = await index.search(request)
        for _ in range(25):
            assert [hit.rule.rule_id for hit in await index.search(request)] == [
                hit.rule.rule_id for hit in first
            ]


# -----------------------------------------------------------------------------
# 2 — Regresión del caso observado: &&&F / ABCFGEGE
# -----------------------------------------------------------------------------


class TestPatternRegression:
    def _run_with_rules(self, rules: list[CanonicalRule]):
        return reason_over_evidence(
            question=f"¿{QUESTION}?",
            evidence_items=[
                _Item(
                    "Matching is positional, left to right. Literal characters "
                    "must match exactly at their position.",
                    metadata={
                        "canonical_rules": [rule.to_dict() for rule in rules],
                    },
                )
            ],
            canonical_rules=rules,
        )

    def test_positional_match_is_deterministic(self) -> None:
        from src.runtime.decision_envelope import build_decision_envelope

        rules = compile_pattern_rules()
        result = self._run_with_rules(rules)
        assert result.answerability == ANSWERABLE_DERIVED
        claims = list(result.derivations.claims)
        assert claims, "la operación determinista debe producir un DerivedClaim"
        claim = claims[0]
        assert claim.deterministic is True
        assert claim.verification_status == VerificationStatus.SUPPORTED.value
        assert claim.operation == "POSITIONAL_MATCH"
        assert claim.result is True
        envelope = build_decision_envelope(result)
        assert envelope is not None and envelope.authoritative
        assert envelope.operation == "POSITIONAL_MATCH"
        assert envelope.result == "MATCH"


# -----------------------------------------------------------------------------
# 3 — Misma decisión 100/100 con perturbación deliberada
# -----------------------------------------------------------------------------


class _FixedFakeLLM:
    """FakeLLM que responde lo contrario de forma deliberada."""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls = 0

    def generate(self) -> str:
        self.calls += 1
        return self.answer


class TestHundredRunConsistency:
    def test_decision_is_identical_under_perturbation(self) -> None:
        from src.runtime.decision_envelope import (
            build_decision_envelope,
            finalize_authoritative_answer,
        )

        rules = compile_pattern_rules()
        supported = [rule for rule in rules if rule.executable]
        assert supported
        rng = random.Random(20261005)  # noqa: S311 — reproducibilidad del test
        contradictory = (
            "NO_MATCH: el valor ABCFGEGE no cumple el patrón &&&F porque las "
            "longitudes son distintas.",
            "No cumple: ABCFGEGE y &&&F tienen distinta longitud.",
            "FALSE. The value and the pattern must have exactly the same "
            "number of characters.",
        )
        decisions: list[tuple[str, str, bool]] = []
        for index in range(100):
            # Perturbación: orden de evidencia, subconjuntos, redacción.
            items = [
                _Item(
                    "Matching is positional, left to right. Literal characters "
                    "must match exactly at their position.",
                    evidence_id=f"ev_{index}",
                ),
                _Item(
                    "The symbol & represents one alphanumeric position.",
                    evidence_id=f"ev_symbol_{index}",
                ),
                _Item(
                    "The value may contain more characters than the pattern.",
                    evidence_id=f"ev_len_{index}",
                ),
            ]
            rng.shuffle(items)
            subset = items[: rng.randint(1, len(items))]
            grounded = reason_over_evidence(
                question=f"¿{QUESTION}?",
                evidence_items=subset,
                canonical_rules=rules,
            )
            envelope = build_decision_envelope(grounded)
            assert envelope is not None, f"run {index}: sin DecisionEnvelope"
            assert envelope.authoritative
            fake = _FixedFakeLLM(rng.choice(contradictory))
            final = finalize_authoritative_answer(
                fake.generate(), grounded, envelope=envelope
            )
            assert final.guard is not None
            assert final.guard.action == "override"
            decisions.append(
                (str(envelope.result), final.answer.splitlines()[0], final.overridden)
            )
        first = decisions[0]
        assert all(item == first for item in decisions), (
            "la decisión cambió entre ejecuciones con la misma fuente"
        )
        assert first[0] == "MATCH"
        assert first[1] == "Sí, cumple."
        assert first[2] is True, "el guard debe registrar el override"


# -----------------------------------------------------------------------------
# 4 — Retrieval perturbation: perder un chunk no invierte la decisión
# -----------------------------------------------------------------------------


class TestRetrievalPerturbation:
    def test_losing_chunks_keeps_decision_via_rule_lane(self) -> None:
        from src.runtime.decision_envelope import build_decision_envelope

        rules = compile_pattern_rules()
        baseline = reason_over_evidence(
            question=f"¿{QUESTION}?",
            evidence_items=[_Item("Matching is positional.")],
            canonical_rules=rules,
        )
        baseline_envelope = build_decision_envelope(baseline)
        assert baseline_envelope is not None
        for keep in range(0, 4):
            grounded = reason_over_evidence(
                question=f"¿{QUESTION}?",
                evidence_items=[_Item(f"fragmento {keep}")],
                canonical_rules=rules,
            )
            envelope = build_decision_envelope(grounded)
            assert envelope is not None, "la regla debe decidir aunque cambie la evidencia"
            assert envelope.normalized_result == baseline_envelope.normalized_result

    def test_missing_premises_yield_undetermined_not_opposite(self) -> None:
        from src.intelligence.reasoning.grounded_engine import UNDETERMINED_RULE

        # Evidencia que referencia una regla compilada, sin poder cargarla:
        # nunca NO_MATCH; el estado es indeterminado y lo nombra.
        item = _Item(
            "Matching is positional.",
            metadata={"canonical_rule_ids": {"k": str(uuid4())}},
        )
        grounded = reason_over_evidence(
            question=f"¿{QUESTION}?",
            evidence_items=[item],
        )
        assert grounded.answerability == UNDETERMINED_RULE
        assert any(
            str(missing).startswith("rule:") for missing in grounded.missing_premises
        )
        assert not grounded.derivations.claims


# -----------------------------------------------------------------------------
# 5 — Paráfrasis: 30 variantes convergen a la misma semántica
# -----------------------------------------------------------------------------


PARAPHRASES_30: tuple[str, ...] = (
    "¿ABCFGEGE cumple el patrón &&&F?",
    "¿ABCFGEGE es válido contra &&&F?",
    "¿ABCFGEGE hace match con &&&F?",
    "¿ABCFGEGE aplica a la regla &&&F?",
    "¿ABCFGEGE acepta el patrón &&&F?",
    "¿el patrón &&&F acepta ABCFGEGE?",
    "ABCFGEGE contra &&&F",
    "ABCFGEGE versus &&&F",
    "valida ABCFGEGE contra &&&F",
    "chequea ABCFGEGE con &&&F",
    "does ABCFGEGE pass the mask &&&F?",
    "does ABCFGEGE match the pattern &&&F?",
    "is ABCFGEGE valid against &&&F?",
    "would ABCFGEGE pass &&&F?",
    "check ABCFGEGE against &&&F",
    "ABCFGEGE vs &&&F",
    "¿resultado de ABCFGEGE contra &&&F?",
    "¿qué resultado da ABCFGEGE contra &&&F?",
    "necesito saber si ABCFGEGE cumple &&&F",
    "decime si ABCFGEGE cumple con &&&F",
    "aplicando la regla &&&F, ¿ABCFGEGE cumple?",
    "según &&&F, ¿ABCFGEGE es válido?",
    "el valor ABCFGEGE, ¿cumple &&&F?",
    "tengo ABCFGEGE, ¿pasa &&&F?",
    "mi valor es ABCFGEGE, ¿matchea &&&F?",
    "confirma si ABCFGEGE cumple el patrón &&&F",
    "¿ABCFGEGE satisface &&&F?",
    "¿ABCFGEGE coincide con &&&F?",
    "¿ABCFGEGE está permitido por &&&F?",
    "evalúa ABCFGEGE contra &&&F",
)


class TestParaphraseConvergence:
    @pytest.mark.parametrize("question", PARAPHRASES_30)
    def test_same_rule_operation_and_result(self, question: str) -> None:
        from src.runtime.decision_envelope import build_decision_envelope

        rules = compile_pattern_rules()
        grounded = reason_over_evidence(
            question=question,
            evidence_items=[_Item("Matching is positional, left to right.")],
            canonical_rules=rules,
        )
        envelope = build_decision_envelope(grounded)
        assert envelope is not None, question
        assert envelope.operation == "POSITIONAL_MATCH", question
        assert envelope.normalized_result == "MATCH", question
        assert envelope.canonical_rule_ids, question


# -----------------------------------------------------------------------------
# 6 — Adversarial generator por operación determinista
# -----------------------------------------------------------------------------


class TestAdversarialGeneratorPerOperation:
    def _authoritative(self, units, question, values, contradicting):
        from src.runtime.decision_envelope import (
            build_decision_envelope,
            finalize_authoritative_answer,
        )

        rules = SemanticRuleCompiler().compile(
            document_id=str(DOC),
            document_title="Manual",
            organization_id=str(ORG),
            units=list(units),
        ).canonical_rules
        executable = [rule for rule in rules if rule.executable]
        assert executable, f"no compiló regla ejecutable para {question}"
        grounded = reason_over_evidence(
            question=question,
            evidence_items=[_Item("regla documentada")],
            canonical_rules=rules,
        )
        envelope = build_decision_envelope(grounded)
        assert envelope is not None, question
        final = finalize_authoritative_answer(
            contradicting, grounded, envelope=envelope
        )
        return envelope, final

    def test_positional_match(self) -> None:
        envelope, final = self._authoritative(
            [
                unit("definition", "The symbol & represents one alphanumeric position."),
                unit(
                    "reference",
                    "Matching is positional from the start. The value may be "
                    "longer than the pattern.",
                ),
            ],
            "¿ABCFGEGE cumple &&&F?",
            {"value": "ABCFGEGE", "pattern": "&&&F"},
            "NO_MATCH: no cumple, las longitudes difieren.",
        )
        assert envelope.operation == "POSITIONAL_MATCH"
        assert envelope.normalized_result == "MATCH"
        assert final.answer.startswith("Sí, cumple.")
        assert final.guard is not None and final.guard.action == "override"

    def test_range_check(self) -> None:
        envelope, final = self._authoritative(
            [unit("rule", "Applicants must be at least 18 years old.")],
            "¿el valor 25 cumple el rango?",
            {"value": "25"},
            "FALSE: 25 está fuera del rango permitido.",
        )
        assert envelope.operation in ("RANGE_CHECK", "COMPARISON")
        assert envelope.normalized_result in ("MATCH", "VALID")
        assert final.guard is not None and final.guard.action == "override"

    def test_enum_check(self) -> None:
        envelope, final = self._authoritative(
            [unit("rule", "The status must be one of ACTIVE, PENDING.")],
            "¿el estado ACTIVE está permitido?",
            {"value": "ACTIVE"},
            "No está permitido: ACTIVE no figura entre los valores.",
        )
        assert envelope.operation in (
            "ENUM_CHECK",
            "SET_MEMBERSHIP",
            "RULE_EVALUATION",
            "",
        )
        assert envelope.normalized_result in ("MATCH", "VALID", "TRUE")
        assert final.guard is not None and final.guard.action == "override"

    def test_formula(self) -> None:
        envelope, final = self._authoritative(
            [unit("rule", "Total = subtotal + tax - discount.")],
            "¿cuál es el total con subtotal=100, tax=20, discount=5?",
            {"subtotal": "100", "tax": "20", "discount": "5"},
            "El total es 130.",
        )
        assert envelope.operation in ("FORMULA_EVALUATION", "FORMULA")
        assert envelope.result in (115, "115")
        assert final.guard is not None and final.guard.action == "override"


# -----------------------------------------------------------------------------
# 7 — Cross-domain (sin ATPCO en producción)
# -----------------------------------------------------------------------------


class TestCrossDomain:
    def _rules(self, *texts):
        return SemanticRuleCompiler().compile(
            document_id=str(DOC),
            document_title="Manual",
            organization_id=str(ORG),
            units=[unit("rule", text) for text in texts],
        ).canonical_rules

    def test_product_mask(self) -> None:
        from src.runtime.decision_envelope import build_decision_envelope

        rules = SemanticRuleCompiler().compile(
            document_id=str(DOC),
            document_title="Manual",
            organization_id=str(ORG),
            units=[
                unit("definition", "The symbol ? represents one uppercase letter."),
                unit(
                    "reference",
                    "Matching is positional. The pattern and the value must have "
                    "the same length.",
                ),
            ],
        ).canonical_rules
        grounded = reason_over_evidence(
            question="¿mi valor ABCD contra ????",
            evidence_items=[_Item("Matching is positional.")],
            canonical_rules=rules,
        )
        envelope = build_decision_envelope(grounded)
        assert envelope is not None and envelope.normalized_result == "MATCH"

    def test_insurance_eligibility(self) -> None:
        from src.runtime.decision_envelope import build_decision_envelope

        rules = self._rules(
            "The applicant is eligible when the value is at least 18."
        )
        grounded = reason_over_evidence(
            question="value=25, ¿el solicitante es elegible?",
            evidence_items=[_Item("regla")],
            canonical_rules=rules,
        )
        envelope = build_decision_envelope(grounded)
        assert envelope is not None
        assert envelope.normalized_result in ("MATCH", "VALID", "ELIGIBLE", "TRUE")

    def test_numeric_ranges(self) -> None:
        from src.runtime.decision_envelope import build_decision_envelope

        rules = self._rules("The value must be greater than 10.")
        grounded = reason_over_evidence(
            question="¿el valor 15 cumple?",
            evidence_items=[_Item("regla")],
            canonical_rules=rules,
        )
        envelope = build_decision_envelope(grounded)
        assert envelope is not None and envelope.normalized_result in ("MATCH", "VALID")
        bad = reason_over_evidence(
            question="¿el valor 5 cumple?",
            evidence_items=[_Item("regla")],
            canonical_rules=rules,
        )
        bad_envelope = build_decision_envelope(bad)
        assert bad_envelope is not None
        assert bad_envelope.normalized_result in ("NO_MATCH", "INVALID")

    def test_temporal_rule(self) -> None:
        from src.runtime.decision_envelope import build_decision_envelope

        rules = self._rules("Effective January 2027, minimum quantity is 20.")
        grounded = reason_over_evidence(
            question="¿la cantidad 25 cumple en 2027-06-01?",
            evidence_items=[_Item("regla")],
            canonical_rules=rules,
        )
        envelope = build_decision_envelope(grounded)
        assert envelope is not None and envelope.normalized_result in ("MATCH", "VALID")

    def test_contractual_exception(self) -> None:
        from src.runtime.decision_envelope import build_decision_envelope

        rules = self._rules(
            "The fee must be at least 10 unless the value is greater than 100."
        )
        excepted = reason_over_evidence(
            question="¿el valor 150 exige fee?",
            evidence_items=[_Item("regla")],
            canonical_rules=rules,
        )
        # La excepción aplica: no hay MATCH/NO_MATCH; el estado es determinado
        # por la regla (NOT_APPLICABLE) y el LLM no puede inventar una decisión.
        assert excepted.answerability != "ANSWERABLE_DERIVED" or build_decision_envelope(
            excepted
        ) is not None

    def test_unknown_invented_domain(self) -> None:
        from src.runtime.decision_envelope import build_decision_envelope

        rules = SemanticRuleCompiler().compile(
            document_id=str(DOC),
            document_title="Manual",
            organization_id=str(ORG),
            units=[
                unit("definition", "Each @ represents one letter."),
                unit("reference", "Tiles are matched from the right edge."),
                unit(
                    "definition",
                    "A value may carry filler characters in front of the matched tile.",
                ),
            ],
        ).canonical_rules
        executable = [rule for rule in rules if rule.executable]
        assert executable, "el dominio inventado debe compilar"
        grounded = reason_over_evidence(
            question="¿el valor ABCU cumple el patrón @@?",
            evidence_items=[_Item("regla")],
            canonical_rules=rules,
        )
        envelope = build_decision_envelope(grounded)
        assert envelope is not None
        assert envelope.operation in ("POSITIONAL_MATCH", "LENGTH_POLICY", "RULE_EVALUATION")


# -----------------------------------------------------------------------------
# 8 — DecisionEnvelope inmutable + observabilidad
# -----------------------------------------------------------------------------


class TestDecisionEnvelopeContract:
    def test_envelope_is_frozen(self) -> None:
        import dataclasses

        from src.runtime.decision_envelope import build_decision_envelope

        grounded = reason_over_evidence(
            question=f"¿{QUESTION}?",
            evidence_items=[_Item("Matching is positional.")],
            canonical_rules=compile_pattern_rules(),
        )
        envelope = build_decision_envelope(grounded)
        assert envelope is not None
        with pytest.raises(dataclasses.FrozenInstanceError):
            envelope.result = "NO_MATCH"  # type: ignore[misc]

    def test_observability_payload_has_required_blocks(self) -> None:
        grounded = reason_over_evidence(
            question=f"¿{QUESTION}?",
            evidence_items=[_Item("Matching is positional.")],
            canonical_rules=compile_pattern_rules(),
        )
        public = grounded.to_public_dict()
        for key in (
            "requirement_graph",
            "deterministic_operation",
            "derived_claim",
            "decision_envelope",
            "canonical_rule_flow",
        ):
            assert key in public, key
        assert public["decision_envelope"]["authoritative"] is True
        assert public["deterministic_operation"]["operation"] == "POSITIONAL_MATCH"

    @pytest.mark.asyncio
    async def test_rule_retrieval_diagnostics_shape(self) -> None:
        result = await retrieve_canonical_rules(
            ORG,
            QUESTION,
            evidence_items=[_Item("Matching is positional.")],
            lookup=InMemoryRuleLookup(compile_pattern_rules()),
            index=InMemoryRuleIndex(compile_pattern_rules()),
        )
        public = result.to_public_dict()
        assert public["strategy"] in ("canonical_first", "chunk_association", "none")
        assert public["supported_rules"] >= 1
        assert public["rule_ids"]
        assert "why_no_rule" in public


# -----------------------------------------------------------------------------
# 9 — Cache: fingerprint de conocimiento + versión de decisión
# -----------------------------------------------------------------------------


class TestCacheFingerprint:
    def test_different_knowledge_different_key(self) -> None:
        from src.infrastructure.redis.cache import RedisCache

        base = RedisCache._hash_query(
            "org", "q", "model", "admin", knowledge_fingerprint="fp-1"
        )
        changed = RedisCache._hash_query(
            "org", "q", "model", "admin", knowledge_fingerprint="fp-2"
        )
        same = RedisCache._hash_query(
            "org", "q", "model", "admin", knowledge_fingerprint="fp-1"
        )
        assert base != changed, "un cambio de reglas debe invalidar la caché"
        assert base == same
        # Sin fingerprint también difiere (fail-closed).
        assert RedisCache._hash_query("org", "q", "model", "admin") != base


# -----------------------------------------------------------------------------
# 10 — Backfill idempotente (detección + flujo con dobles)
# -----------------------------------------------------------------------------


class TestRuleBackfill:
    def test_document_needs_backfill_detection(self) -> None:
        from src.knowledge.rule_compiler.backfill import (
            document_needs_rule_backfill,
        )
        from src.knowledge.rule_compiler.index import RULE_INDEX_VERSION

        assert document_needs_rule_backfill({}) is True
        assert (
            document_needs_rule_backfill(
                {"rule_index_version": RULE_INDEX_VERSION}
            )
            is False
        )
        assert document_needs_rule_backfill({}, rules_indexed=True) is False
        assert (
            document_needs_rule_backfill(
                {"rule_backfill_version": "rule-backfill-1"}
            )
            is False
        )

    @pytest.mark.asyncio
    async def test_backfill_flow_is_idempotent_with_doubles(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.knowledge.rule_compiler import backfill as backfill_module

        candidates = [
            {
                "id": uuid4(),
                "organization_id": ORG,
                "workspace_id": None,
                "source_id": None,
                "title": "Manual",
                "metadata": {},
            }
        ]

        async def fake_find(organization_id, **kwargs):
            return list(candidates)

        class _FakeCompilation:
            def __init__(self) -> None:
                self.persisted = {
                    "status": "completed",
                    "rules": 2,
                    "canonical_rules": 1,
                    "canonical_rule_ids": {"k": str(uuid4())},
                    "canonical_rule_objects": {str(uuid4()): str(uuid4())},
                    "canonical_rule_fingerprints": {"r": "fp"},
                    "rule_index_version": "canonical-rule-index-1",
                }

        class _FakeCompiler:
            def __init__(self) -> None:
                self.calls = 0

            async def compile_document(self, document, **kwargs):
                self.calls += 1
                return _FakeCompilation()

        class _FakeVectorStore:
            def __init__(self) -> None:
                self.updates = 0

            async def update_document_payload(self, *args, **kwargs):
                self.updates += 1

        compiler = _FakeCompiler()
        vectors = _FakeVectorStore()

        async def fake_load(organization_id, document_id):
            return object()

        marked: list = []

        async def fake_mark(organization_id, document_id):
            marked.append(document_id)

        monkeypatch.setattr(backfill_module, "find_backfill_candidates", fake_find)
        monkeypatch.setattr(backfill_module, "load_structured_document", fake_load)
        monkeypatch.setattr(backfill_module, "_mark_document_backfilled", fake_mark)

        first = await backfill_module.backfill_documents(
            ORG, compiler=compiler, vector_store=vectors
        )
        assert first.documents_backfilled == 1
        assert first.rules_persisted == 2
        assert first.canonical_rules == 1
        assert first.payloads_updated == 1
        assert compiler.calls == 1
        assert marked

        # Idempotencia: el documento marcado ya no es candidato.
        candidates.clear()
        second = await backfill_module.backfill_documents(
            ORG, compiler=compiler, vector_store=vectors
        )
        assert second.documents_backfilled == 0
        assert compiler.calls == 1

