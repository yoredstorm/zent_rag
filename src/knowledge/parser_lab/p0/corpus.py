# =============================================================================
# P0 — Corpus controlado + Golden Knowledge Sets
# =============================================================================
# Corpus A-L del brief §2. Cada documento se genera determinísticamente
# (sin binarios en git) y declara su Golden Set: objetos de conocimiento
# esperados con tipo semántico, páginas, sección, propiedades, premisas
# requeridas y queries ejecutables. El Golden Set es la verdad del benchmark.
#
# K (escaneado) queda pendiente para la fase Hybrid/OCR: el benchmark lo
# reporta como skipped, no lo simula.
# =============================================================================
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.knowledge.parser_lab.p0.corpus_build import PdfCanvas, tagged_pdf


def golden_object(
    object_id: str,
    semantic_type: str,
    meaning: str,
    *,
    pages: list[int],
    section: str | None = None,
    equivalents: list[str] | None = None,
    properties: dict[str, Any] | None = None,
    relations: list[str] | None = None,
    executable: bool = False,
    required_premises: list[str] | None = None,
    allowed_formulations: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": object_id,
        "semantic_type": semantic_type,
        "meaning": meaning,
        "pages": pages,
        "section": section,
        "equivalents": equivalents or [],
        "properties": properties or {},
        "relations": relations or [],
        "executable": executable,
        "required_premises": required_premises or [],
        "allowed_formulations": allowed_formulations or [],
    }


def golden_query(
    query_id: str,
    kind: str,
    question: str,
    *,
    expected_status: str | None = None,
    values: dict[str, Any] | None = None,
    objects: list[str] | None = None,
    expected_answer_contains: list[str] | None = None,
    executable: bool = False,
    cross_page: bool = False,
    answerable: bool = True,
) -> dict[str, Any]:
    return {
        "id": query_id,
        "kind": kind,
        "question": question,
        "expected_status": expected_status,
        "values": values,
        "objects": objects or [],
        "expected_answer_contains": expected_answer_contains or [],
        "executable": executable,
        "cross_page": cross_page,
        "answerable": answerable,
    }


def _golden(
    *,
    anchor_terms: list[str],
    objects: list[dict[str, Any]],
    queries: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "anchor_terms": anchor_terms,
        "objects": objects,
        "queries": queries,
    }


# ---------------------------------------------------------------------------
# A. Manual técnico grande (páginas configurables: 24 por defecto, 300 para §23)
# ---------------------------------------------------------------------------


def build_manual_grande(pages: int = 24) -> bytes:
    canvas = PdfCanvas()
    for page_index in range(1, pages + 1):
        if page_index > 1:
            canvas.new_page()
        canvas.text(72, 730, f"Manual Técnico de Operaciones — Módulo {page_index}", size=15, bold=True)
        canvas.text(72, 700, f"{page_index}. Especificaciones del módulo {page_index}", size=13, bold=True)
        canvas.text(
            72,
            670,
            f"PA{page_index} - torque nominal del módulo {page_index}.",
            size=11,
        )
        canvas.text(
            72,
            648,
            f"El operador must verificar que PA{page_index} no exceda {page_index * 10} Nm antes de arrancar.",
            size=11,
        )
        canvas.text(
            72,
            620,
            f"margen de seguridad - 15 por ciento del torque nominal del módulo {page_index}.",
            size=11,
        )
        if page_index % 4 == 0:
            canvas.table(
                72,
                580,
                [150.0, 220.0, 100.0],
                [
                    ["Código", "Descripción", "Máximo"],
                    [f"T{page_index}01", f"Componente del módulo {page_index}", f"{page_index * 10} Nm"],
                    [f"T{page_index}02", f"Sensor del módulo {page_index}", f"{page_index * 5} Nm"],
                ],
            )
    return canvas.build()


def golden_manual_grande(pages: int = 24) -> dict[str, Any]:
    objects: list[dict[str, Any]] = []
    queries: list[dict[str, Any]] = []
    for page_index in range(1, pages + 1):
        section = f"{page_index}. Especificaciones del módulo {page_index}"
        objects.append(
            golden_object(
                f"def-pa{page_index}",
                "definition",
                f"PA{page_index} es el torque nominal del módulo {page_index}",
                pages=[page_index],
                section=section,
                equivalents=[f"PA{page_index}", "torque nominal"],
                properties={"term": f"PA{page_index}", "value": "torque nominal"},
            )
        )
        objects.append(
            golden_object(
                f"rule-pa{page_index}",
                "rule",
                f"PA{page_index} no debe exceder {page_index * 10} Nm antes de arrancar",
                pages=[page_index],
                section=section,
                equivalents=[f"PA{page_index}", f"{page_index * 10} Nm", "must"],
                properties={"subject": f"PA{page_index}", "limit": f"{page_index * 10} Nm"},
            )
        )
        if page_index % 4 == 0:
            objects.append(
                golden_object(
                    f"table-m{page_index}",
                    "table_mapping",
                    f"tabla de componentes del módulo {page_index}",
                    pages=[page_index],
                    section=section,
                    equivalents=[
                        f"T{page_index}01",
                        f"Componente del módulo {page_index}",
                        f"T{page_index}02",
                    ],
                )
            )
    for page_index in range(1, min(pages, 3) + 1):
        queries.append(
            golden_query(
                f"q-def-{page_index}",
                "definition",
                f"¿Qué es PA{page_index}?",
                objects=[f"def-pa{page_index}"],
                expected_answer_contains=["torque nominal"],
            )
        )
        queries.append(
            golden_query(
                f"q-rule-{page_index}",
                "validation",
                f"¿Qué límite tiene PA{page_index}?",
                objects=[f"rule-pa{page_index}"],
                expected_answer_contains=[f"{page_index * 10} Nm"],
            )
        )
    return _golden(
        anchor_terms=["PA", "torque", "Nm", "módulo", "margen de seguridad"],
        objects=objects,
        queries=queries,
    )


