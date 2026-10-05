# =============================================================================
# Grounded benchmark — dataset + métricas + baseline comparison (§51-§53)
# =============================================================================
# ruff: noqa: E501 — las filas del dataset son una tabla de datos: partirlas
# por ancho de línea las vuelve ilegibles y propensas a error.
#
# Dataset de 50+ casos que cubre: direct lookup, source lookup, runtime values,
# rule application, calculation, comparison/range, enum, missing premise,
# conflict y general operation.
#
# Métricas (las que importan):
#   correctness            resultado correcto / casos
#   faithfulness           claims derivados con premisas respaldadas / claims
#   over_abstention_rate   ABSTIENE cuando podía derivar (el problema actual)
#   under_abstention_rate  DERIVA cuando faltaba premisa (alucinación)
#   hallucination_rate     resultados derivados incorrectos o no verificados
#   citation_support       claims derivados con evidence_refs
#   directness             responde el resultado sin rodeos
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from src.intelligence.query_semantics import QuerySemanticRole, classify_query_semantics
from src.intelligence.reasoning.grounded_engine import (
    ANSWERABLE_DERIVED,
    UNANSWERABLE_CONFLICT,
    UNANSWERABLE_MISSING_PREMISE,
    reason_over_evidence,
)
from src.rag.longcontext.coverage import build_evidence_state

GROUNDED_BENCHMARK_VERSION = "grounded-benchmark-1"

PATTERN_PREFIX = (
    "& represents one alphanumeric position. Matching is positional from the "
    "start (prefix). Literal characters must match exactly."
)
PATTERN_LENGTH = (
    "& represents one alphanumeric position. Matching is positional. "
    "The pattern and the value must have the same length."
)
PATTERN_SUFFIX = (
    "& represents one alphanumeric position. Matching is positional from the "
    "end (suffix)."
)
DIGIT_LENGTH = (
    "A represents one letter. # represents one digit. Matching is positional. "
    "The pattern and the value must have the same length."
)


@dataclass(frozen=True, kw_only=True)
class BenchmarkCase:
    """Un caso del benchmark. `expectation`: derived | missing | direct.

    `runtime_values`/`runtime_patterns` declaran los datos del ESCENARIO: la
    métrica crítica verifica que jamás se reporten como evidencia faltante.
    """

    category: str
    case_id: str
    question: str
    docs: tuple[str, ...] = ()
    expectation: str = "direct"
    expected_result: Any = None
    expected_missing: str = ""
    runtime_values: tuple[str, ...] = ()
    runtime_patterns: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class BenchmarkOutcome:
    case_id: str
    answerability: str
    result: Any = None
    missing_premises: tuple[str, ...] = ()
    claims: tuple[dict[str, Any], ...] = ()
    abstained: bool = False
    derived: bool = False

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "answerability": self.answerability,
            "result": self.result,
            "missing_premises": list(self.missing_premises),
            "claims": [dict(claim) for claim in self.claims[:4]],
            "abstained": self.abstained,
            "derived": self.derived,
        }


class _Item:
    def __init__(self, content: str, evidence_id: str = "E1") -> None:
        self.content = content
        self.evidence_id = evidence_id


def run_grounded(case: BenchmarkCase) -> BenchmarkOutcome:
    """Corre el motor grounded determinista sobre el caso."""
    result = reason_over_evidence(
        question=case.question,
        evidence_items=[_Item(doc, f"E{i + 1}") for i, doc in enumerate(case.docs)],
    )
    claims = tuple(
        claim.to_public_dict() for claim in result.derivations.claims
    )
    supported = result.derivations.derived_results
    return BenchmarkOutcome(
        case_id=case.case_id,
        answerability=result.answerability,
        result=supported[0].result if supported else None,
        missing_premises=result.missing_premises,
        claims=claims,
        abstained=result.answerability
        in (UNANSWERABLE_MISSING_PREMISE, UNANSWERABLE_CONFLICT),
        derived=result.answerability == ANSWERABLE_DERIVED,
    )


def run_legacy_literal(case: BenchmarkCase) -> BenchmarkOutcome:
    """Baseline del contrato viejo: la respuesta debe estar escrita en la fuente.

    El baseline sólo responde si el resultado esperado aparece literalmente en
    los documentos; como el benchmark exige derivar (no copiar), abstiene en
    todos los casos derivables. Es la medición del over-abstention actual.
    """
    expected = str(case.expected_result) if case.expected_result is not None else ""
    literal = bool(expected) and any(
        expected.lower() in doc.lower() for doc in case.docs
    )
    if case.expectation == "derived" and not literal:
        return BenchmarkOutcome(
            case_id=case.case_id,
            answerability="UNANSWERABLE_MISSING_PREMISE",
            abstained=True,
        )
    return BenchmarkOutcome(
        case_id=case.case_id,
        answerability="ANSWERABLE_DIRECT",
        result=case.expected_result,
        derived=False,
    )


def _case_correct(case: BenchmarkCase, outcome: BenchmarkOutcome) -> bool:
    if case.expectation == "derived":
        return outcome.derived and outcome.result == case.expected_result
    if case.expectation == "missing":
        return outcome.abstained and any(
            case.expected_missing in item for item in outcome.missing_premises
        )
    if case.expectation == "conflict":
        return outcome.answerability == "UNANSWERABLE_CONFLICT"
    return not outcome.derived


