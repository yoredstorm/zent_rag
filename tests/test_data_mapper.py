# Mapper universal: planos, contratos, aislamiento y retención. Sin almacén nuevo.
from __future__ import annotations

from cryptography.fernet import Fernet

from src.platform.workflows.data_mapper import (
    MAPPING_SCHEMA,
    DataMapError,
    accept_memory,
    apply_read,
    assemble_min_context,
    assert_graph_mapping,
    can_read,
    correct_memory,
    data_plane_inventory,
    declarative_select,
    erase_memory,
    export_memory,
    inspect_schema,
    mapping_errors,
    missing_fallback,
    preview_rows,
    project_source,
)


def _actor(**extra):
    base = {
        "organization_id": "org-1",
        "workspace_id": "ws-1",
        "role": "seller",
        "subject_id": "cust-1",
        "session_id": "sess-1",
    }
    base.update(extra)
    return base


def _product_doc(**extra):
    doc = {
        "schema": MAPPING_SCHEMA,
        "role": "seller",
        "sources": [
            {
                "id": "pg_products",
                "kind": "managed_db",
                "table": "products",
                "capability_ref": "catalog.products.search",
                "fields": [
                    {"name": "sku", "type": "string"},
                    {"name": "name", "type": "string"},
                ],
            }
        ],
        "mappings": [
            {"source_id": "pg_products", "field": "sku", "target": "product"},
        ],
        "output_schema": {
            "type": "object",
            "required": ["product"],
            "properties": {"product": {"type": "string"}},
        },
    }
    doc.update(extra)
    return doc


def test_inventory_reuses_existing_stores() -> None:
    inventory = data_plane_inventory()
    assert inventory["duplicate_vector_store"] is False
    assert "workflow_instances.state" in inventory["stores"]["workflow.state"]
    with __import__("pytest").raises(DataMapError):
        project_source({"id": "q", "kind": "vector_store"})


def test_product_postgres_exercise_kb_support_docs_and_auditor_files() -> None:
    assert mapping_errors(_product_doc()) == []
    exercise = {
        "schema": MAPPING_SCHEMA,
        "sources": [
            {
                "id": "kb_math",
                "kind": "knowledge_file",
                "kb_id": "kb-1",
                "document_id": "doc-9",
                "fields": [{"name": "title", "type": "string"}],
            }
        ],
        "mappings": [{"source_id": "kb_math", "field": "title", "target": "exercise"}],
        "output_schema": {
            "type": "object",
            "required": ["exercise"],
            "properties": {"exercise": {"type": "string"}},
        },
    }
    assert mapping_errors(exercise) == []
    support = {
        "schema": MAPPING_SCHEMA,
        "sources": [
            {
                "id": "kb_help",
                "kind": "knowledge_base",
                "kb_id": "kb-help",
                "fields": [{"name": "article", "type": "string"}],
            }
        ],
        "mappings": [{"source_id": "kb_help", "field": "article", "target": "ticket"}],
    }
    assert mapping_errors(support) == []
    auditor = {
        "schema": MAPPING_SCHEMA,
        "sources": [
            {
                "id": "files",
                "kind": "knowledge_file",
                "document_id": "audit.csv",
                "fields": [{"name": "code", "type": "string"}],
            }
        ],
        "mappings": [{"source_id": "files", "field": "code", "target": "ticket"}],
    }
    assert mapping_errors(auditor) == []
    chef = _product_doc(role="chef")
    assert mapping_errors(chef) == []


def test_contract_mismatch_missing_row_and_schema_update() -> None:
    bad = _product_doc()
    bad["output_schema"] = {
        "type": "object",
        "required": ["product"],
        "properties": {"product": {"type": "integer"}},
    }
    assert any("contract_mismatch" in item or "tipo inválido" in item for item in mapping_errors(bad))
    missing = apply_read([], target="product", field="sku")
    assert missing["value"] is None
    assert missing["invented"] is False
    assert missing["fallback"]["claim"] is None
    drifted = _product_doc()
    drifted["sources"][0]["fields"] = [{"name": "name", "type": "string"}]
    assert any(item.startswith("schema_changed") for item in mapping_errors(drifted))
    profile = _product_doc()
    profile["mappings"] = [
        {"source_id": "pg_products", "field": "sku", "target": "wellness_note", "plane": "role.profile"}
    ]
    profile["output_schema"] = {
        "type": "object",
        "required": ["wellness_note"],
        "properties": {"wellness_note": {"type": "string"}},
    }
    profile_errors = mapping_errors(profile)
    assert any("role.profile" in item for item in profile_errors)
    bare = _product_doc()
    bare["sources"][0].pop("capability_ref")
    assert any("capability_ref" in item for item in mapping_errors(bare))