# ---------------------------------------------------------------------------
# B. Manual con muchas tablas
# ---------------------------------------------------------------------------


def build_manual_tablas(pages: int = 6) -> bytes:
    canvas = PdfCanvas()
    for page_index in range(1, pages + 1):
        if page_index > 1:
            canvas.new_page()
        canvas.text(72, 730, "Catálogo Técnico de Repuestos", size=15, bold=True)
        canvas.text(72, 700, f"{page_index}. Tabla de componentes", size=13, bold=True)
        canvas.table(
            72,
            660,
            [110.0, 240.0, 120.0],
            [
                ["Código", "Descripción", "Máximo"],
                [f"T{page_index}01", f"Componente {page_index}A", f"{page_index}0 Nm"],
                [f"T{page_index}02", f"Componente {page_index}B", f"{page_index * 15} Nm"],
                [f"T{page_index}03", f"Componente {page_index}C", f"{page_index * 20} Nm"],
            ],
        )
    return canvas.build()


def golden_manual_tablas(pages: int = 6) -> dict[str, Any]:
    objects = []
    queries = []
    for page_index in range(1, pages + 1):
        objects.append(
            golden_object(
                f"table-cat{page_index}",
                "table_mapping",
                f"códigos T{page_index}01..03 con descripción y máximo",
                pages=[page_index],
                section=f"{page_index}. Tabla de componentes",
                equivalents=[
                    f"T{page_index}01",
                    f"Componente {page_index}A",
                    f"T{page_index}02",
                    f"Componente {page_index}B",
                    f"T{page_index}03",
                ],
                properties={"headers": "Código Descripción Máximo"},
            )
        )
    for page_index in (2, 3):
        queries.append(
            golden_query(
                f"q-table-{page_index}",
                "table_lookup",
                f"¿Cuál es el máximo del código T{page_index}02?",
                objects=[f"table-cat{page_index}"],
                expected_answer_contains=[f"{page_index * 15} Nm"],
            )
        )
    return _golden(
        anchor_terms=["T", "Componente", "Máximo", "Nm"],
        objects=objects,
        queries=queries,
    )


# ---------------------------------------------------------------------------
# C. Contrato
# ---------------------------------------------------------------------------


def build_contrato(pages: int = 3) -> bytes:
    canvas = PdfCanvas()
    canvas.text(72, 730, "Contrato de Servicios Profesionales", size=16, bold=True)
    canvas.text(72, 700, "7. Penalizaciones", size=13, bold=True)
    canvas.text(
        72,
        670,
        "El retraso superior a 30 días must generar una penalización del 2% del importe anual.",
        size=11,
    )
    canvas.text(
        72,
        648,
        "Salvo fuerza mayor, la penalización no aplica y el plazo se extiende.",
        size=11,
    )
    canvas.text(
        72,
        626,
        "Vigencia desde 2026-01-01 hasta 2026-12-31.",
        size=11,
    )
    canvas.text(72, 596, "penalizacion = 0.02 * importe_anual", size=12)
    canvas.text(
        72,
        566,
        "importe anual - suma de las facturas del período.",
        size=11,
    )
    canvas.new_page()
    canvas.text(72, 730, "8. Obligaciones de las partes", size=13, bold=True)
    canvas.text(
        72,
        700,
        "El proveedor must entregar el informe mensual dentro de los 5 días hábiles.",
        size=11,
    )
    canvas.text(
        72,
        678,
        "El cliente must aprobar el informe o must presentar observaciones en 10 días.",
        size=11,
    )
    canvas.new_page()
    canvas.text(72, 730, "9. Terminación", size=13, bold=True)
    canvas.text(
        72,
        700,
        "Cualquiera de las partes must not terminar el contrato sin preaviso de 30 días.",
        size=11,
    )
    return canvas.build()


