# =============================================================================
# Domain Layer — PII / campos sensibles (patrones puros, sin frameworks)
# =============================================================================
# Detecta por NOMBRE de columna candidatos PII y campos sensibles de negocio.
# Usado por el profiling seguro (no se muestrea columnas sensibles) y por el
# catálogo físico.
# =============================================================================
from __future__ import annotations

import re

_PII_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("email", re.compile(r"email|correo", re.I)),
    ("phone", re.compile(r"phone|telefono|celular|movil|phone_number", re.I)),
    ("national_id", re.compile(r"rut|dni|cedula|passport|nid", re.I)),
    ("secret", re.compile(r"password|passwd|secret|token|api_key|credential", re.I)),
    ("payment_card", re.compile(r"card|credit|payment_method|bin_", re.I)),
    ("address", re.compile(r"address|direccion|domicilio|calle", re.I)),
    ("birth_date", re.compile(r"birth|nacimiento|fecha_nac", re.I)),
    ("health", re.compile(r"health|salud|medical|clinical|diagnost", re.I)),
    ("salary", re.compile(r"salario|salary|sueldo|remuneraci[oó]n", re.I)),
    ("financial", re.compile(r"account_number|cuenta|iban|clabe|income", re.I)),
]

_SENSITIVE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("cost", re.compile(r"cost|salario|salary|sueldo", re.I)),
    ("revenue", re.compile(r"revenue|ingreso|factura", re.I)),
    ("pii_related", re.compile(r"insured|coverage|beneficiario", re.I)),
]


def pii_flags_for_column(name: str) -> list[str]:
    """Labels PII detectados por nombre de columna (vacío = sin candidatos)."""
    return [label for label, pattern in _PII_PATTERNS if pattern.search(name)]


def is_sensitive_column(name: str) -> bool:
    """True si el nombre sugiere un campo sensible de negocio."""
    return any(pattern.search(name) for _label, pattern in _SENSITIVE_PATTERNS) or bool(
        pii_flags_for_column(name)
    )


def should_sample_column(name: str) -> bool:
    """Una columna PII/sensible nunca se muestrea automáticamente."""
    return not is_sensitive_column(name)