def test_permissions_secrets_and_injection_stay_data() -> None:
    locked = _product_doc()
    locked["sources"][0]["required_permission"] = "data:read"
    assert any(item.startswith("permission_denied") for item in mapping_errors(locked, permissions=frozenset()))
    assert mapping_errors(locked, permissions=frozenset({"data:read"})) == []
    schema = inspect_schema(
        {"id": "t", "kind": "managed_db", "fields": [{"name": "sku", "type": "string"}, {"name": "api_key", "type": "string"}]},
        permissions=frozenset(),
    )
    assert [field["name"] for field in schema["fields"]] == ["sku"]
    preview = preview_rows(
        [{"sku": "A", "password": "s3cret", "note": "x'; DROP TABLE products;--"}],
        limit=5,
    )
    assert preview["rows"][0]["password"] == "[redactado]"
    assert "DROP" in preview["rows"][0]["note"]
    built = declarative_select(
        {
            "table": "products",
            "columns": ["sku"],
            "filters": {"sku": "x'; DROP TABLE products;--"},
        }
    )
    assert "DROP" not in built["sql"]
    assert built["params"]["f0"].startswith("x'; DROP")
    try:
        declarative_select({"table": "products;drop", "columns": ["sku"]})
        raise AssertionError("identificador peligroso")
    except DataMapError as exc:
        assert exc.code == "raw_sql"
    try:
        declarative_select({"sql": "SELECT * FROM products", "table": "products", "columns": ["sku"]})
        raise AssertionError("sql libre")
    except DataMapError as exc:
        assert exc.code == "raw_sql"
    try:
        declarative_select({"table": "products", "columns": ["sku"], "op": "delete"})
        raise AssertionError("escritura")
    except DataMapError as exc:
        assert exc.code == "write_denied"
    allowed = declarative_select(
        {"table": "orders", "columns": ["id"], "op": "update", "capability_ref": "sales.order.update"}
    )
    assert allowed["mode"] == "capability"
    assert allowed["sql"] is None


def test_memory_opt_in_export_correct_erase_and_no_clinical_retention() -> None:
    key = Fernet.generate_key()
    try:
        accept_memory(
            {
                "organization_id": "org-1",
                "workspace_id": "ws-1",
                "subject_id": "cust-1",
                "purpose": "progreso",
                "consent": False,
                "expires_at": "2026-12-01T00:00:00+00:00",
                "value": {"done": 1},
            },
            key=key,
        )
        raise AssertionError("consent")
    except DataMapError as exc:
        assert exc.code == "consent_required"
    try:
        accept_memory(
            {
                "organization_id": "org-1",
                "workspace_id": "ws-1",
                "subject_id": "cust-1",
                "purpose": "clinico",
                "consent": True,
                "sensitivity": "clinical",
                "expires_at": "2026-12-01T00:00:00+00:00",
                "value": "nota",
            },
            key=key,
        )
        raise AssertionError("clinico")
    except DataMapError as exc:
        assert exc.code == "no_retention"
    stored = accept_memory(
        {
            "organization_id": "org-1",
            "workspace_id": "ws-1",
            "subject_id": "cust-1",
            "purpose": "progreso del curso",
            "consent": True,
            "expires_at": "2026-12-01T00:00:00+00:00",
            "target": "progress",
            "value": {"done": 2},
        },
        key=key,
    )
    assert stored["value"]["enc"] == "fernet"
    actor = _actor(role="mentor")
    exported = export_memory(stored, actor, key=key)
    assert exported["value"] == '{"done": 2}'
    corrected = correct_memory(stored, actor, {"done": 3}, key=key)
    assert corrected["version"] == 2
    assert export_memory(corrected, actor, key=key)["value"] == '{"done": 3}'
    erased = erase_memory(stored, actor)
    assert erased["status"] == "erased"
    assert erased["value"] is None
    try:
        export_memory(stored, _actor(role="mentor", subject_id="cust-2"), key=key)
        raise AssertionError("otro sujeto")
    except DataMapError as exc:
        assert exc.code == "isolation"