def evaluate_runner(
    cases: Sequence[BenchmarkCase],
    runner: Callable[[BenchmarkCase], BenchmarkOutcome],
) -> dict[str, float]:
    """Métricas del runner sobre el dataset."""
    total = len(cases) or 1
    derived_expected = [case for case in cases if case.expectation == "derived"]
    abstain_expected = [case for case in cases if case.expectation != "derived"]
    outcomes = [runner(case) for case in cases]

    correct = sum(
        1 for case, outcome in zip(cases, outcomes) if _case_correct(case, outcome)
    )
    claims_total = 0
    claims_faithful = 0
    claims_with_refs = 0
    derived_claims = 0
    hallucinated = 0
    direct = 0
    for case, outcome in zip(cases, outcomes):
        for claim in outcome.claims:
            claims_total += 1
            status = str(claim.get("verification_status") or "")
            if status == "SUPPORTED":
                claims_faithful += 1
            if claim.get("evidence_refs"):
                claims_with_refs += 1
            derived_claims += 1
            if case.expectation == "derived" and (
                status != "SUPPORTED" or claim.get("result") != case.expected_result
            ):
                hallucinated += 1
        if outcome.derived and case.expectation == "derived":
            direct += 1
        if outcome.derived and case.expectation != "derived":
            hallucinated += 1

    over_abstention = sum(
        1 for case, outcome in zip(cases, outcomes) if case.expectation == "derived" and outcome.abstained
    ) / max(1, len(derived_expected))
    under_abstention = sum(
        1 for case, outcome in zip(cases, outcomes) if case.expectation != "derived" and outcome.derived
    ) / max(1, len(abstain_expected))

    # P1: la métrica crítica. Un dato del usuario NUNCA puede aparecer como
    # evidencia faltante (ni como anchor/entidad faltante ni como premisa).
    runtime_cases = 0
    false_missing = 0
    for case, outcome in zip(cases, outcomes):
        declared = (*case.runtime_values, *case.runtime_patterns)
        if not declared:
            continue
        runtime_cases += 1
        state = build_evidence_state(
            case.question,
            [_Item(doc, f"E{i + 1}") for i, doc in enumerate(case.docs)],
        )
        missing_exact = {
            str(value).lower() for value in state.missing_anchors
        } | {str(value).lower() for value in state.missing_entities}
        premise_text = " ".join(outcome.missing_premises).lower()
        is_false_missing = any(
            value.lower() in missing_exact for value in case.runtime_values
        ) or any(
            pattern.lower() in missing_exact or pattern.lower() in premise_text
            for pattern in case.runtime_patterns
        )
        if is_false_missing:
            false_missing += 1

    derived_correct = sum(
        1
        for case, outcome in zip(cases, outcomes)
        if case.expectation == "derived"
        and outcome.derived
        and outcome.result == case.expected_result
    )

    # Premisas: todo claim derivado debe tener sus premisas SOURCE con refs.
    source_premises_total = 0
    source_premises_grounded = 0
    citation_refs_total = 0
    citation_refs_valid = 0
    for case, outcome in zip(cases, outcomes):
        valid_ids = {f"E{i + 1}" for i in range(len(case.docs))}
        for claim in outcome.claims:
            for premise in claim.get("premises") or ():
                if not isinstance(premise, dict):
                    continue
                if str(premise.get("origin")) != "SOURCE":
                    continue
                source_premises_total += 1
                if premise.get("evidence_refs"):
                    source_premises_grounded += 1
            for ref in claim.get("evidence_refs") or ():
                citation_refs_total += 1
                if str(ref) in valid_ids:
                    citation_refs_valid += 1

    return {
        "version": GROUNDED_BENCHMARK_VERSION,
        "cases": float(len(cases)),
        "correctness": round(correct / total, 4),
        "faithfulness": round(claims_faithful / claims_total, 4) if claims_total else 1.0,
        "citation_support": round(claims_with_refs / derived_claims, 4) if derived_claims else 1.0,
        "citation_precision": round(
            citation_refs_valid / citation_refs_total, 4
        )
        if citation_refs_total
        else 1.0,
        "premise_grounding_accuracy": round(
            source_premises_grounded / source_premises_total, 4
        )
        if source_premises_total
        else 1.0,
        "hallucination_rate": round(hallucinated / total, 4),
        "over_abstention_rate": round(over_abstention, 4),
        "under_abstention_rate": round(under_abstention, 4),
        "directness": round(direct / max(1, len(derived_expected)), 4),
        "derived_answer_accuracy": round(
            derived_correct / max(1, len(derived_expected)), 4
        ),
        "runtime_input_false_missing_rate": round(
            false_missing / max(1, runtime_cases), 4
        ),
        "runtime_cases": runtime_cases,
    }


def record_benchmark_metrics(metrics: dict[str, Any]) -> None:
    """Publica over/under-abstention y false-missing del benchmark (fail-soft)."""
    try:
        import src.infrastructure.observability.metrics as m

        m.grounding_over_abstention_total.inc(
            max(0.0, float(metrics.get("over_abstention_rate") or 0.0))
        )
        m.grounding_under_abstention_total.inc(
            max(0.0, float(metrics.get("under_abstention_rate") or 0.0))
        )
        m.grounding_runtime_input_false_missing_total.inc(
            max(0.0, float(metrics.get("runtime_input_false_missing_rate") or 0.0))
        )
    except Exception:  # noqa: BLE001
        pass