def golden_contrato(pages: int = 3) -> dict[str, Any]:
    objects = [
        golden_object(
            "rule-penalizacion",
            "rule",
            "retraso > 30 días genera penalización del 2% del importe anual",
            pages=[1],
            section="7. Penalizaciones",
            equivalents=["retraso", "30 días", "penalización", "2%", "importe anual"],
            properties={"subject": "retraso", "consequence": "penalización 2%"},
            relations=["penalizacion -> importe_anual"],
            required_premises=["condition.present"],
        ),
        golden_object(
            "exc-fuerza-mayor",
            "exception",
            "fuerza mayor exceptúa la penalización",
            pages=[1],
            section="7. Penalizaciones",
            equivalents=["fuerza mayor", "no aplica"],
        ),
        golden_object(
            "temp-vigencia",
            "temporal_constraint",
            "vigencia 2026-01-01 a 2026-12-31",
            pages=[1],
            section="7. Penalizaciones",
            equivalents=["2026-01-01", "2026-12-31", "Vigencia"],
        ),
        golden_object(
            "formula-penalizacion",
            "formula",
            "penalizacion = 0.02 * importe_anual",
            pages=[1],
            section="7. Penalizaciones",
            equivalents=["penalizacion", "0.02", "importe_anual"],
            executable=True,
            required_premises=["formula.expression"],
        ),
        golden_object(
            "def-importe-anual",
            "definition",
            "importe anual es la suma de las facturas del período",
            pages=[1],
            section="7. Penalizaciones",
            equivalents=["importe anual", "suma de las facturas"],
            properties={"term": "importe anual", "value": "suma de las facturas"},
        ),
        golden_object(
            "fact-penalizacion-pct",
            "fact",
            "la penalización es del 2% del importe anual",
            pages=[1],
            section="7. Penalizaciones",
            equivalents=["penalización", "2%", "importe anual"],
            properties={"predicate": "porcentaje", "value": "2%"},
        ),
        golden_object(
            "rule-informe-mensual",
            "rule",
            "proveedor entrega informe mensual en 5 días hábiles",
            pages=[2],
            section="8. Obligaciones de las partes",
            equivalents=["informe mensual", "5 días hábiles", "must entregar"],
        ),
        golden_object(
            "rule-preaviso",
            "rule",
            "terminación requiere preaviso de 30 días",
            pages=[3],
            section="9. Terminación",
            equivalents=["preaviso", "30 días", "must not terminar"],
        ),
    ]
    queries = [
        golden_query(
            "q-def-importe",
            "definition",
            "¿Qué es el importe anual?",
            objects=["def-importe-anual"],
            expected_answer_contains=["facturas"],
        ),
        golden_query(
            "q-calc-penalizacion",
            "calculation",
            "¿Cuál es la penalización para un importe anual de 1000?",
            objects=["formula-penalizacion"],
            values={"importe_anual": 1000},
            expected_status="MATCH",
            executable=True,
        ),
        golden_query(
            "q-exception",
            "exception",
            "¿Cuándo no aplica la penalización?",
            objects=["exc-fuerza-mayor"],
            expected_answer_contains=["fuerza mayor"],
        ),
        golden_query(
            "q-multi-hop",
            "multi_hop",
            "¿Qué obligación de informe tiene el proveedor y en qué plazo?",
            objects=["rule-informe-mensual"],
            expected_answer_contains=["informe mensual", "5 días"],
        ),
    ]
    return _golden(
        anchor_terms=["penalización", "importe anual", "informe mensual", "preaviso", "fuerza mayor"],
        objects=objects,
        queries=queries,
    )


# ---------------------------------------------------------------------------
# D. Procedimiento
# ---------------------------------------------------------------------------


def build_procedimiento(pages: int = 2) -> bytes:
    canvas = PdfCanvas()
    canvas.text(72, 730, "Procedimiento de Alta de Cliente", size=16, bold=True)
    canvas.text(72, 700, "1. Pasos", size=13, bold=True)
    for index, step in enumerate(
        [
            "Validar la identidad del cliente con documento oficial vigente.",
            "Registrar al cliente en el sistema con el estado inicial nuevo.",
            "Notificar al área comercial en un plazo de 24 horas.",
        ],
        start=1,
    ):
        canvas.text(72, 670 - index * 22, f"{index}. {step}", size=11)
    canvas.text(
        72,
        580,
        "El analista must not registrar clientes sin identidad validada.",
        size=11,
    )
    canvas.text(
        72,
        552,
        "Estados permitidos del cliente: nuevo, activo, suspendido, cerrado.",
        size=11,
    )
    canvas.new_page()
    canvas.text(72, 730, "2. Escalamiento", size=13, bold=True)
    canvas.text(
        72,
        700,
        "Si el cliente no completa la validación en 48 horas, el caso must escalar al supervisor.",
        size=11,
    )
    return canvas.build()


def golden_procedimiento(pages: int = 2) -> dict[str, Any]:
    objects = [
        golden_object(
            "enum-estados",
            "enumeration",
            "estados permitidos: nuevo, activo, suspendido, cerrado",
            pages=[1],
            section="1. Pasos",
            equivalents=["nuevo", "activo", "suspendido", "cerrado"],
            properties={"values": "nuevo activo suspendido cerrado"},
        ),
        golden_object(
            "rule-identidad",
            "rule",
            "no registrar clientes sin identidad validada",
            pages=[1],
            section="1. Pasos",
            equivalents=["identidad validada", "must not registrar"],
        ),
        golden_object(
            "rule-escalamiento",
            "rule",
            "validación > 48 horas escala al supervisor",
            pages=[2],
            section="2. Escalamiento",
            equivalents=["48 horas", "escalar al supervisor"],
            required_premises=["condition.present"],
        ),
        golden_object(
            "def-estado-inicial",
            "definition",
            "estado inicial del cliente registrado es nuevo",
            pages=[1],
            section="1. Pasos",
            equivalents=["estado inicial", "nuevo"],
        ),
    ]
    queries = [
        golden_query(
            "q-enum",
            "lookup",
            "¿Qué estados están permitidos para el cliente?",
            objects=["enum-estados"],
            expected_answer_contains=["nuevo", "activo", "suspendido"],
        ),
        golden_query(
            "q-procedure",
            "validation",
            "¿Qué debe hacer el analista antes de registrar?",
            objects=["rule-identidad"],
            expected_answer_contains=["identidad"],
        ),
    ]
    return _golden(
        anchor_terms=["cliente", "identidad", "estado", "escalar", "supervisor"],
        objects=objects,
        queries=queries,
    )


# ---------------------------------------------------------------------------
# E. Política empresarial
# ---------------------------------------------------------------------------


def build_politica(pages: int = 3) -> bytes:
    canvas = PdfCanvas()
    canvas.text(72, 730, "Política de Aprobación de Gastos", size=16, bold=True)
    canvas.text(72, 700, "1. Reglas generales", size=13, bold=True)
    canvas.text(
        72,
        670,
        "El área financiera must aprobar todo gasto superior a 5000 EUR.",
        size=11,
    )
    canvas.text(
        72,
        648,
        "Si el gasto supera el umbral de aprobación, se requiere firma del director.",
        size=11,
    )
    canvas.text(
        72,
        626,
        "Quedan exceptuados los gastos de nómina y los impuestos.",
        size=11,
    )
    canvas.text(
        72,
        604,
        "umbral de aprobación - 5000 EUR.",
        size=11,
    )
    canvas.text(
        72,
        582,
        "La política de gastos references al procedimiento de compras.",
        size=11,
    )
    canvas.new_page()
    canvas.text(72, 730, "2. Responsabilidades", size=13, bold=True)
    canvas.text(
        72,
        700,
        "El director financiero must revisar la política cada 12 meses.",
        size=11,
    )
    canvas.new_page()
    canvas.text(72, 730, "3. Excepciones", size=13, bold=True)
    canvas.text(
        72,
        700,
        "El comité must autorizar excepciones por escrito.",
        size=11,
    )
    return canvas.build()


