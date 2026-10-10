# =============================================================================
# Pack ATPCO — aliases de dominio cargables (metadata, no lógica genérica).
# =============================================================================
from __future__ import annotations

from src.knowledge.enrichment.profiling import (
    active_profile_packs,
    expand_aliases,
    load_profile_packs,
)


def test_atpco_pack_declares_spanish_date_aliases() -> None:
    load_profile_packs(["src.verticals.atpco.enrichment"])
    packs = active_profile_packs()
    assert any(pack.name == "atpco" for pack in packs)
    aliases = expand_aliases("cambio de fechas", packs)
    assert "Eff Date" in aliases
    assert "Disc Date" in aliases
    assert "Effective Date" in aliases
    assert "Discontinue Date" in aliases


def test_pack_alias_lookup_is_normalized() -> None:
    load_profile_packs(["src.verticals.atpco.enrichment"])
    packs = active_profile_packs()
    assert expand_aliases("  CAMBIO DE FECHAS ", packs) == expand_aliases(
        "cambio de fechas", packs
    )


def test_unknown_term_has_no_pack_aliases() -> None:
    load_profile_packs(["src.verticals.atpco.enrichment"])
    packs = active_profile_packs()
    assert expand_aliases("politica de vacaciones", packs) == ()
