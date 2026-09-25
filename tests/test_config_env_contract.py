# =============================================================================
# Contrato de nombres de variables de entorno (evita regresiones silenciosas).
# =============================================================================
# Settings usa `env_prefix="RAG_"`: el nombre real de cada variable es
# `RAG_` + el nombre EXACTO del campo. Un nombre sin el prefijo (o con el
# prefijo a medias) no da error: Pydantic lo ignora y el sistema sigue con el
# default, así que un flag «configurado» puede no estar aplicándose nunca.
#
# Este test compara los archivos de despliegue contra `Settings.model_fields`.
# =============================================================================
from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.core.config import Settings

ROOT = Path(__file__).resolve().parent.parent

_ENV_LINE_RE = re.compile(r"^\s*(?:-\s*)?(RAG_[A-Z0-9_]+)\s*[:=]")

#: Archivos que declaran variables de entorno del servicio.
ARCHIVOS = (
    ".env.example",
    "docker-compose.yml",
    "docker-compose.prod.yml",
    "deploy/k8s/configmap.yaml",
)

#: Claves que no son campos de Settings a propósito (las consume otra capa).
NO_APLICAN: frozenset[str] = frozenset()


def _keys(path: Path) -> list[str]:
    if not path.exists():
        return []
    keys: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _ENV_LINE_RE.match(line)
        if match:
            keys.append(match.group(1).upper())
    return keys


@pytest.mark.parametrize("archivo", ARCHIVOS)
def test_variables_de_entorno_mapean_a_un_campo(archivo: str) -> None:
    campos = {name.upper() for name in Settings.model_fields}
    desconocidas = [
        key
        for key in _keys(ROOT / archivo)
        if key not in NO_APLICAN and key[len("RAG_"):] not in campos
    ]
    assert desconocidas == [], (
        f"{archivo}: estas variables no existen en Settings y se ignoran en "
        f"silencio (el nombre debe ser RAG_ + el campo exacto): {sorted(set(desconocidas))}"
    )


def test_prefijo_del_modelo() -> None:
    assert Settings.model_config.get("env_prefix") == "RAG_"


def test_flags_del_gate_y_evidencia_existen() -> None:
    """Los flags que gobiernan el gate y la evidencia no se renombran sin test."""
    for nombre in (
        "RUNTIME_ANSWER_GATE",
        "RUNTIME_AGENT_JEV_LOOP",
        "RUNTIME_AGENT_JEV_LOOP_CANARY_PERCENTAGE",
        "RUNTIME_AGENT_MAX_RETRIEVAL_ROUNDS",
        "RUNTIME_AGENT_MAX_SEARCHES",
        "RUNTIME_JEV_ANSWER_APPROVE",
        "RUNTIME_JEV_ANSWER_REVISE",
        "RUNTIME_JEV_STATE_MAX_CHARS",
        "RUNTIME_EVIDENCE_BUDGET_CHARS",
        "RAG_RESPONSE_INTELLIGENCE_MODE",
        "RAG_RESPONSE_PRESENTATION_GATE",
        "RAG_RETRIEVAL_ENTITY_PIN",
    ):
        assert nombre in Settings.model_fields, f"falta el campo {nombre}"


def test_nombres_documentados_coinciden_con_el_modelo() -> None:
    """`.env.example` documenta el nombre real (RAG_ + campo), no uno inventado."""
    campos = {name.upper() for name in Settings.model_fields}
    exportados = {
        key for key in _keys(ROOT / ".env.example") if not key.startswith("RAG_RAG_")
    }
    for key in sorted(exportados):
        assert key[len("RAG_"):] in campos, key
