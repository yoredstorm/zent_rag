# =============================================================================
# Evidence usage + cronología JEV — «Ver flujo» describe lo que ZENT hizo
# =============================================================================
# Regresión del caso &&&F vs ABCFGEGE: la regla y el DerivedClaim usan
# evidencia que no se mostró al LLM; JEV pidió más evidencia y Premise Closure
# lo resolvió. La traza debe mostrar ejes de uso separados, el juicio JEV
# superado y las citas todas con referencia existente.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

from src.rag.traceability import build_traceability
from src.runtime.evidence import EvidenceItem, EvidenceRegistry, evidence_invariants


def _registry_item(evidence_id: str, *, document_id: str = "doc-1", chunk: str = "c1"):
    return EvidenceItem(
        source_type="qdrant",
        content=f"fragmento {evidence_id} del manual",
        document_id=document_id,
        chunk_id=f"{chunk}-{evidence_id}",
        evidence_id=evidence_id,
        title="manual.pdf",
        score=0.9,
    )


def _evidence_block() -> dict:
    registry = EvidenceRegistry()
    registry.add(
        [
            _registry_item("E1"),
            _registry_item("E2"),
            _registry_item("E3"),
        ]
    )
    return registry.to_public_dict(
        selected_ids=("E1", "E2"),
        reasoning_ids=("E1", "E2"),
        cited_ids=("E2",),
        decision_ids=("E3",),
        rule_compilation_ids=("E3",),
        premise_closure_ids=("E3",),
    )


def _item(eid: str, **overrides) -> dict:
    item = {
        "evidence_id": eid,
        "document_id": "doc-1",
        "chunk_id": f"c-{eid}",
        "original_filename": "manual.pdf",
        "page": 1,
        "excerpt": f"fragmento {eid}",
        "status": "USED",
        "score": 0.9,
        "doc_index": 1,
    }
    item.update(overrides)
    return item


def _authoritative_flow(**overrides) -> dict:
    flow = {
        "status": "completed",
        "method": "agent",
        "question": (
            "yo tengo en el record 2 &&&F y en el farebasis me viene "
            "ABCFGEGE cumple o no cumple"
        ),
        "generation": {"skipped": False},
        "sources": [],
        "fallbacks": [],
        "timings": {},
        "retrieval": {
            "used": True,
            "chunks": 3,
            "attempts": 2,
            "expanded": True,
            "rounds": [
                {"attempt": 1, "sufficient": False, "n_items": 2},
                {"attempt": 2, "sufficient": True, "n_items": 3},
            ],
        },
        "grounding": {"grounded": True, "score": 0.8},
        "steps": [
            {
                "id": "s1",
                "type": "grounded_reasoning",
                "status": "ok",
                "derived_claim": {
                    "deterministic": True,
                    "verification_status": "SUPPORTED",
                    "operation": "POSITIONAL_MATCH",
                    "result": True,
                    "canonical_rule_ids": ["rule:atpco"],
                    "evidence_refs": ["E3"],
                },
                "decision_envelope": {
                    "authoritative": True,
                    "operation": "POSITIONAL_MATCH",
                    "result": "MATCH",
                    "canonical_rule_ids": ["rule:atpco"],
                    "evidence_refs": ["E3"],
                },
            },
            {
                "id": "s2",
                "type": "premise_closure",
                "status": "ok",
                "termination": "SATISFIED",
                "missing_after": [],
                "rules_added": 1,
                "evidence_added": 1,
                "detail": {
                    "rounds": [{"new_evidence_refs": ["E3"]}],
                    "missing_after": [],
                    "rules_added": 1,
                    "evidence_added": 1,
                },
            },
            {
                "id": "s3",
                "type": "final_authority_lock",
                "authoritative": True,
                "operation": "POSITIONAL_MATCH",
                "result": "MATCH",
                "lock_action": "preserved",
            },
        ],
        "jev_preflight": {
            "mode": "on",
            "packs": [
                {
                    "phase": "post_retrieval",
                    "status": "ok",
                    "question_count": 2,
                    "questions": [
                        {
                            "id": "needs_more_evidence",
                            "type": "noul",
                            "decision": "yes",
                            "confidence": 0.9,
                        },
                        {
                            "id": "satisfied",
                            "type": "noul",
                            "decision": "no",
                            "confidence": 0.9,
                        },
                    ],
                }
            ],
            "decisions": [
                {
                    "phase": "post_retrieval",
                    "action": "retrieve_more",
                    "applied": True,
                    "question_id": "needs_more_evidence",
                    "reasons": ["missing_evidence"],
                }
            ],
            "summary": {"calls": 1, "judgments": 2},
        },
        "evidence": {
            **_evidence_block(),
            "counts": {
                "evidence_retrieved": 3,
                "evidence_unique": 3,
                "evidence_selected": 2,
                "evidence_used": 3,
                "evidence_used_for_reasoning": 2,
                "evidence_used_for_rule_compilation": 1,
                "evidence_used_for_premise_closure": 1,
                "evidence_used_for_decision": 1,
                "evidence_cited": 1,
                "documents_consulted": 1,
                "documents_selected": 1,
                "documents_used_for_decision": 1,
                "documents_cited": 1,
            },
        },
        "citations": [{"index": 1, "evidence_id": "E2", "cited": True}],
    }
    flow.update(overrides)
    return flow