def golden_politica(pages: int = 3) -> dict[str, Any]:
    objects = [
        golden_object(
            "rule-aprobacion",
            "rule",
            "gastos > 5000 EUR requieren aprobación del área financiera",
            pages=[1],
            section="1. Reglas generales",
            equivalents=["5000 EUR", "aprobar", "gasto superior"],
            properties={"subject": "gasto", "threshold": "5000 EUR"},
            required_premises=["condition.present"],
        ),
        golden_object(
            "def-umbral",
            "definition",
            "umbral de aprobación es 5000 EUR",
            pages=[1],
            section="1. Reglas generales",
            equivalents=["umbral de aprobación", "5000 EUR"],
            properties={"term": "umbral de aprobación", "value": "5000 EUR"},
        ),
        golden_object(
            "exc-nomina",
            "exception",
            "nómina e impuestos exceptuados",
            pages=[1],
            section="1. Reglas generales",
            equivalents=["exceptuados", "nómina", "impuestos"],
        ),
        golden_object(
            "rel-politica-compras",
            "relationship",
            "política de gastos references procedimiento de compras",
            pages=[1],
            section="1. Reglas generales",
            equivalents=["política de gastos", "procedimiento de compras"],
        ),
        golden_object(
            "rule-revision",
            "rule",
            "el director financiero revisa la política cada 12 meses",
            pages=[2],
            section="2. Responsabilidades",
            equivalents=["director financiero", "12 meses", "revisar"],
        ),
        golden_object(
            "rule-excepciones",
            "rule",
            "el comité autoriza excepciones por escrito",
            pages=[3],
            section="3. Excepciones",
            equivalents=["comité", "excepciones", "por escrito"],
        ),
    ]
    queries = [
        golden_query(
            "q-threshold",
            "definition",
            "¿Cuál es el umbral de aprobación?",
            objects=["def-umbral"],
            expected_answer_contains=["5000 EUR"],
        ),
        golden_query(
            "q-apply-threshold",
            "apply_rule",
            "¿Un gasto de 6000 EUR requiere aprobación?",
            objects=["rule-aprobacion"],
            expected_answer_contains=["aprobación"],
        ),
        golden_query(
            "q-exception",
            "exception",
            "¿Qué gastos quedan exceptuados?",
            objects=["exc-nomina"],
            expected_answer_contains=["nómina"],
        ),
        golden_query(
            "q-relationship",
            "relationship",
            "¿A qué procedimiento referencia la política de gastos?",
            objects=["rel-politica-compras"],
            expected_answer_contains=["compras"],
        ),
    ]
    return _golden(
        anchor_terms=["gasto", "aprobación", "umbral", "nómina", "director financiero"],
        objects=objects,
        queries=queries,
    )


# ---------------------------------------------------------------------------
# F. Multi-columna
# ---------------------------------------------------------------------------


def build_multicolumna(pages: int = 2) -> bytes:
    canvas = PdfCanvas()
    canvas.text(72, 730, "Informe de Indicadores Operativos", size=16, bold=True)
    canvas.text(72, 700, "KPI-A - promedio de ventas diarias.", size=11)
    canvas.text(320, 700, "El responsable must revisar KPI-A cada semana.", size=11)
    canvas.text(72, 676, "KPI-B - tasa de conversión mensual.", size=11)
    canvas.text(320, 676, "El equipo must publicar KPI-B en el tablero antes del día 5.", size=11)
    canvas.new_page()
    canvas.text(72, 730, "desviación - diferencia entre KPI-A y su meta.", size=11)
    canvas.text(320, 730, "Si la desviación supera el 10%, el responsable must escalar el caso.", size=11)
    return canvas.build()


def golden_multicolumna(pages: int = 2) -> dict[str, Any]:
    objects = [
        golden_object(
            "def-kpi-a",
            "definition",
            "KPI-A es el promedio de ventas diarias",
            pages=[1],
            equivalents=["KPI-A", "promedio de ventas diarias"],
            properties={"term": "KPI-A", "value": "promedio de ventas diarias"},
        ),
        golden_object(
            "def-kpi-b",
            "definition",
            "KPI-B es la tasa de conversión mensual",
            pages=[1],
            equivalents=["KPI-B", "tasa de conversión mensual"],
            properties={"term": "KPI-B", "value": "tasa de conversión mensual"},
        ),
        golden_object(
            "rule-kpi-a",
            "rule",
            "el responsable revisa KPI-A cada semana",
            pages=[1],
            equivalents=["responsable", "KPI-A", "cada semana"],
        ),
        golden_object(
            "rule-kpi-b",
            "rule",
            "el equipo publica KPI-B antes del día 5",
            pages=[1],
            equivalents=["equipo", "KPI-B", "día 5"],
        ),
        golden_object(
            "def-desviacion",
            "definition",
            "desviación es la diferencia entre KPI-A y su meta",
            pages=[2],
            equivalents=["desviación", "KPI-A", "meta"],
        ),
        golden_object(
            "rule-desviacion",
            "rule",
            "desviación > 10% escala el caso",
            pages=[2],
            equivalents=["desviación", "10%", "escalar"],
            required_premises=["condition.present"],
        ),
    ]
    queries = [
        golden_query(
            "q-def-kpi-a",
            "definition",
            "¿Qué es KPI-A?",
            objects=["def-kpi-a"],
            expected_answer_contains=["promedio de ventas"],
        ),
        golden_query(
            "q-rule-desviacion",
            "validation",
            "¿Qué pasa si la desviación supera el 10%?",
            objects=["rule-desviacion"],
            expected_answer_contains=["escalar"],
        ),
    ]
    return _golden(
        anchor_terms=["KPI-A", "KPI-B", "desviación", "responsable", "tablero"],
        objects=objects,
        queries=queries,
    )