def test_isolation_between_roles_tenants_and_sessions() -> None:
    cart = {
        "organization_id": "org-1",
        "workspace_id": "ws-1",
        "plane": "workflow.state",
        "target": "cart",
        "subject_id": "cust-2",
        "sensitivity": "personal",
        "source": "state.cart",
        "timestamp": "2026-10-22T00:00:00+00:00",
        "scope": "subject",
    }
    assert can_read(_actor(role="mentor", subject_id="cust-1"), cart) is False
    assert can_read(_actor(role="seller", subject_id="cust-1"), cart) is False
    assert can_read(_actor(role="seller", subject_id="cust-2"), cart) is True
    wellness = {
        "organization_id": "org-1",
        "workspace_id": "ws-1",
        "plane": "conversation.context",
        "target": "wellness_note",
        "subject_id": "cust-1",
        "session_id": "sess-1",
        "sensitivity": "clinical",
        "source": "turn",
        "timestamp": "2026-10-22T00:00:00+00:00",
        "scope": "session",
    }
    assert can_read(_actor(role="seller"), wellness) is False
    assert can_read(_actor(role="wellness", subject_id="cust-1"), wellness) is True
    assert can_read(_actor(role="wellness", subject_id="cust-1", session_id="otra"), wellness) is False
    assert can_read(_actor(organization_id="org-2", role="seller", subject_id="cust-2"), cart) is False


def test_minimal_context_and_fallbacks_do_not_invent() -> None:
    actor = _actor(role="wellness", subject_id="cust-1")
    assembled = assemble_min_context(
        mission="acompañar sin diagnosticar",
        actor=actor,
        consent=True,
        pieces=[
            {
                "plane": "knowledge.rag",
                "source": "kb-help",
                "timestamp": "2026-10-22T00:00:00+00:00",
                "scope": "tenant",
                "organization_id": "org-1",
                "confidence": 0.9,
                "quality": "cited",
                "value": "artículo 3",
                "sensitivity": "public",
            },
            {
                "plane": "conversation.context",
                "target": "wellness_note",
                "source": "turn",
                "timestamp": "2026-10-22T00:00:00+00:00",
                "scope": "session",
                "organization_id": "org-1",
                "workspace_id": "ws-1",
                "subject_id": "cust-1",
                "session_id": "sess-1",
                "sensitivity": "clinical",
                "value": "nota",
            },
            {"plane": "knowledge.rag", "value": "sin fuente"},
            {
                "plane": "workflow.state",
                "target": "cart",
                "source": "state.cart",
                "timestamp": "2026-10-22T00:00:00+00:00",
                "scope": "subject",
                "organization_id": "org-1",
                "subject_id": "cust-9",
                "sensitivity": "personal",
                "value": ["arroz"],
            },
        ],
    )
    assert assembled["invented"] is False
    assert [piece["source"] for piece in assembled["pieces"]] == ["kb-help", "turn"]
    assert {item["reason"] for item in assembled["omitted"]} == {"sin procedencia", "aislamiento"}
    for kind in ("memory", "knowledge", "progress", "clinical", "row"):
        fallback = missing_fallback(kind)
        assert fallback["claim"] is None
    assert "diagnóstico" in missing_fallback("clinical")["message"]
    assert "No declaro avance" in missing_fallback("progress")["message"]


def test_save_rejects_a_bad_mapping_on_the_graph() -> None:
    try:
        assert_graph_mapping({"metadata": {"data_mapping": {"schema": "no"}}})
        raise AssertionError("debio fallar")
    except ValueError as exc:
        assert "data mapping" in str(exc)
    assert_graph_mapping({"metadata": {}})
    assert_graph_mapping({"metadata": {"data_mapping": _product_doc()}})