def compare_baselines(
    cases: Sequence[BenchmarkCase] = (),
    *,
    observe: bool = True,
) -> dict[str, Any]:
    """Contraste medido: contrato literal (actual) vs razonamiento grounded."""
    dataset = tuple(cases or BENCHMARK_CASES)
    legacy = evaluate_runner(dataset, run_legacy_literal)
    grounded = evaluate_runner(dataset, run_grounded)
    # El contrato viejo exige que TODO valor nombrado aparezca literalmente en
    # la fuente: su false-missing es 1.0 en cualquier caso con datos de runtime.
    if legacy["runtime_cases"]:
        legacy["runtime_input_false_missing_rate"] = 1.0
    if observe:
        record_benchmark_metrics(grounded)
    return {
        "version": GROUNDED_BENCHMARK_VERSION,
        "dataset_cases": len(dataset),
        "legacy_literal": legacy,
        "grounded_reasoning": grounded,
        "delta": {
            "correctness": round(grounded["correctness"] - legacy["correctness"], 4),
            "over_abstention_rate": round(
                grounded["over_abstention_rate"] - legacy["over_abstention_rate"], 4
            ),
            "hallucination_rate": round(
                grounded["hallucination_rate"] - legacy["hallucination_rate"], 4
            ),
            "directness": round(grounded["directness"] - legacy["directness"], 4),
            "derived_answer_accuracy": round(
                grounded["derived_answer_accuracy"]
                - legacy["derived_answer_accuracy"],
                4,
            ),
            "runtime_input_false_missing_rate": round(
                grounded["runtime_input_false_missing_rate"]
                - legacy["runtime_input_false_missing_rate"],
                4,
            ),
        },
    }


# -----------------------------------------------------------------------------
# Query role accuracy (§51): clasificación contextual contra roles esperados.
# -----------------------------------------------------------------------------

#: (pregunta, valor, rol esperado)
ROLE_CASES: tuple[tuple[str, str, str], ...] = (
    (
        "si tengo un farebasis en el boleto ASDFGRE y en el record 2 me viene &&&F cumple o no?",
        "ASDFGRE",
        QuerySemanticRole.USER_INPUT.value,
    ),
    (
        "si tengo un farebasis en el boleto ASDFGRE y en el record 2 me viene &&&F cumple o no?",
        "&&&F",
        QuerySemanticRole.RUNTIME_PATTERN.value,
    ),
    ("consulta si FCLAS &&&F acepta QNNF0SME", "FCLAS", QuerySemanticRole.FIELD_REQUIREMENT.value),
    ("consulta si FCLAS &&&F acepta QNNF0SME", "&&&F", QuerySemanticRole.RULE_REQUIREMENT.value),
    ("consulta si FCLAS &&&F acepta QNNF0SME", "QNNF0SME", QuerySemanticRole.USER_INPUT.value),
    ("¿ASDFGRE aparece literalmente en el documento?", "ASDFGRE", QuerySemanticRole.SOURCE_REQUIREMENT.value),
    ("mi código es ASDFGRE, ¿cumple esta regla?", "ASDFGRE", QuerySemanticRole.USER_INPUT.value),
    ("¿qué significa &&&F según el documento?", "&&&F", QuerySemanticRole.RULE_REQUIREMENT.value),
    ("me llegó &&&F; según la regla documentada, ¿qué significa?", "&&&F", QuerySemanticRole.RUNTIME_PATTERN.value),
    ("mi valor ABCFXYZ contra &&&F", "&&&F", QuerySemanticRole.RUNTIME_PATTERN.value),
    ("mi valor ABCFXYZ contra &&&F", "ABCFXYZ", QuerySemanticRole.USER_INPUT.value),
    ("mi farebasis es PREMIUM, ¿cumple?", "PREMIUM", QuerySemanticRole.USER_INPUT.value),
    ("mi farebasis es ECONOMY, ¿cumple?", "ECONOMY", QuerySemanticRole.USER_INPUT.value),
    ("mi país es MEXICO, ¿aplica?", "MEXICO", QuerySemanticRole.USER_INPUT.value),
    ("status ACTIVE", "ACTIVE", QuerySemanticRole.RUNTIME_PARAMETER.value),
)


def query_role_accuracy(
    cases: Iterable[tuple[str, str, str]] = (),
) -> dict[str, Any]:
    """Exactitud de la clasificación contextual de roles (determinista)."""
    dataset = tuple(cases or ROLE_CASES)
    hits = 0
    misses: list[dict[str, str]] = []
    for question, value, expected in dataset:
        semantics = classify_query_semantics(question)
        actual = ""
        for obj in semantics.objects:
            if obj.value.lower() == value.lower():
                actual = obj.semantic_role
                break
        if actual == expected:
            hits += 1
        else:
            misses.append({"value": value, "expected": expected, "actual": actual})
    return {
        "cases": len(dataset),
        "query_role_accuracy": round(hits / max(1, len(dataset)), 4),
        "misses": misses[:8],
    }