# ---------------------------------------------------------------------------
# G. PDF tagged
# ---------------------------------------------------------------------------


def build_tagged(pages: int = 1) -> bytes:
    return tagged_pdf(
        title="Normativa Interna",
        elements=[
            ("H1", "Normativa Interna de Registro"),
            ("H2", "3. Registro de entidades"),
            ("P", "Toda entidad must registrarse antes del 31/12/2026."),
            ("P", "entidad - persona jurídica o sucursal."),
            ("P", "El incumplimiento must not quedar sin sanción."),
        ],
    )


def golden_tagged(pages: int = 1) -> dict[str, Any]:
    objects = [
        golden_object(
            "def-entidad",
            "definition",
            "entidad es persona jurídica o sucursal",
            pages=[1],
            section="3. Registro de entidades",
            equivalents=["entidad", "persona jurídica", "sucursal"],
            properties={"term": "entidad", "value": "persona jurídica o sucursal"},
        ),
        golden_object(
            "rule-registro",
            "rule",
            "toda entidad must registrarse antes del 31/12/2026",
            pages=[1],
            section="3. Registro de entidades",
            equivalents=["entidad", "registrarse", "31/12/2026"],
        ),
        golden_object(
            "rule-sancion",
            "rule",
            "el incumplimiento must not quedar sin sanción",
            pages=[1],
            section="3. Registro de entidades",
            equivalents=["incumplimiento", "sanción", "must not"],
        ),
    ]
    queries = [
        golden_query(
            "q-def-entidad",
            "definition",
            "¿Qué es una entidad?",
            objects=["def-entidad"],
            expected_answer_contains=["persona jurídica"],
        ),
        golden_query(
            "q-plazo",
            "lookup",
            "¿Cuál es el plazo de registro?",
            objects=["rule-registro"],
            expected_answer_contains=["31/12/2026"],
        ),
    ]
    return _golden(
        anchor_terms=["entidad", "registro", "sanción", "31/12/2026"],
        objects=objects,
        queries=queries,
    )


# ---------------------------------------------------------------------------
# H. Layout fixed-width
# ---------------------------------------------------------------------------


def build_fixed_width(pages: int = 2) -> bytes:
    canvas = PdfCanvas()
    canvas.text(72, 730, "Especificación de Registro de Datos", size=15, bold=True)
    canvas.text(72, 700, "1. Estructura de posiciones", size=13, bold=True)
    rows = [
        "Bytes 64-67 Exception Time",
        "Bytes 68-71 Penalty Amount",
        "Bytes 72-73 Fare Class Length",
        "Bytes 74-75 Record Type Code",
    ]
    for index, row in enumerate(rows):
        canvas.text(72, 670 - index * 20, row, size=11)
    canvas.text(
        72,
        570,
        "El campo Exception Time must ocupar exactamente 4 bytes entre las posiciones 64 y 67.",
        size=11,
    )
    canvas.text(
        72,
        548,
        "El campo Fare Class Length must tener una longitud mínima de 2 bytes.",
        size=11,
    )
    canvas.new_page()
    canvas.text(72, 730, "2. Reglas de validación", size=13, bold=True)
    canvas.text(
        72,
        700,
        "Si el registro no respeta las posiciones, el sistema must rechazar el archivo.",
        size=11,
    )
    return canvas.build()


def golden_fixed_width(pages: int = 2) -> dict[str, Any]:
    objects = [
        golden_object(
            "range-exception-time",
            "range",
            "Exception Time ocupa bytes 64-67",
            pages=[1],
            section="1. Estructura de posiciones",
            equivalents=["Exception Time", "64-67"],
            properties={"field": "Exception Time", "range": "64-67"},
        ),
        golden_object(
            "len-fare-class",
            "length_policy",
            "Fare Class Length mínimo 2 bytes",
            pages=[1],
            section="1. Estructura de posiciones",
            equivalents=["Fare Class Length", "longitud mínima", "2 bytes"],
            required_premises=["length.policy"],
        ),
        golden_object(
            "rule-exception-time",
            "rule",
            "Exception Time must ocupar exactamente 4 bytes entre 64 y 67",
            pages=[1],
            section="1. Estructura de posiciones",
            equivalents=["Exception Time", "exactamente 4 bytes", "64", "67"],
            executable=True,
            required_premises=["length.policy", "range.value"],
        ),
        golden_object(
            "rule-rechazo",
            "rule",
            "registro fuera de posiciones must rechazar el archivo",
            pages=[2],
            section="2. Reglas de validación",
            equivalents=["rechazar el archivo", "posiciones", "must"],
            required_premises=["condition.present"],
        ),
    ]
    queries = [
        golden_query(
            "q-range",
            "lookup",
            "¿En qué bytes está Exception Time?",
            objects=["range-exception-time"],
            expected_answer_contains=["64", "67"],
        ),
        golden_query(
            "q-apply-length",
            "apply_rule",
            "¿Exception Time cumple la longitud exacta?",
            objects=["rule-exception-time"],
            expected_answer_contains=["4 bytes"],
        ),
    ]
    return _golden(
        anchor_terms=["Exception Time", "Penalty Amount", "Fare Class Length", "bytes"],
        objects=objects,
        queries=queries,
    )