# ---------------------------------------------------------------------------
# §1-§4 — modelo único de uso, por ejes
# ---------------------------------------------------------------------------


def test_registry_flags_son_independientes() -> None:
    public = _evidence_block()
    assert public["retrieved_count"] == 3
    assert public["unique_count"] == 3
    assert public["selected_count"] == 2
    assert public["used_for_reasoning_count"] == 2
    assert public["used_for_rule_compilation_count"] == 1
    assert public["used_for_premise_closure_count"] == 1
    assert public["used_for_decision_count"] == 1
    assert public["cited_count"] == 1
    assert public["documents_retrieved_count"] == 1
    assert public["documents_used_for_decision_count"] == 1
    assert public["documents_cited_count"] == 1
    by_id = {item["evidence_id"]: item for item in public["items"]}
    assert by_id["E3"]["used_for_decision"] is True
    assert by_id["E3"]["selected"] is False
    assert by_id["E1"]["used_for_reasoning"] is True
    assert by_id["E1"]["used_for_decision"] is False
    assert by_id["E2"]["cited"] is True
    assert by_id["E2"]["citation_only_context"] is False
    assert evidence_invariants(public) == []


def test_derived_claim_marca_used_for_decision_en_la_traza() -> None:
    trace = build_traceability(_authoritative_flow())
    counts = trace["evidence"]["counts"]
    assert counts["evidence_used_for_decision"] == 1
    assert counts["documents_used_for_decision"] == 1
    canonical = {
        item["evidence_id"]: item for item in trace["evidence"]["canonical_evidence"]
    }
    assert canonical["E3"]["used_for_decision"] is True
    assert canonical["E3"]["used_for_rule_compilation"] is True
    assert canonical["E1"]["used_for_reasoning"] is True
    # La evidencia de la decisión no puede quedar como "0 usadas".
    assert trace["evidence"]["counts"]["evidence_used"] >= 1


def test_soporte_publica_los_ejes_sin_mezclarlos() -> None:
    trace = build_traceability(_authoritative_flow())
    support = trace["presentation"]["support"]
    assert support["evidence_unique"] == 3
    assert support["evidence_used_for_decision"] == 1
    assert support["evidence_used_for_reasoning"] == 2
    assert support["documents_used_for_decision"] == 1
    assert support["documents_cited"] == 1


# ---------------------------------------------------------------------------
# §5 — integridad referencial de citas
# ---------------------------------------------------------------------------


def test_todas_las_citas_apuntan_a_evidencia_existente() -> None:
    trace = build_traceability(_authoritative_flow())
    canonical_ids = {
        item["evidence_id"] for item in trace["evidence"]["canonical_evidence"]
    }
    for citation in trace["evidence"]["citations"]:
        assert citation["evidence_id"] in canonical_ids
    assert trace["evidence"]["citations_summary"]["dangling"] == []


# ---------------------------------------------------------------------------
# §7-§8 — cronología JEV y juicios superados
# ---------------------------------------------------------------------------


def test_jev_intermedio_queda_superado_por_la_decision() -> None:
    trace = build_traceability(_authoritative_flow())
    jev = trace["jev"]
    assert jev["requested_more_evidence"] is True
    assert jev["resolution"]["label"] == "DecisionEnvelope MATCH"
    assert jev["superseded_count"] >= 3
    judgments = {j["question_code"]: j for j in jev["judgments"]}
    assert judgments["needs_more_evidence"]["status"] == "SUPERSEDED"
    assert judgments["needs_more_evidence"]["superseded_by"] == "DecisionEnvelope MATCH"
    assert judgments["satisfied"]["status"] == "SUPERSEDED"
    [decision] = jev["decisions"]
    assert decision["action"] == "retrieve_more"
    assert decision["status"] == "SUPERSEDED"
    assert decision["superseded_by"] == "DecisionEnvelope MATCH"