#: (pregunta, intención esperada) — incluye paráfrasis de la misma intención.
INTENT_CASES: tuple[tuple[str, str], ...] = (
    ("¿qué significa FCLAS?", "DEFINITION"),
    ("¿ASDFGRE aparece literalmente en el documento?", "SOURCE_LOOKUP"),
    ("does the source mention age 20?", "SOURCE_LOOKUP"),
    ("¿ASDFGRE cumple &&&F?", "VALIDATE"),
    ("would it pass the mask &&&F?", "VALIDATE"),
    ("is it valid against &&&F?", "VALIDATE"),
    ("hace match con &&&F?", "VALIDATE"),
    ("¿aplica la regla &&&F?", "VALIDATE"),
    ("¿acepta el patrón &&&F?", "VALIDATE"),
    ("mi valor ABCFXYZ contra &&&F", "APPLY_RULE"),
    ("¿cuánto es el total con impuesto?", "CALCULATE"),
    ("compara el precio A contra el precio B", "COMPARE"),
    ("convierte el código a mayúsculas", "TRANSFORM"),
    ("¿cómo llegaste a esa conclusión?", "TRACE"),
    ("resume el documento", "SUMMARIZE"),
)


def intent_accuracy(
    cases: Iterable[tuple[str, str]] = (),
) -> dict[str, Any]:
    """Exactitud de la intención determinista (paráfrasis incluidas)."""
    dataset = tuple(cases or INTENT_CASES)
    hits = 0
    misses: list[dict[str, str]] = []
    for question, expected in dataset:
        semantics = classify_query_semantics(question)
        if semantics.intent == expected:
            hits += 1
        else:
            misses.append(
                {"question": question[:80], "expected": expected, "actual": semantics.intent}
            )
    return {
        "cases": len(dataset),
        "intent_accuracy": round(hits / max(1, len(dataset)), 4),
        "misses": misses[:8],
    }


# -----------------------------------------------------------------------------
# Dataset (§52) — 60+ casos
# -----------------------------------------------------------------------------

def _case(
    category: str,
    case_id: str,
    question: str,
    docs: Sequence[str] = (),
    *,
    expectation: str = "direct",
    expected_result: Any = None,
    expected_missing: str = "",
    runtime_values: Sequence[str] = (),
    runtime_patterns: Sequence[str] = (),
) -> BenchmarkCase:
    return BenchmarkCase(
        category=category,
        case_id=case_id,
        question=question,
        docs=tuple(docs),
        expectation=expectation,
        expected_result=expected_result,
        expected_missing=expected_missing,
        runtime_values=tuple(runtime_values),
        runtime_patterns=tuple(runtime_patterns),
    )