# ---------------------------------------------------------------------------
# I. Reglas distribuidas entre páginas
# ---------------------------------------------------------------------------


def build_distribuidas(pages: int = 3) -> bytes:
    canvas = PdfCanvas()
    canvas.text(72, 730, "Reglas de Procesamiento de Transacciones", size=15, bold=True)
    canvas.text(72, 700, "1. Límites", size=13, bold=True)
    canvas.text(72, 670, "El sistema must rechazar la transacción", size=11)
    canvas.new_page()
    canvas.text(72, 730, "si el monto excede el límite configurado, y must registrar el evento.", size=11)
    canvas.text(
        72,
        700,
        "límite configurado - 10000 EUR por operación.",
        size=11,
    )
    canvas.new_page()
    canvas.text(72, 730, "2. Excepciones", size=13, bold=True)
    canvas.text(
        72,
        700,
        "Salvo que el cliente tenga autorización previa, la regla de rechazo aplica siempre.",
        size=11,
    )
    return canvas.build()


def golden_distribuidas(pages: int = 3) -> dict[str, Any]:
    objects = [
        golden_object(
            "cross-rule-rechazo",
            "cross_page_rule",
            "rechazar transacción si monto excede límite configurado y registrar evento",
            pages=[1, 2],
            section="1. Límites",
            equivalents=["rechazar la transacción", "excede el límite configurado", "registrar el evento"],
            properties={"subject": "transacción", "threshold": "10000 EUR"},
            executable=True,
            required_premises=["condition.present"],
        ),
        golden_object(
            "def-limite",
            "definition",
            "límite configurado es 10000 EUR por operación",
            pages=[2],
            section="1. Límites",
            equivalents=["límite configurado", "10000 EUR"],
            properties={"term": "límite configurado", "value": "10000 EUR"},
        ),
        golden_object(
            "exc-autorizacion",
            "exception",
            "autorización previa exceptúa la regla de rechazo",
            pages=[3],
            section="2. Excepciones",
            equivalents=["autorización previa", "rechazo"],
        ),
    ]
    queries = [
        golden_query(
            "q-distributed",
            "distributed_rule",
            "¿Cuándo se rechaza una transacción y qué se registra?",
            objects=["cross-rule-rechazo"],
            expected_answer_contains=["rechazar", "registrar el evento"],
            cross_page=True,
        ),
        golden_query(
            "q-limit",
            "lookup",
            "¿Cuál es el límite configurado?",
            objects=["def-limite"],
            expected_answer_contains=["10000 EUR"],
        ),
    ]
    return _golden(
        anchor_terms=["transacción", "límite configurado", "evento", "autorización previa"],
        objects=objects,
        queries=queries,
    )


# ---------------------------------------------------------------------------
# J. Ruido visual: headers/footers repetidos
# ---------------------------------------------------------------------------


def build_ruido(pages: int = 3) -> bytes:
    canvas = PdfCanvas()
    for page_index in range(1, pages + 1):
        if page_index > 1:
            canvas.new_page()
        canvas.text(72, 760, "CONFIDENCIAL - USO INTERNO", size=9)
        canvas.text(72, 40, f"Página {page_index} de {pages}", size=9)
        canvas.text(72, 720, "Manual de Seguridad de la Información", size=15, bold=True)
        canvas.text(72, 690, f"{page_index}. Controles", size=13, bold=True)
        canvas.text(
            72,
            660,
            f"El empleado must reportar incidentes de seguridad en un plazo de {page_index * 8} horas.",
            size=11,
        )
        canvas.text(
            72,
            638,
            "Las credenciales must not compartirse por correo electrónico.",
            size=11,
        )
    return canvas.build()


def golden_ruido(pages: int = 3) -> dict[str, Any]:
    objects = []
    queries = []
    for page_index in range(1, pages + 1):
        objects.append(
            golden_object(
                f"rule-reporte-{page_index}",
                "rule",
                f"reportar incidentes en {page_index * 8} horas",
                pages=[page_index],
                section=f"{page_index}. Controles",
                equivalents=["reportar incidentes", f"{page_index * 8} horas"],
            )
        )
    objects.append(
        golden_object(
            "rule-credenciales",
            "rule",
            "credenciales must not compartirse por correo",
            pages=[1],
            section="1. Controles",
            equivalents=["credenciales", "must not compartirse", "correo"],
        )
    )
    queries = [
        golden_query(
            "q-reporte",
            "lookup",
            "¿En qué plazo se reportan incidentes en la página 2?",
            objects=["rule-reporte-2"],
            expected_answer_contains=["16 horas"],
        )
    ]
    return _golden(
        anchor_terms=["incidentes", "credenciales", "seguridad", "horas"],
        objects=objects,
        queries=queries,
    )


# ---------------------------------------------------------------------------
# L. Fórmulas
# ---------------------------------------------------------------------------


def build_formulas(pages: int = 2) -> bytes:
    canvas = PdfCanvas()
    canvas.text(72, 730, "Modelo Financiero Básico", size=15, bold=True)
    canvas.text(72, 700, "1. Fórmulas", size=13, bold=True)
    canvas.text(72, 670, "interes = capital * tasa * tiempo", size=12)
    canvas.text(72, 648, "descuento = precio * 0.9", size=12)
    canvas.text(
        72,
        618,
        "tasa - interés mensual aplicable al capital.",
        size=11,
    )
    canvas.new_page()
    canvas.text(72, 730, "2. Aplicación", size=13, bold=True)
    canvas.text(
        72,
        700,
        "El analista must aplicar la fórmula de interés para cada operación.",
        size=11,
    )
    return canvas.build()


