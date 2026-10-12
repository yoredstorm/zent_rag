# =============================================================================
# Aislamiento por conversación — claves de caché nunca cruzan conversaciones.
# =============================================================================
# Regla: el aislamiento es por scope real (tenant + conversación), nunca por
# TTL. Mismo tenant, dos conversaciones: historial y respuestas no se cruzan.
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from src.agents.runtime.orchestrator import RAGOrchestrator
from src.infrastructure.redis.cache import RedisCache
from src.runtime.cache_fingerprint import conversation_cache_key


class _RecordingCache:
    """Proveedor nuevo: acepta conversation_id y registra lo recibido."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def _hash_query(
        self,
        organization_id: str,
        query: str,
        model: str,
        role: str = "",
        *,
        knowledge_fingerprint: str = "",
        conversation_id: str = "",
    ) -> str:
        self.calls.append(
            {
                "organization_id": organization_id,
                "conversation_id": conversation_id,
                "knowledge_fingerprint": knowledge_fingerprint,
            }
        )
        return (
            f"key:{organization_id}:{conversation_id}:{query}:{model}:{role}:"
            f"{knowledge_fingerprint}"
        )


class _LegacyCache:
    """Proveedor viejo (embebido): firma sin conversation_id."""

    @staticmethod
    def _hash_query(organization_id: str, query: str, model: str, role: str = "") -> str:
        return f"legacy:{organization_id}:{query}:{model}:{role}"


class TestClaveDeConversacion:
    def test_dos_conversaciones_no_comparten_clave(self) -> None:
        org = uuid4()
        conv_a, conv_b = uuid4(), uuid4()
        assert conversation_cache_key(org, conv_a) != conversation_cache_key(org, conv_b)

    def test_misma_conversacion_es_estable(self) -> None:
        org = uuid4()
        conv = uuid4()
        assert conversation_cache_key(org, conv) == conversation_cache_key(org, conv)

    def test_incluye_tenant(self) -> None:
        conv = uuid4()
        assert conversation_cache_key(uuid4(), conv) != conversation_cache_key(
            uuid4(), conv
        )


class TestHashQueryDelProveedor:
    def test_respuesta_cacheada_no_cruza_conversaciones(self) -> None:
        org = uuid4().hex
        query, model, role = "¿cuál es el límite?", "default", "admin"
        conv_a, conv_b = uuid4().hex, uuid4().hex

        key_a = RedisCache._hash_query(
            org, query, model, role, conversation_id=conv_a
        )
        key_b = RedisCache._hash_query(
            org, query, model, role, conversation_id=conv_b
        )
        assert key_a != key_b

        # Misma conversación + mismo fingerprint: misma clave (cache hit real).
        same_a = RedisCache._hash_query(
            org, query, model, role, conversation_id=conv_a
        )
        assert same_a == key_a

    def test_firma_legacy_sigue_funcionando(self) -> None:
        key = RedisCache._hash_query("org", "q", "model", "admin")
        assert isinstance(key, str) and key


class TestResponseCacheKey:
    def test_proveedor_nuevo_recibe_la_conversacion(self) -> None:
        cache = _RecordingCache()
        orch = SimpleNamespace(_cache=cache)
        key_a = RAGOrchestrator._response_cache_key(
            orch,
            organization_id="org",
            query="q",
            model="m",
            role="admin",
            conversation_id="conv-a",
        )
        key_b = RAGOrchestrator._response_cache_key(
            orch,
            organization_id="org",
            query="q",
            model="m",
            role="admin",
            conversation_id="conv-b",
        )
        assert key_a != key_b
        assert cache.calls[0]["conversation_id"] == "conv-a"
        assert cache.calls[1]["conversation_id"] == "conv-b"

    def test_proveedor_legacy_no_cachea_con_conversacion(self) -> None:
        """Fail-closed: sin soporte de conversación NO hay clave degradada.

        Degradar la clave serviría la respuesta de otra conversación del mismo
        tenant. Se desactiva la caché para el request (None) y se registra el
        bypass.
        """
        from src.infrastructure.observability.metrics import zent_cache_bypass_total

        orch = SimpleNamespace(_cache=_LegacyCache())
        counter = zent_cache_bypass_total.labels(
            reason="conversation_unsupported", provider="_LegacyCache"
        )
        before = counter._value.get()
        key = RAGOrchestrator._response_cache_key(
            orch,
            organization_id="org",
            query="q",
            model="m",
            role="admin",
            conversation_id="conv-a",
        )
        assert key is None
        assert counter._value.get() == before + 1

    def test_proveedor_legacy_sin_conversacion_conserva_clave(self) -> None:
        """Sin conversación no hay aislamiento que preservar: la firma sigue."""
        orch = SimpleNamespace(_cache=_LegacyCache())
        key = RAGOrchestrator._response_cache_key(
            orch,
            organization_id="org",
            query="q",
            model="m",
            role="admin",
        )
        assert key == _LegacyCache._hash_query("org", "q", "m", "admin")

    def test_cross_conversation_hits_cero_por_cien(self) -> None:
        """Adversarial ×100: A escribe, B lee — jamás comparten clave.

        Con proveedor nuevo las claves son distintas; con proveedor legacy la
        clave es None (caché desactivada), nunca la de la otra conversación.
        """
        org = uuid4().hex
        hits = 0
        for _ in range(100):
            conv_a, conv_b = uuid4().hex, uuid4().hex
            recording = SimpleNamespace(_cache=_RecordingCache())
            key_a = RAGOrchestrator._response_cache_key(
                recording,
                organization_id=org,
                query="misma pregunta",
                model="m",
                role="admin",
                conversation_id=conv_a,
            )
            key_b = RAGOrchestrator._response_cache_key(
                recording,
                organization_id=org,
                query="misma pregunta",
                model="m",
                role="admin",
                conversation_id=conv_b,
            )
            if key_a == key_b:
                hits += 1
            legacy = SimpleNamespace(_cache=_LegacyCache())
            legacy_key = RAGOrchestrator._response_cache_key(
                legacy,
                organization_id=org,
                query="misma pregunta",
                model="m",
                role="admin",
                conversation_id=conv_a,
            )
            if legacy_key is not None:
                hits += 1
        assert hits == 0

    def test_fingerprint_y_conversacion_conviven(self) -> None:
        cache = _RecordingCache()
        orch = SimpleNamespace(_cache=cache)
        key = RAGOrchestrator._response_cache_key(
            orch,
            organization_id="org",
            query="q",
            model="m",
            role="admin",
            knowledge_fingerprint="fp1",
            conversation_id="conv-a",
        )
        assert "fp1" in key
        assert cache.calls[0]["knowledge_fingerprint"] == "fp1"
        assert cache.calls[0]["conversation_id"] == "conv-a"

    def test_sin_proveedor_hash_devuelve_clave_determinista(self) -> None:
        orch = SimpleNamespace(_cache=SimpleNamespace())
        args = dict(
            organization_id="org",
            query="q",
            model="m",
            role="admin",
            conversation_id="conv-a",
        )
        first = RAGOrchestrator._response_cache_key(orch, **args)
        second = RAGOrchestrator._response_cache_key(orch, **args)
        other = RAGOrchestrator._response_cache_key(
            orch, **{**args, "conversation_id": "conv-b"}
        )
        assert first == second
        assert first != other