def test_juicio_superado_conserva_su_historia() -> None:
    trace = build_traceability(_authoritative_flow())
    [judgment] = [
        item for item in trace["jev"]["judgments"] if item["question_code"] == "satisfied"
    ]
    assert judgment["answer"] == "no"  # el hecho histórico no se reescribe
    assert judgment["sequence"] >= 1
    assert judgment["final_effect"] == "resolved_by_later_stage"


# ---------------------------------------------------------------------------
# §9 — historia: premise closure y autoridad determinista en el journey
# ---------------------------------------------------------------------------


def test_journey_cuenta_la_cronologia_real() -> None:
    trace = build_traceability(_authoritative_flow())
    journey = [node["kind"] for node in trace["presentation"]["journey"]]
    assert journey.index("RETRIEVAL_RETRIED") < journey.index("PREMISES_CLOSED")
    assert journey.index("PREMISES_CLOSED") < journey.index("RULE_COMPILED")
    assert journey.index("RULE_COMPILED") < journey.index("DETERMINISTIC_AUTHORITY")
    authority = next(
        node
        for node in trace["presentation"]["journey"]
        if node["kind"] == "DETERMINISTIC_AUTHORITY"
    )
    assert authority["params"]["operation"] == "POSITIONAL_MATCH"
    assert authority["params"]["result"] == "MATCH"


# ---------------------------------------------------------------------------
# §12 — warnings duplicados agrupados
# ---------------------------------------------------------------------------


def test_identidad_debil_se_agrupa_con_cantidad() -> None:
    weak_items = []
    for evidence_id in ("E1", "E2", "E3"):
        item = _item(evidence_id)
        item.pop("original_filename", None)
        weak_items.append(item)
    flow = _authoritative_flow(sources=weak_items)
    flow.pop("evidence")
    flow.pop("citations")
    trace = build_traceability(flow)
    weak = [
        item
        for item in trace["diagnostics"]["items"]
        if item["code"] == "CANONICAL_SOURCE_WEAK_IDENTITY"
    ]
    assert len(weak) == 1
    assert weak[0]["params"]["count"] == 3


# ---------------------------------------------------------------------------
# §14 — regresión completa del caso real (motor determinista real)
# ---------------------------------------------------------------------------


def test_identidad_fuerte_desde_parser_evita_warning() -> None:
    registry = EvidenceRegistry()
    registry.add_from_meta(
        {
            "evidence": [
                {
                    "content": "fragmento con identidad física",
                    "document_id": "doc-1",
                    "chunk_id": "c1",
                    "evidence_id": "E1",
                    "original_file_id": "file-abc",
                    "original_filename": "atpco.pdf",
                }
            ]
        }
    )
    public = registry.to_public_dict(selected_ids=("E1",), reasoning_ids=("E1",))
    assert public["items"][0]["original_file_id"] == "file-abc"
    assert public["items"][0]["retrieved"] is True
    assert public["items"][0]["cited_in_answer"] is False
    flow = {
        "status": "completed",
        "method": "agent",
        "generation": {"skipped": False},
        "sources": [],
        "fallbacks": [],
        "timings": {},
        "evidence": {
            **public,
            "counts": {
                "evidence_retrieved": 1,
                "evidence_used": 1,
                "documents_consulted": 1,
            },
        },
    }
    trace = build_traceability(flow)
    canonical = trace["evidence"]["canonical_evidence"][0]
    assert canonical["canonical_source_id"].startswith("src_")
    weak = [
        item
        for item in trace["diagnostics"]["items"]
        if item["code"] == "CANONICAL_SOURCE_WEAK_IDENTITY"
    ]
    assert weak == []