def golden_formulas(pages: int = 2) -> dict[str, Any]:
    objects = [
        golden_object(
            "formula-interes",
            "formula",
            "interes = capital * tasa * tiempo",
            pages=[1],
            section="1. Fórmulas",
            equivalents=["interes", "capital", "tasa", "tiempo"],
            executable=True,
            required_premises=["formula.expression"],
        ),
        golden_object(
            "formula-descuento",
            "formula",
            "descuento = precio * 0.9",
            pages=[1],
            section="1. Fórmulas",
            equivalents=["descuento", "precio", "0.9"],
        ),
        golden_object(
            "def-tasa",
            "definition",
            "tasa es el interés mensual aplicable",
            pages=[1],
            section="1. Fórmulas",
            equivalents=["tasa", "interés mensual"],
            properties={"term": "tasa", "value": "interés mensual"},
        ),
        golden_object(
            "rule-aplicar-interes",
            "rule",
            "el analista must aplicar la fórmula de interés",
            pages=[2],
            section="2. Aplicación",
            equivalents=["analista", "fórmula de interés"],
        ),
    ]
    queries = [
        golden_query(
            "q-formula",
            "calculation",
            "¿Cómo se calcula el interés?",
            objects=["formula-interes"],
            expected_answer_contains=["capital", "tasa", "tiempo"],
        ),
        golden_query(
            "q-def-tasa",
            "definition",
            "¿Qué es la tasa?",
            objects=["def-tasa"],
            expected_answer_contains=["interés mensual"],
        ),
    ]
    return _golden(
        anchor_terms=["interes", "capital", "tasa", "descuento", "precio"],
        objects=objects,
        queries=queries,
    )


# ---------------------------------------------------------------------------
# ATPCO — regresión real (contenido fiel del fixture, sin lógica de dominio)
# ---------------------------------------------------------------------------


def build_atpco(pages: int = 2) -> bytes:
    canvas = PdfCanvas()
    canvas.text(72, 730, "DATA APPLICATION FOR RECORD 2 - CATEGORY CONTROL", size=14, bold=True)
    canvas.text(72, 705, "Fare Family Match using Exclamation Point (!) or Ampersand (&)", size=12, bold=True)
    canvas.text(
        72,
        678,
        "The ! or & indicate a match to any alphanumeric character in that position of the fare class.",
        size=11,
    )
    canvas.text(
        72,
        656,
        "When using special characters ! or &, a fare class must contain at least the number of characters",
        size=11,
    )
    canvas.text(
        72,
        644,
        "referenced in the fare class field (additional characters may follow).",
        size=11,
    )
    canvas.text(
        72,
        616,
        "An & can be used to indicate a number or alpha in a specific position of the fare class.",
        size=11,
    )
    canvas.table(
        72,
        580,
        [150.0, 220.0, 120.0],
        [
            ["Example", "Pattern", "Valid matches"],
            ["Example 2", "&&TEST", "ABTEST, A1TEST, A1TESTA"],
            ["Example 3", "W&2M", "WB2M, WC2M, WB2MXRT"],
        ],
        size=9.0,
    )
    canvas.new_page()
    canvas.text(72, 730, "Positional rules", size=13, bold=True)
    canvas.text(
        72,
        700,
        "W&&2M cannot be used to match WA2M or W2M due to minimal fare class length being five characters.",
        size=11,
    )
    canvas.text(
        72,
        678,
        "The matched fare classes are at least six characters for patterns with three ampersands.",
        size=11,
    )
    return canvas.build()


def golden_atpco(pages: int = 2) -> dict[str, Any]:
    objects = [
        golden_object(
            "sym-ampersand",
            "symbol_definition",
            "& indica match a cualquier carácter alfanumérico en esa posición",
            pages=[1],
            section="Fare Family Match using Exclamation Point (!) or Ampersand (&)",
            equivalents=["&", "alphanumeric character", "in that position"],
            properties={"symbol": "&", "meaning": "any alphanumeric in position"},
        ),
        golden_object(
            "len-fare-class-min",
            "length_policy",
            "la fare class must contener al menos el número de caracteres "
            "referenciados (additional characters may follow)",
            pages=[1],
            section="Fare Family Match using Exclamation Point (!) or Ampersand (&)",
            equivalents=["at least the number of characters", "additional characters may follow"],
            required_premises=["length.policy"],
        ),
        golden_object(
            "rule-positional-match",
            "rule",
            "& se usa para indicar número o alfa en una posición específica; el match es posicional",
            pages=[1, 2],
            section="Positional rules",
            equivalents=["specific position", "positionally", "match fare class characters"],
            properties={"operator": "POSITIONAL_MATCH", "symbol": "&"},
            executable=True,
            required_premises=["symbol.definition", "matching.operator", "length.policy"],
        ),
        golden_object(
            "table-examples",
            "table_mapping",
            "ejemplos &&TEST, W&2M, W&&2M con matches válidos",
            pages=[1, 2],
            equivalents=["&&TEST", "ABTEST", "W&2M", "WB2M", "W&&2M"],
        ),
        golden_object(
            "cross-rule-ampersand-length",
            "cross_page_rule",
            "patrón con ampersands requiere longitud mínima y match posicional",
            pages=[1, 2],
            equivalents=["minimal fare class length", "positional rules"],
        ),
    ]
    queries = [
        golden_query(
            "q-atpco-match",
            "apply_rule",
            "¿ABCFGEGE cumple el patrón &&&F?",
            objects=["rule-positional-match"],
            values={"value": "ABCFGEGE", "pattern": "&&&F"},
            expected_status="MATCH",
            executable=True,
        ),
        golden_query(
            "q-atpco-length",
            "validation",
            "¿Qué longitud mínima exige el patrón &&&F?",
            objects=["len-fare-class-min"],
            expected_answer_contains=["at least", "characters"],
        ),
        golden_query(
            "q-atpco-symbol",
            "definition",
            "¿Qué significa & en la fare class?",
            objects=["sym-ampersand"],
            expected_answer_contains=["alphanumeric"],
        ),
    ]
    return _golden(
        anchor_terms=["&", "fare class", "alphanumeric", "position", "characters"],
        objects=objects,
        queries=queries,
    )


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CorpusDoc:
    name: str
    letter: str
    kind: str
    title: str
    notes: str
    builder: Callable[[int], bytes]
    golden_builder: Callable[[int], dict[str, Any]]
    default_pages: int = 2
    status: str = "ready"  # ready | pending_hybrid


