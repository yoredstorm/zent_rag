# =============================================================================
# Response Intelligence — cómo explicar la respuesta (forma, no contenido).
# =============================================================================
# Evidence Reasoning determina qué puede concluirse. Este paquete determina cómo
# explicarlo: elige la forma (blueprint), fija el nivel de detalle y compone un
# contrato observable que el generador recibe como instrucción.
#
# Nunca cambia hechos: no hay aquí ninguna fuente de verdad factual.
# =============================================================================
from __future__ import annotations

from src.intelligence.response.blueprints import (
    BLUEPRINT_ORDER,
    BLUEPRINTS,
    Blueprint,
    blueprint_ids,
    describe_blueprints,
    get_blueprint,
    public_blueprints,
    register_blueprint,
)
from src.intelligence.response.contract import (
    compose_contract,
    prompt_block,
)
from src.intelligence.response.profile import (
    RESPONSE_PROFILE_PRESETS,
    apply_turn_overrides,
    profile_from_config,
    profile_prompt_block,
)
from src.intelligence.response.questions import (
    build_composition_questions,
    read_composition_answers,
)
from src.intelligence.response.selector import (
    BlueprintSelection,
    deterministic_candidates,
    select_blueprint,
)

__all__ = [
    "BLUEPRINTS",
    "BLUEPRINT_ORDER",
    "Blueprint",
    "BlueprintSelection",
    "RESPONSE_PROFILE_PRESETS",
    "apply_turn_overrides",
    "blueprint_ids",
    "build_composition_questions",
    "compose_contract",
    "describe_blueprints",
    "deterministic_candidates",
    "get_blueprint",
    "profile_from_config",
    "profile_prompt_block",
    "prompt_block",
    "public_blueprints",
    "read_composition_answers",
    "register_blueprint",
    "select_blueprint",
]
