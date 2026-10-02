# =============================================================================
# Knowledge Events — adaptador de eventos de dominio al bus durable (C8, W5).
# =============================================================================
# `KnowledgeSystemEventEmitter` traduce `KnowledgeSystemEvent` al contrato real
# de `KnowledgeEventEmitter` (persistencia durable + publicación realtime).
# =============================================================================
from src.platform.knowledge_events.emitter import KnowledgeSystemEventEmitter

__all__ = ["KnowledgeSystemEventEmitter"]