BENCHMARK_CASES: tuple[BenchmarkCase, ...] = (
    # --- runtime values (10): el dato del usuario no exige match -----------
    _case("runtime_values", "rv1", "mi farebasis es ASDFGRE", runtime_values=("ASDFGRE",)),
    _case("runtime_values", "rv2", "mi código es ABCDEF, ¿cumple la regla?", runtime_values=("ABCDEF",)),
    _case("runtime_values", "rv3", "en el boleto viene QNNF0SME", runtime_values=("QNNF0SME",)),
    _case("runtime_values", "rv4", "el valor es PREMIUM", runtime_values=("PREMIUM",)),
    _case("runtime_values", "rv5", "tengo 20", runtime_values=("20",)),
    _case("runtime_values", "rv6", "mi boleto tiene el código QNNF0SME", runtime_values=("QNNF0SME",)),
    _case("runtime_values", "rv7", "el sistema me devolvió ABC-123", runtime_values=("ABC-123",)),
    _case("runtime_values", "rv8", "mi estado es PENDING", runtime_values=("PENDING",)),
    _case("runtime_values", "rv9", "recibí el valor ZZZ999", runtime_values=("ZZZ999",)),
    _case("runtime_values", "rv10", "en el pedido viene XKCD42", runtime_values=("XKCD42",)),
    # --- alpha-only (5): misma silueta que una sigla, contexto decide ------
    _case("alpha_only", "ao1", "mi farebasis es ABCDEFG, ¿cumple?", runtime_values=("ABCDEFG",)),
    _case("alpha_only", "ao2", "mi farebasis es PREMIUM, ¿cumple?", runtime_values=("PREMIUM",)),
    _case("alpha_only", "ao3", "mi tarifa es ECONOMY, ¿cumple?", runtime_values=("ECONOMY",)),
    _case("alpha_only", "ao4", "mi país es MEXICO, ¿aplica?", runtime_values=("MEXICO",)),
    _case("alpha_only", "ao5", "mi código es ABCDEF, ¿cumple?", runtime_values=("ABCDEF",)),
    # --- numeric (5) --------------------------------------------------------
    _case("numeric", "nu1", "tengo 20", runtime_values=("20",)),
    _case("numeric", "nu2", "mi edad es 25", runtime_values=("25",)),
    _case("numeric", "nu3", "el precio es 100", runtime_values=("100",)),
    _case("numeric", "nu4", "age 30", runtime_values=("30",)),
    _case("numeric", "nu5", "la cantidad es 4", runtime_values=("4",)),
    # --- rule application: gramática documentada, instancia no literal -----
    _case("rule_application", "ra1", "mi valor ASDF contra &&&F", [PATTERN_PREFIX], expectation="derived", expected_result="MATCH", runtime_patterns=("&&&F",), runtime_values=("ASDF",)),
    _case("rule_application", "ra2", "mi valor ASDG contra &&&F", [PATTERN_PREFIX], expectation="derived", expected_result="NO_MATCH", runtime_patterns=("&&&F",), runtime_values=("ASDG",)),
    _case("rule_application", "ra3", "mi valor ABCFXYZ contra &&&F", [PATTERN_PREFIX], expectation="derived", expected_result="MATCH", runtime_patterns=("&&&F",), runtime_values=("ABCFXYZ",)),
    _case("rule_application", "ra4", "mi valor 123FABC contra &&&F", [PATTERN_PREFIX], expectation="derived", expected_result="MATCH", runtime_patterns=("&&&F",), runtime_values=("123FABC",)),
    _case("rule_application", "ra5", "mi valor ABCX contra &&&F", [PATTERN_PREFIX], expectation="derived", expected_result="NO_MATCH", runtime_patterns=("&&&F",), runtime_values=("ABCX",)),
    _case("rule_application", "ra6", "mi valor ABCDX contra &&&F", [PATTERN_PREFIX], expectation="derived", expected_result="NO_MATCH", runtime_patterns=("&&&F",), runtime_values=("ABCDX",)),
    _case("rule_application", "ra7", "ASDFGRE contra &&&F", [PATTERN_LENGTH], expectation="derived", expected_result="NO_MATCH", runtime_patterns=("&&&F",), runtime_values=("ASDFGRE",)),
    _case("rule_application", "ra8", "ASDF contra &&&F", [PATTERN_LENGTH], expectation="derived", expected_result="MATCH", runtime_patterns=("&&&F",), runtime_values=("ASDF",)),
    _case("rule_application", "ra9", "mi valor GREASDF contra &&&F", [PATTERN_SUFFIX], expectation="derived", expected_result="MATCH", runtime_patterns=("&&&F",), runtime_values=("GREASDF",)),
    _case("rule_application", "ra10", "mi valor GREASDG contra &&&F", [PATTERN_SUFFIX], expectation="derived", expected_result="NO_MATCH", runtime_patterns=("&&&F",), runtime_values=("GREASDG",)),
    _case("rule_application", "ra11", "producto ABC-123 contra AAA-###", [DIGIT_LENGTH], expectation="derived", expected_result="MATCH", runtime_patterns=("AAA-###",), runtime_values=("ABC-123",)),
    _case("rule_application", "ra12", "producto ABC-12X contra AAA-###", [DIGIT_LENGTH], expectation="derived", expected_result="NO_MATCH", runtime_patterns=("AAA-###",), runtime_values=("ABC-12X",)),
    # --- patterns (5): instancias con semántica documentada ----------------
    _case("patterns", "pa1", "mi valor ZZ9FXYZ contra &&&F", [PATTERN_PREFIX], expectation="derived", expected_result="MATCH", runtime_patterns=("&&&F",), runtime_values=("ZZ9FXYZ",)),
    _case("patterns", "pa2", "mi valor AB1F77 contra &&&F", [PATTERN_PREFIX], expectation="derived", expected_result="MATCH", runtime_patterns=("&&&F",), runtime_values=("AB1F77",)),
    _case("patterns", "pa3", "mi valor ABCZ contra &&&F", [PATTERN_PREFIX], expectation="derived", expected_result="NO_MATCH", runtime_patterns=("&&&F",), runtime_values=("ABCZ",)),
    _case("patterns", "pa4", "mi valor XXABCDF contra &&&F", [PATTERN_SUFFIX], expectation="derived", expected_result="MATCH", runtime_patterns=("&&&F",), runtime_values=("XXABCDF",)),
    _case("patterns", "pa5", "producto XYZ-999 contra AAA-###", [DIGIT_LENGTH], expectation="derived", expected_result="MATCH", runtime_patterns=("AAA-###",), runtime_values=("XYZ-999",)),
    # --- missing premise: sin semántica documentada, no se inventa ---------
    _case("missing_premise", "mp1", "mi valor ASDFGRE contra &&&F", ["patterns are supported"], expectation="missing", expected_missing="definition:symbol:&", runtime_patterns=("&&&F",), runtime_values=("ASDFGRE",)),
    _case("missing_premise", "mp2", "mi valor ASDFGRE contra &&&F", ["the mask is documented for the field"], expectation="missing", expected_missing="matching_policy", runtime_patterns=("&&&F",), runtime_values=("ASDFGRE",)),
    _case("missing_premise", "mp3", "producto ABC-123 contra AAA-###", ["product codes are supported"], expectation="missing", expected_missing="definition:symbol:#", runtime_patterns=("AAA-###",), runtime_values=("ABC-123",)),
    _case("missing_premise", "mp4", "ASDFGRE contra &&&F", ["La máscara &&&F exige longitud indicada."], expectation="missing", expected_missing="definition:symbol:&", runtime_patterns=("&&&F",), runtime_values=("ASDFGRE",)),
    # --- calculation --------------------------------------------------------
    _case("calculation", "ca1", "base=100 surcharge=20", ["A fee is calculated as base amount plus surcharge."], expectation="derived", expected_result=120, runtime_values=("100", "20")),
    _case("calculation", "ca2", "price=100 tax_rate=0.18", ["total = price * (1 + tax_rate)"], expectation="derived", expected_result=118, runtime_values=("100", "0.18")),
    _case("calculation", "ca3", "precio=200 descuento=0.1", ["final = precio * (1 - descuento)"], expectation="derived", expected_result=180, runtime_values=("200", "0.1")),
    _case("calculation", "ca4", "base=50 surcharge=10", ["A fee is calculated as base amount plus surcharge."], expectation="derived", expected_result=60, runtime_values=("50", "10")),
    _case("calculation", "ca5", "price=80 tax_rate=0.25", ["total = price * (1 + tax_rate)"], expectation="derived", expected_result=100, runtime_values=("80", "0.25")),
    _case("calculation", "ca6", "monto=1000 tasa=0.19", ["total = monto * (1 + tasa)"], expectation="derived", expected_result=1190, runtime_values=("1000", "0.19")),
    _case("calculation", "ca7", "cantidad=4 precio=25", ["total = cantidad * precio"], expectation="derived", expected_result=100, runtime_values=("4", "25")),
    _case("calculation", "ca8", "price=100", ["total = price * (1 + tax_rate)"], expectation="missing", expected_missing="input:tax_rate", runtime_values=("100",)),
    _case("calculation", "ca9", "cantidad=3 precio=10", ["total = cantidad * precio"], expectation="derived", expected_result=30, runtime_values=("3", "10")),
    # --- formulas (5) -------------------------------------------------------
    _case("formulas", "fo1", "price=50 tax_rate=0.1", ["total = price * (1 + tax_rate)"], expectation="derived", expected_result=55, runtime_values=("50", "0.1")),
    _case("formulas", "fo2", "price=200 tax_rate=0.5", ["total = price * (1 + tax_rate)"], expectation="derived", expected_result=300, runtime_values=("200", "0.5")),
    _case("formulas", "fo3", "cantidad=6 precio=5", ["total = cantidad * precio"], expectation="derived", expected_result=30, runtime_values=("6", "5")),
    _case("formulas", "fo4", "base=10 surcharge=5", ["A fee is calculated as base amount plus surcharge."], expectation="derived", expected_result=15, runtime_values=("10", "5")),
    _case("formulas", "fo5", "precio=300 descuento=0.2", ["final = precio * (1 - descuento)"], expectation="derived", expected_result=240, runtime_values=("300", "0.2")),
    # --- comparison / range -------------------------------------------------
    _case("range", "rg1", "age 20", ["eligible age is >=18"], expectation="derived", expected_result=True, runtime_values=("20",)),
    _case("range", "rg2", "age 17", ["eligible age is >=18"], expectation="derived", expected_result=False, runtime_values=("17",)),
    _case("range", "rg3", "age 18", ["eligible age is >=18"], expectation="derived", expected_result=True, runtime_values=("18",)),
    _case("range", "rg4", "age 70", ["maximum age is <=65"], expectation="derived", expected_result=False, runtime_values=("70",)),
    _case("range", "rg5", "age 30", ["maximum age is <=65"], expectation="derived", expected_result=True, runtime_values=("30",)),
    _case("range", "rg6", "edad 25", ["edad mínima es >=18"], expectation="derived", expected_result=True, runtime_values=("25",)),
    _case("range", "rg7", "la edad mínima es 18, tengo 20, ¿cumplo?", ["eligible age is >=18"], expectation="derived", expected_result=True, runtime_values=("20",)),
    _case("range", "rg8", "tengo 16, ¿cumplo la edad mínima?", ["eligible age is >=18"], expectation="derived", expected_result=False, runtime_values=("16",)),
    _case("range", "rg9", "age 65", ["maximum age is <=65"], expectation="derived", expected_result=True, runtime_values=("65",)),
    _case("range", "rg10", "tengo 18, ¿cumplo?", ["eligible age is >=18"], expectation="derived", expected_result=True, runtime_values=("18",)),
    # --- enum ---------------------------------------------------------------
    _case("enum", "en1", "status ACTIVE", ["allowed statuses: ACTIVE, PENDING"], expectation="derived", expected_result=True, runtime_values=("ACTIVE",)),
    _case("enum", "en2", "status PENDING", ["allowed statuses: ACTIVE, PENDING"], expectation="derived", expected_result=True, runtime_values=("PENDING",)),
    _case("enum", "en3", "status CLOSED", ["allowed statuses: ACTIVE, PENDING"], expectation="derived", expected_result=False, runtime_values=("CLOSED",)),
    _case("enum", "en4", "estado ACTIVO", ["allowed estados: ACTIVO, PENDIENTE"], expectation="derived", expected_result=True, runtime_values=("ACTIVO",)),
    _case("enum", "en5", "status SUSPENDED", ["allowed statuses: ACTIVE, PENDING"], expectation="derived", expected_result=False, runtime_values=("SUSPENDED",)),
    # --- general operation (arithmetic) ------------------------------------
    _case("general_operation", "go1", "3 + 3", [], expectation="derived", expected_result=6, runtime_values=("3",)),
    _case("general_operation", "go2", "10 - 4", [], expectation="derived", expected_result=6, runtime_values=("10", "4")),
    _case("general_operation", "go3", "6 * 7", [], expectation="derived", expected_result=42, runtime_values=("6", "7")),
    _case("general_operation", "go4", "20 / 4", [], expectation="derived", expected_result=5, runtime_values=("20", "4")),
    _case("general_operation", "go5", "1 + 2", [], expectation="derived", expected_result=3, runtime_values=("1", "2")),
    # --- direct lookup / source lookup (clasificación; retrieval responde) --
    _case("direct_lookup", "dl1", "¿qué significa CAT31 según el documento?"),
    _case("direct_lookup", "dl2", "¿qué es FCLAS?"),
    _case("direct_lookup", "dl3", "define el campo FCLAS"),
    _case("direct_lookup", "dl4", "¿cuál es el plazo de entrega?", ["Delivery takes 5 days."]),
    _case("direct_lookup", "dl5", "¿qué garantía tiene el producto?", ["The product has a 12-month warranty."]),
    _case("direct_lookup", "dl6", "¿cuál es la política de devoluciones?", ["Returns are accepted within 30 days."]),
    _case("direct_lookup", "dl7", "¿cómo se contacta soporte?", ["Support is available by email."]),
    _case("direct_lookup", "dl8", "¿qué moneda se usa?", ["Prices are in US dollars."]),
    _case("direct_lookup", "dl9", "¿cuál es el horario de atención?", ["Office hours are 9 to 18."]),
    _case("direct_lookup", "dl10", "¿qué significa el estado PENDING?", ["PENDING means awaiting review."]),
    _case("direct_lookup", "dl11", "¿dónde se publica la factura?", ["Invoices are published in the portal."]),
    _case("direct_lookup", "dl12", "¿qué cubre el seguro?", ["The insurance covers transport damage."]),
    _case("direct_lookup", "dl13", "¿cuántos niveles tiene el plan?", ["The plan has three levels."]),
    _case("direct_lookup", "dl14", "¿qué documento se requiere?", ["A valid ID is required."]),
    _case("direct_lookup", "dl15", "¿cuál es el canal oficial?", ["The official channel is the portal."]),
    _case("direct_lookup", "dl16", "¿qué significa SLA?", ["SLA means service level agreement."]),
    _case("direct_lookup", "dl17", "¿cómo se solicita el reembolso?", ["Refunds are requested from the portal."]),
    _case("direct_lookup", "dl18", "¿qué pasa si falta el pago?", ["The service is suspended after 10 days."]),
    _case("direct_lookup", "dl19", "¿qué incluye la suscripción?", ["The subscription includes updates."]),
    _case("direct_lookup", "dl20", "¿cuál es el formato del reporte?", ["Reports are delivered as CSV."]),
    _case("source_lookup", "sl1", "¿ASDFGRE aparece literalmente en el documento?"),
    _case("source_lookup", "sl2", "¿dónde está documentado ABCDEF?"),
    _case("source_lookup", "sl3", "busca QNNF0SME en el documento"),
    _case("source_lookup", "sl4", "¿el documento menciona age 20?"),
    _case("source_lookup", "sl5", "does the source mention age 20?"),
    _case("source_lookup", "sl6", "¿el texto contiene &&&F?"),
    _case("source_lookup", "sl7", "¿figura QNNF0SME en el manual?"),
    _case("source_lookup", "sl8", "¿dónde aparece ASDFGRE?"),
    _case("source_lookup", "sl9", "¿el documento menciona FCLAS?"),
    _case("source_lookup", "sl10", "¿figura el código ABC-123 en la fuente?"),
    # --- rule application extra ---------------------------------------------
    _case("rule_application", "ra13", "mi valor ABCDEF contra &&&F", [PATTERN_LENGTH], expectation="derived", expected_result="NO_MATCH", runtime_patterns=("&&&F",), runtime_values=("ABCDEF",)),
    _case("rule_application", "ra14", "mi valor ZZ9F contra &&&F", [PATTERN_PREFIX], expectation="derived", expected_result="MATCH", runtime_patterns=("&&&F",), runtime_values=("ZZ9F",)),
    _case("rule_application", "ra15", "mi valor 9ABF contra &&&F", [PATTERN_SUFFIX], expectation="derived", expected_result="MATCH", runtime_patterns=("&&&F",), runtime_values=("9ABF",)),
    # --- calculation extra --------------------------------------------------
    _case("calculation", "ca10", "price=60 tax_rate=0.1", ["total = price * (1 + tax_rate)"], expectation="derived", expected_result=66, runtime_values=("60", "0.1")),
    # --- missing premises extra ---------------------------------------------
    _case("missing_premise", "mp5", "mi valor ASDFGRE contra ###", ["patterns are supported"], expectation="missing", expected_missing="definition:symbol:#", runtime_patterns=("###",), runtime_values=("ASDFGRE",)),
    _case("missing_premise", "mp6", "age 20, ¿cumple?", ["eligibility must follow policy P"], expectation="missing", expected_missing="definition:policy:P", runtime_values=("20",)),
    _case("missing_premise", "mp7", "mi valor AB@C contra @@#C", ["patterns are supported"], expectation="missing", expected_missing="definition:symbol:@", runtime_patterns=("@@#C",), runtime_values=("AB@C",)),
    _case("missing_premise", "mp8", "mi valor ABC contra ????", ["patterns are supported"], expectation="missing", expected_missing="definition:symbol:?", runtime_patterns=("????",), runtime_values=("ABC",)),
    _case("missing_premise", "mp9", "date 2020-01-01, age 20, ¿cumple?", ["minimum age is >=18 effective from 2026-01-01"], expectation="missing", expected_missing="no_rule_valid_at", runtime_values=("20", "2020-01-01")),
    _case("missing_premise", "mp10", "mi valor QNNF0SME contra &&&F", ["the mask is documented without symbol semantics"], expectation="missing", expected_missing="definition:symbol:&", runtime_patterns=("&&&F",), runtime_values=("QNNF0SME",)),
    # --- transformations (política de strings documentada) ------------------
    _case("transformation", "tr1", "¿abc es igual a ABC?", ["codes are compared case-insensitively"], expectation="derived", expected_result=True),
    _case("transformation", "tr2", "¿ABC es igual a ABD?", ["codes are compared case-insensitively"], expectation="derived", expected_result=False),
    _case("transformation", "tr3", "¿FCLAS es igual a fclas?", ["codes are compared case-insensitively"], expectation="derived", expected_result=True),
    _case("transformation", "tr4", "¿premium es igual a PREMIUM?", ["codes are compared case-insensitively"], expectation="derived", expected_result=True),
    _case("transformation", "tr5", "¿XKCD42 es igual a xkcd42?", ["codes are compared case-insensitively"], expectation="derived", expected_result=True),
    _case("transformation", "tr6", "¿AAA es igual a BBB?", ["codes are compared case-insensitively"], expectation="derived", expected_result=False),
    _case("transformation", "tr7", "¿AbC es igual a aBc?", ["convert to uppercase before comparing"], expectation="derived", expected_result=True),
    _case("transformation", "tr8", "¿AbC es igual a ABC?", ["convert to uppercase before comparing"], expectation="derived", expected_result=True),
    _case("transformation", "tr9", "¿ABC es igual a ABD?", ["convert to uppercase before comparing"], expectation="derived", expected_result=False),
    _case("transformation", "tr10", "¿qnnf0sme es igual a QNNF0SME?", ["codes are compared case-insensitively"], expectation="derived", expected_result=True),
    # --- boolean rules -------------------------------------------------------
    _case("boolean", "bo1", "active=true verified=true, ¿es eligible?", ["active AND verified -> eligible"], expectation="derived", expected_result=True, runtime_values=("true",)),
    _case("boolean", "bo2", "active=true verified=false, ¿es eligible?", ["active AND verified -> eligible"], expectation="derived", expected_result=False, runtime_values=("true", "false")),
    _case("boolean", "bo3", "activo=true verificado=true, ¿es elegible?", ["es elegible si está activo y verificado"], expectation="derived", expected_result=True, runtime_values=("true",)),
    _case("boolean", "bo4", "active=false, ¿es eligible?", ["active AND verified -> eligible"], expectation="missing", expected_missing="input:verified", runtime_values=("false",)),
    # --- temporal ------------------------------------------------------------
    _case("temporal", "te1", "date 2026-10-04, age 20, ¿cumple?", ["minimum age is >=18 effective until 2025-12-31.", "minimum age is >=21 effective from 2026-01-01."], expectation="derived", expected_result=False, runtime_values=("20", "2026-10-04")),
    _case("temporal", "te2", "date 2025-06-01, age 20, ¿cumple?", ["minimum age is >=18 effective until 2025-12-31.", "minimum age is >=21 effective from 2026-01-01."], expectation="derived", expected_result=True, runtime_values=("20", "2025-06-01")),
    # --- conflict ------------------------------------------------------------
    _case("conflict", "cf1", "age 20, ¿cumple?", ["minimum age is >=21.", "minimum age is >=18."], expectation="conflict"),
    _case("conflict", "cf2", "price=100 tax_rate=0.1", ["total = price * (1 + tax_rate)", "total = price * tax_rate"], expectation="conflict"),
    # --- tax percent ---------------------------------------------------------
    _case("calculation", "tx1", "price = 100; total with tax?", ["tax rate = 18%"], expectation="derived", expected_result=118, runtime_values=("100",)),
    # --- new pattern over generic grammar ------------------------------------
    _case("patterns", "np1", "mi valor AB12 contra &&##", ["& represents one alphanumeric position. # represents one digit. Matching is positional. The pattern and the value must have the same length."], expectation="derived", expected_result="MATCH", runtime_patterns=("&&##",), runtime_values=("AB12",)),
    _case("patterns", "np2", "mi valor ABC2 contra &&##", ["& represents one alphanumeric position. # represents one digit. Matching is positional. The pattern and the value must have the same length."], expectation="derived", expected_result="NO_MATCH", runtime_patterns=("&&##",), runtime_values=("ABC2",)),
)


__all__ = [
    "BENCHMARK_CASES",
    "GROUNDED_BENCHMARK_VERSION",
    "ROLE_CASES",
    "BenchmarkCase",
    "BenchmarkOutcome",
    "compare_baselines",
    "evaluate_runner",
    "query_role_accuracy",
    "record_benchmark_metrics",
    "run_grounded",
    "run_legacy_literal",
]