CORPUS: list[CorpusDoc] = [
    CorpusDoc(
        "manual_tecnico_grande",
        "A",
        "manual",
        "Manual técnico grande",
        "Definiciones y reglas por página; escalable a cientos de páginas.",
        build_manual_grande,
        golden_manual_grande,
        default_pages=24,
    ),
    CorpusDoc(
        "manual_tablas",
        "B",
        "tablas",
        "Manual con muchas tablas",
        "Tablas con headers y filas en cada página.",
        build_manual_tablas,
        golden_manual_tablas,
        default_pages=6,
    ),
    CorpusDoc(
        "contrato",
        "C",
        "contrato",
        "Contrato de servicios",
        "Regla, excepción, temporal, fórmula y definición.",
        build_contrato,
        golden_contrato,
        default_pages=3,
    ),
    CorpusDoc(
        "procedimiento",
        "D",
        "procedimiento",
        "Procedimiento de alta",
        "Pasos, enumeración y reglas.",
        build_procedimiento,
        golden_procedimiento,
        default_pages=2,
    ),
    CorpusDoc(
        "politica",
        "E",
        "politica",
        "Política empresarial",
        "Condiciones, excepciones y relaciones.",
        build_politica,
        golden_politica,
        default_pages=3,
    ),
    CorpusDoc(
        "multicolumna",
        "F",
        "multicolumna",
        "Documento multi-columna",
        "Dos columnas con definiciones y reglas.",
        build_multicolumna,
        golden_multicolumna,
        default_pages=2,
    ),
    CorpusDoc(
        "tagged",
        "G",
        "tagged",
        "PDF tagged",
        "StructTreeRoot + ParentTree con MCIDs.",
        build_tagged,
        golden_tagged,
        default_pages=1,
    ),
    CorpusDoc(
        "fixed_width",
        "H",
        "fixed_width",
        "Layout fixed-width",
        "Posiciones Bytes NN-NN y políticas de longitud.",
        build_fixed_width,
        golden_fixed_width,
        default_pages=2,
    ),
    CorpusDoc(
        "distribuidas",
        "I",
        "distribuidas",
        "Reglas distribuidas entre páginas",
        "Regla partida entre página 1 y 2.",
        build_distribuidas,
        golden_distribuidas,
        default_pages=3,
    ),
    CorpusDoc(
        "ruido",
        "J",
        "ruido",
        "Headers/footers repetidos",
        "Chrome repetido en todas las páginas.",
        build_ruido,
        golden_ruido,
        default_pages=3,
    ),
    CorpusDoc(
        "escaneado",
        "K",
        "escaneado",
        "PDF escaneado",
        "Pendiente: requiere hybrid/OCR. No se simula.",
        lambda pages: b"",
        lambda pages: {"anchor_terms": [], "objects": [], "queries": []},
        default_pages=1,
        status="pending_hybrid",
    ),
    CorpusDoc(
        "formulas",
        "L",
        "formulas",
        "Fórmulas",
        "Fórmulas tipo cálculo y definiciones.",
        build_formulas,
        golden_formulas,
        default_pages=2,
    ),
    CorpusDoc(
        "atpco",
        "ATPCO",
        "atpco",
        "ATPCO Record 2 (regresión)",
        "Contenido fiel del fixture ampersand; diagnóstico de premisas.",
        build_atpco,
        golden_atpco,
        default_pages=2,
    ),
]


def corpus_by_name(name: str) -> CorpusDoc:
    for doc in CORPUS:
        if doc.name == name:
            return doc
    raise KeyError(f"corpus desconocido: {name}")


def build_corpus_pdf(doc: CorpusDoc, *, pages: int | None = None) -> bytes:
    return doc.builder(int(pages or doc.default_pages))


def golden_for(doc: CorpusDoc, *, pages: int | None = None) -> dict[str, Any]:
    payload = doc.golden_builder(int(pages or doc.default_pages))
    payload.update(
        {
            "document": doc.name,
            "letter": doc.letter,
            "kind": doc.kind,
            "title": doc.title,
            "notes": doc.notes,
            "status": doc.status,
            "pages": int(pages or doc.default_pages),
        }
    )
    return payload


def write_golden_sets(directory: str | Path, *, pages_overrides: dict[str, int] | None = None) -> list[str]:
    """Persiste los Golden Sets como artefactos auditables (JSON)."""
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for doc in CORPUS:
        pages = (pages_overrides or {}).get(doc.name, doc.default_pages)
        payload = golden_for(doc, pages=pages)
        path = root / f"{doc.name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(str(path))
    return written


def load_golden(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "CORPUS",
    "CorpusDoc",
    "build_corpus_pdf",
    "corpus_by_name",
    "golden_for",
    "golden_object",
    "golden_query",
    "load_golden",
    "write_golden_sets",
]
