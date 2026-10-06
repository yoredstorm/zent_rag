# PDF Parser Knowledge Benchmark (P0)

> La métrica principal no es parsing: es cuánto conocimiento correcto, relacionado, recuperable y ejecutable adquiere ZENT del PDF.

## Tabla de decisión

| Metric | pdfplumber | opendataloader | winner |
| --- | ---: | ---: | --- |
| **STRUCTURAL QUALITY** |  |  | |
| Text Preservation Recall | 0.9846 | 0.9846 | tie |
| Reading Order Accuracy | 0.7808 | 0.7808 | tie |
| Heading Accuracy | 0.4479 | 0.6042 | opendataloader |
| Section Hierarchy Accuracy | 1.0000 | 1.0000 | tie |
| Table Detection Recall | 1.0000 | 1.0000 | tie |
| Table Structure Accuracy | 1.0000 | 1.0000 | tie |
| Symbol Preservation | 1.0000 | 1.0000 | tie |
| Special Character Preservation | 1.0000 | 1.0000 | tie |
| Cross-page Continuity | 0.5000 | 0.5000 | tie |
| Duplicate Rate | 0.3077 | 0.0000 | opendataloader |
| Header/Footer Contamination | 0.3077 | 0.0000 | opendataloader |
| Broken Sentence Rate | 0.0769 | 0.0769 | tie |
| **SEMANTIC QUALITY** |  |  | |
| Semantic Unit Recall | 0.9269 | 0.9269 | tie |
| Semantic Unit Precision | 0.9532 | 1.0000 | opendataloader |
| Fragmentation Rate | 0.0000 | 0.0000 | tie |
| Incorrect Merge Rate | 0.3961 | 0.4630 | pdfplumber |
| Cross-page Stitch Accuracy | 0.0000 | 0.0000 | tie |
| Definition Detection Recall | 1.0000 | 1.0000 | tie |
| Rule Candidate Recall | 0.9722 | 0.9722 | tie |
| Exception Detection Recall | 1.0000 | 1.0000 | tie |
| Table Semantic Preservation | 1.0000 | 1.0000 | tie |
| **KNOWLEDGE QUALITY** |  |  | |
| Definition Recall | 0.2963 | 0.2963 | tie |
| Fact Recall | 0.0000 | 0.0000 | tie |
| Rule Recall | 0.9091 | 0.9091 | tie |
| Relationship Recall | 0.0000 | 0.0000 | tie |
| Exception Recall | 0.0000 | 0.6667 | opendataloader |
| Enumeration Recall | 1.0000 | 1.0000 | tie |
| Formula Recall | 0.5000 | 0.0000 | pdfplumber |
| Table Mapping Recall | 1.0000 | 1.0000 | tie |
| Knowledge Precision | 0.6247 | 0.7542 | opendataloader |
| **CANONICAL RULE QUALITY** |  |  | |
| CanonicalRule Recall | 0.8889 | 0.8611 | pdfplumber |
| CanonicalRule Precision | 0.8236 | 0.9167 | opendataloader |
| SUPPORTED Rate | 0.8750 | 0.8472 | pdfplumber |
| EXECUTABLE Rate | 0.0278 | 0.0278 | tie |
| UNKNOWN Rate | 0.0000 | 0.0000 | tie |
| PARTIALLY_SUPPORTED Rate | 0.1250 | 0.1528 | pdfplumber |
| CONFLICTING Rate | 0.0000 | 0.0000 | tie |
| False Rule Rate | 0.1764 | 0.0833 | opendataloader |
| Missing Premise Rate | 0.9722 | 0.9722 | tie |
| Property Provenance Completeness | 1.0000 | 1.0000 | tie |
| **PREMISE COVERAGE** |  |  | |
| Premise Coverage Recall | 0.7188 | 0.7188 | tie |
| **RETRIEVAL** |  |  | |
| Recall@K | 0.3889 | 0.4722 | opendataloader |
| MRR | 0.3096 | 0.3517 | opendataloader |
| Rule Retrieval Recall | 0.3889 | 0.4722 | opendataloader |
| Premise Retrieval Recall | 0.0000 | 0.0000 | tie |
| Irrelevant Evidence Ratio | 0.8961 | 0.8498 | opendataloader |
| Source-local Success | 1.0000 | 1.0000 | tie |
| Cross-page Evidence Recovery | 0.0000 | 0.0000 | tie |
| **ANSWERABILITY** |  |  | |
| Answerable With Evidence Rate | 0.9744 | 0.9167 | pdfplumber |
| False Abstention Rate | 0.0449 | 0.0833 | pdfplumber |
| Unsupported Hallucination Rate | 0.0000 | 0.0000 | tie |
| **DECISION ACCURACY** |  |  | |
| Answer Accuracy | 1.0000 | 1.0000 | tie |
| Deterministic Decision Rate | 0.0000 | 0.0000 | tie |
| **CONSISTENCY** |  |  | |
| Consistency Rate | 1.0000 | n/a | - |
| **PERFORMANCE** |  |  | |
| Seconds per Page | 0.0689 | 1.1970 | pdfplumber |

## Scores

- **pdfplumber**: KCS=0.7096 (clamped 0.7096), ZentPdfKnowledgeScore=0.7116, performance_viable=True
- **opendataloader**: KCS=0.7493 (clamped 0.7493), ZentPdfKnowledgeScore=0.7617, performance_viable=True

## Recomendación

**Verdict: `D_NEED_MORE_DATA`**

| Criterio | Cumple |
| --- | --- |
| knowledge_precision_not_reduced | sí |
| rule_precision_not_reduced | sí |
| structural_fidelity_maintained | sí |
| semantic_unit_quality_increased | sí |
| canonical_rule_recall_increased | no |
| premise_coverage_not_reduced | sí |
| false_abstentions_reduced | no |
| hallucinations_not_increased | sí |
| consistency_maintained | no |
| provenance_not_worse | sí |

## Documentos

| Documento | letter | pdfplumber s | ODL s | ODL rules | pdfplumber rules | KCS p | KCS odl |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| manual_tecnico_grande | A | 1.9713 | 7.3336 | 43 | 24 | 0.7669 | 0.8096 |
| manual_tablas | B | 0.3309 | 2.7616 | 0 | 0 | 0.375 | 0.375 |
| contrato | C | 0.2368 | 2.9792 | 3 | 5 | 0.6505 | 0.7135 |
| procedimiento | D | 0.1369 | 2.3827 | 2 | 3 | 0.6444 | 0.8354 |
| politica | E | 0.1282 | 2.4838 | 3 | 4 | 0.6938 | 0.8833 |
| multicolumna | F | 0.1344 | 2.6476 | 3 | 4 | 0.8783 | 0.8833 |
| tagged | G | 0.0734 | 4.2814 | 2 | 2 | 0.725 | 0.75 |
| fixed_width | H | 0.1094 | 2.7477 | 2 | 3 | 0.8021 | 0.7438 |
| distribuidas | I | 0.1502 | 2.8921 | 2 | 2 | 0.1417 | 0.1417 |
| ruido | J | 0.1886 | 2.5876 | 3 | 6 | 0.8125 | 0.8125 |
| formulas | L | 0.0999 | 2.5527 | 1 | 1 | 0.6667 | 0.6667 |
| atpco | ATPCO | 0.1754 | 3.2738 | 1 | 3 | 0.5806 | 0.5708 |
| manual_tecnico_grande#large | A | 14.6528 | 7.6817 | 235 | 120 | 0.7499 | 0.8093 |

## Pendientes

- escaneado: Pendiente: requiere hybrid/OCR. No se simula.