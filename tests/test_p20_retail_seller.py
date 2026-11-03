# =============================================================================
# P20-03/06/07 — manifiesto comercial y preset de vendedor.
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from src.platform.agents.retail_seller import (
    RETAIL_SELLER_PROMPT,
    RETAIL_SELLER_TOOLS,
    create_retail_seller,
    retail_agent_config,
    retail_grants,
)
from src.platform.commerce.catalog_manifest import retail_catalog_manifest


def test_catalog_manifest_declares_authority_and_forbidden_rules() -> None:
    manifest = retail_catalog_manifest(
        source_id=uuid4(), connector_id=uuid4(), workspace_id=uuid4()
    )
    assert manifest["version"] == "p20.retail-catalog/v1"
    assert manifest["entity"]["primary_key"] == "sku"
    assert manifest["authority"]["price"].endswith(".price")
    assert manifest["authority"]["stock"].endswith(".available")
    assert "precio inventado por el LLM" in manifest["presentation"]["forbidden"]
    assert "sales.cart.add" in manifest["capabilities"]["cart"]


def test_retail_agent_config_and_grants_are_explicit() -> None:
    config = retail_agent_config(source_id="source-1", cart_ttl_seconds=120)
    assert config["source_ids"] == ["source-1"]
    assert config["cart_ttl_seconds"] == 120
    assert config["security"]["no_llm_prices"] is True
    grants = retail_grants()
    assert {grant["capability_ref"] for grant in grants} >= {
        "store.query_database",
        "store.products.search",
        "store.price.get",
        "store.stock.get",
    }
    assert all(grant["resource_ref"] == "bodega.product_catalog_v" for grant in grants)
    assert all("row_scope" not in grant for grant in grants)


def test_retail_prompt_forbids_invented_money_and_cross_conversation_reads() -> None:
    prompt = RETAIL_SELLER_PROMPT.lower()
    assert "nunca inventes" in prompt
    assert "get_price_and_stock" in prompt
    assert "cart_add" in prompt
    assert "get_my_order" in prompt
    assert "otras conversaciones" in prompt
    assert "cart_get" in RETAIL_SELLER_TOOLS


async def test_create_retail_seller_uses_repo_and_grants(monkeypatch) -> None:
    calls: dict = {}

    class _Repo:
        async def create_agent(self, organization_id, name, **kwargs):
            calls["organization_id"] = organization_id
            calls["name"] = name
            calls["kwargs"] = kwargs
            return SimpleNamespace(id=uuid4(), name=name)

    async def _grants(organization_id, agent_id, grants, **kwargs):
        calls["grants"] = grants
        calls["grant_workspace"] = kwargs.get("workspace_id")

    monkeypatch.setattr(
        "src.platform.agents.retail_seller.set_agent_data_grants", _grants
    )
    organization_id = uuid4()
    workspace_id = uuid4()
    result = await create_retail_seller(
        organization_id,
        name="Vendedor demo",
        workspace_id=workspace_id,
        source_id="source-1",
        agent_repo=_Repo(),
    )
    assert result["agent_id"]
    assert calls["kwargs"]["tools"] == list(RETAIL_SELLER_TOOLS)
    assert calls["kwargs"]["config_json"]["source_ids"] == ["source-1"]
    assert calls["grants"]
    assert calls["grant_workspace"] == workspace_id