def test_regresion_caso_real_amplificador() -> None:
    from src.intelligence.reasoning.grounded_engine import reason_over_evidence
    from src.knowledge.compiler.model import EvidenceRef, SemanticUnit, SourceLocator
    from src.knowledge.rule_compiler import SemanticRuleCompiler
    from src.runtime.decision_envelope import build_decision_envelope

    document_id = str(uuid4())
    organization_id = str(uuid4())

    def _unit(kind: str, text: str, page: int) -> SemanticUnit:
        return SemanticUnit(
            kind=kind,
            key=f"{kind}:{text[:24]}",
            label=text[:24],
            text=text,
            confidence=0.8,
            evidence=EvidenceRef(
                locator=SourceLocator(
                    document_id=document_id,
                    document_title="Manual",
                    page=page,
                    section_path=("Matching",),
                ),
                excerpt=text,
            ),
        )

    rules = SemanticRuleCompiler().compile(
        document_id=document_id,
        document_title="Manual",
        organization_id=organization_id,
        units=[
            _unit(
                "definition",
                "The value may contain more characters than the pattern.",
                1,
            ),
            _unit("definition", "The symbol & represents one alphanumeric position.", 7),
            _unit(
                "reference",
                "Matching is positional, left to right. Literal characters must "
                "match exactly at their position.",
                2,
            ),
        ],
    ).canonical_rules
    assert any(rule.executable for rule in rules)

    class _Item:
        def __init__(self, content: str, evidence_id: str) -> None:
            self.content = content
            self.evidence_id = evidence_id
            self.metadata: dict = {}

    grounded = reason_over_evidence(
        question=(
            "yo tengo en el record 2 &&&F y en el farebasis me viene "
            "ABCFGEGE cumple o no cumple"
        ),
        evidence_items=[_Item("Matching is positional, left to right.", "E1")],
        canonical_rules=rules,
    )
    envelope = build_decision_envelope(grounded)
    assert envelope is not None
    assert envelope.normalized_result == "MATCH"

    public = grounded.to_public_dict()
    evidence_refs = list(
        (public.get("derived_claim") or {}).get("evidence_refs") or []
    )
    assert evidence_refs, "el motor real debe publicar refs de evidencia"

    registry = EvidenceRegistry()
    registry.add(
        [
            EvidenceItem(
                source_type="qdrant",
                content="Matching is positional, left to right.",
                document_id="doc-atpco",
                chunk_id="c1",
                evidence_id=evidence_refs[0],
                title="atpco-rules.pdf",
                score=0.9,
            )
        ]
    )
    evidence_block = registry.to_public_dict(
        selected_ids=(evidence_refs[0],),
        reasoning_ids=(evidence_refs[0],),
        cited_ids=(evidence_refs[0],),
        decision_ids=evidence_refs,
        rule_compilation_ids=evidence_refs,
        premise_closure_ids=evidence_refs,
    )

    flow = {
        "status": "completed",
        "method": "agent",
        "question": public.get("question") or "&&&F vs ABCFGEGE",
        "generation": {"skipped": False},
        "sources": [],
        "fallbacks": [],
        "retrieval": {"used": True, "chunks": 1, "attempts": 1, "rounds": []},
        "grounding": {"grounded": False, "score": 0.0, "policy": "strict_source"},
        "steps": [
            {"id": "s1", "type": "grounded_reasoning", "status": "ok", **public},
            {
                "id": "s2",
                "type": "final_authority_lock",
                "authoritative": True,
                "operation": envelope.operation,
                "result": envelope.normalized_result,
                "lock_action": "preserved",
            },
        ],
        "verification": {
            "overall": "blocked",
            "checks": [
                {"key": "answer_gate", "state": "warn"},
                {"key": "grounding", "state": "blocked"},
            ],
        },
        "evidence": evidence_block,
        "citations": [{"index": 1, "evidence_id": evidence_refs[0], "cited": True}],
    }
    trace = build_traceability(flow)

    counts = trace["evidence"]["counts"]
    assert (counts["evidence_retrieved"] or 0) > 0
    assert (counts["evidence_unique"] or 0) > 0
    assert (counts["evidence_used_for_decision"] or 0) > 0
    assert (counts["documents_used_for_decision"] or 0) >= 1
    assert trace["verification"]["decision_verification"]["status"] == "VERIFIED"
    assert trace["verification"]["decision_verification"]["result"] == "MATCH"
    canonical_ids = {
        item["evidence_id"] for item in trace["evidence"]["canonical_evidence"]
    }
    for citation in trace["evidence"]["citations"]:
        assert citation["evidence_id"] in canonical_ids
    assert trace["evidence"]["citations_summary"]["dangling"] == []
    assert "0 usadas" not in str(trace["presentation"]["support"])
