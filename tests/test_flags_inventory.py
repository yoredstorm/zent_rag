# =============================================================================
# Flags inventory — drift contra .env.example (F0, corregido en F9-F11).
# =============================================================================
# El bug original: el filtro de claves de `.env.example` no aplicaba el prefijo
# `RAG_`, así que TODOS los flags parecían ausentes. El test fija el contrato.
from __future__ import annotations

from src.scripts.flags_inventory import (
    ENV_FLAG_PREFIXES,
    compute_drift,
    render_markdown,
)


class TestDrift:
    def test_env_example_real_no_tiene_drift(self) -> None:
        from src.scripts.flags_inventory import collect_env_example, collect_flags

        flags = collect_flags()
        drift = compute_drift(flags, collect_env_example())
        assert drift["en_env_sin_setting"] == []
        assert drift["setting_sin_env_example"] == [], (
            "flags de Settings ausentes de .env.example: "
            f"{drift['setting_sin_env_example'][:10]}"
        )

    def test_prefijo_rag_en_las_claves_documentadas(self) -> None:
        assert "RAG_RUNTIME_" in ENV_FLAG_PREFIXES
        assert ENV_FLAG_PREFIXES == tuple(
            f"RAG_{prefix}" for prefix in ("RUNTIME_", "ADAPTIVE_RAG_", "DECISION_",
                                            "JEV_", "NARRATIVE_", "LONG_CONTEXT_",
                                            "GATEWAY_", "EMBEDDING_", "LLM_", "CACHE_")
        )

    def test_drift_detecta_una_clave_faltante(self) -> None:
        flags = [
            {"flag": "RAG_RUNTIME_ANSWER_GATE", "field": "RUNTIME_ANSWER_GATE",
             "default": "off", "purpose": ""},
            {"flag": "RAG_RUNTIME_NUEVO", "field": "RUNTIME_NUEVO",
             "default": "on", "purpose": ""},
        ]
        env = {"RAG_RUNTIME_ANSWER_GATE": "off"}
        drift = compute_drift(flags, env)
        assert drift["setting_sin_env_example"] == ["RAG_RUNTIME_NUEVO"]
        assert drift["en_env_sin_setting"] == []

    def test_drift_detecta_clave_documentada_sin_campo(self) -> None:
        flags = [
            {
                "flag": "RAG_RUNTIME_ANSWER_GATE",
                "field": "x",
                "default": "",
                "purpose": "",
                "aliases": [],
            }
        ]
        env = {"RAG_RUNTIME_ANSWER_GATE": "off", "RAG_RUNTIME_INVENTADO": "1"}
        drift = compute_drift(flags, env)
        assert drift["en_env_sin_setting"] == ["RAG_RUNTIME_INVENTADO"]

    def test_alias_cuenta_como_documentado(self) -> None:
        flags = [
            {
                "flag": "RAG_DECISION_PREFLIGHT_MODE",
                "field": "DECISION_PREFLIGHT_MODE",
                "default": "off",
                "purpose": "",
                "aliases": ["RAG_JEV_PREFLIGHT_MODE"],
            }
        ]
        env = {"RAG_DECISION_PREFLIGHT_MODE": "off", "RAG_JEV_PREFLIGHT_MODE": "off"}
        drift = compute_drift(flags, env)
        assert drift["en_env_sin_setting"] == []

    def test_render_markdown_incluye_tabla_y_drift(self) -> None:
        flags = [
            {
                "flag": "RAG_RUNTIME_ANSWER_GATE",
                "field": "RUNTIME_ANSWER_GATE",
                "default": "off",
                "purpose": "verifica el borrador",
            }
        ]
        text = render_markdown(flags, {"en_env_sin_setting": [], "setting_sin_env_example": []})
        assert "| Flag | Default | Propósito |" in text
        assert "`RAG_RUNTIME_ANSWER_GATE`" in text
        assert "Sin drift" in text
