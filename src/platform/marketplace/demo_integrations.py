# =============================================================================
# Demo Integrations — PokéAPI, Open-Meteo y JSONPlaceholder (misión §2-§7).
#
# Se declaran como manifests v2 (actions + events) con provider `public_rest`:
# sin credenciales, HTTPS, SSRF check, timeout y límite de respuesta. El
# runtime de marketplace existente las ejecuta; no hay executor ad-hoc por
# integración. Los datos de JSONPlaceholder son DEMO y nunca productivos.
# =============================================================================
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

DEMO_INTEGRATIONS: list[dict[str, Any]] = [
    # -----------------------------------------------------------------------
    # PokéAPI — demo pública sin API key (misión §3-§5)
    # -----------------------------------------------------------------------
    {
        "slug": "pokeapi",
        "name": "PokéAPI (demo)",
        "provider": "pokeapi",
        "version": 1,
        "description": "Datos públicos de Pokémon para demos de integraciones, formularios y agentes.",
        "category": "demo",
        "auth_modes": ["NONE"],
        "pricing": {"model": "FREE"},
        "rate_limits": {"requests_per_minute": 60},
        "data_policy": {},
        "support": {"demo": True, "docs": "https://pokeapi.co"},
        "base_url": "https://pokeapi.co/api/v2",
        "capabilities": [
            {
                "slug": "pokemon",
                "name": "Pokémon",
                "description": "Consulta información pública de Pokémon.",
                "actions": [
                    {
                        "action_id": "pokemon.get",
                        "display_name": "Obtener información del Pokémon",
                        "description": "Nombre, tipos, habilidades, altura, peso y estadísticas.",
                        "business_name": "Buscar Pokémon",
                        "method": "GET",
                        "path_template": "/pokemon/{name}",
                        "output_map": {
                            "name": "name",
                            "id": "id",
                            "height": "height",
                            "weight": "weight",
                            "types": "types",
                            "abilities": "abilities",
                            "stats": "stats",
                            "base_experience": "base_experience",
                        },
                        "input_schema": {
                            "type": "object",
                            "required": ["name"],
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "x-business-label": "Pokémon",
                                    "x-business-placeholder": "pikachu",
                                    "x-business-help": "Escribe el nombre en inglés (pikachu, charmander…).",
                                    "examples": ["pikachu", "charmander", "bulbasaur"],
                                    "minLength": 2,
                                    "maxLength": 40,
                                }
                            },
                        },
                        "output_schema": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "x-business-label": "Nombre"},
                                "id": {"type": "integer", "x-business-label": "Número"},
                                "height": {"type": "integer", "x-business-label": "Altura", "x-business-unit": "dm"},
                                "weight": {"type": "integer", "x-business-label": "Peso", "x-business-unit": "hg"},
                                "types": {"type": "array", "x-business-label": "Tipos"},
                                "abilities": {"type": "array", "x-business-label": "Habilidades"},
                                "stats": {"type": "array", "x-business-label": "Estadísticas"},
                            },
                        },
                        "risk_level": "info",
                        "read_only": True,
                        "cache_policy": {"allow": True, "ttl_seconds": 3600},
                        "cost_model": {"model": "FREE"},
                    },
                    {
                        "action_id": "pokemon.species",
                        "display_name": "Ver especie",
                        "description": "Color, hábitat y datos de especie del Pokémon.",
                        "business_name": "Ver especie",
                        "method": "GET",
                        "path_template": "/pokemon-species/{name}",
                        "output_map": {
                            "name": "name",
                            "id": "id",
                            "color": "color.name",
                            "habitat": "habitat.name",
                            "is_legendary": "is_legendary",
                            "is_mythical": "is_mythical",
                            "capture_rate": "capture_rate",
                        },
                        "input_schema": {
                            "type": "object",
                            "required": ["name"],
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "x-business-label": "Pokémon",
                                    "x-business-placeholder": "pikachu",
                                }
                            },
                        },
                        "output_schema": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "x-business-label": "Nombre"},
                                "color": {"type": "string", "x-business-label": "Color"},
                                "habitat": {"type": "string", "x-business-label": "Hábitat"},
                                "is_legendary": {"type": "boolean", "x-business-label": "Legendario"},
                            },
                        },
                        "risk_level": "info",
                        "read_only": True,
                        "cache_policy": {"allow": True, "ttl_seconds": 3600},
                        "cost_model": {"model": "FREE"},
                    },
                    {
                        "action_id": "pokemon.by_type",
                        "display_name": "Buscar Pokémon por tipo",
                        "description": "Lista de Pokémon de un tipo (eléctrico, fuego…).",
                        "business_name": "Buscar Pokémon por tipo",
                        "method": "GET",
                        "path_template": "/type/{type}",
                        "output_map": {"name": "name", "id": "id", "pokemon": "pokemon"},
                        "input_schema": {
                            "type": "object",
                            "required": ["type"],
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "x-business-label": "Tipo",
                                    "x-business-help": "Tipo elemental en inglés.",
                                    "enum": [
                                        "normal", "fire", "water", "electric", "grass", "ice",
                                        "fighting", "poison", "ground", "flying", "psychic",
                                        "bug", "rock", "ghost", "dragon", "dark", "steel", "fairy",
                                    ],
                                    "x-business-enum-labels": [
                                        "Normal", "Fuego", "Agua", "Eléctrico", "Planta", "Hielo",
                                        "Lucha", "Veneno", "Tierra", "Volador", "Psíquico",
                                        "Bicho", "Roca", "Fantasma", "Dragón", "Siniestro", "Acero", "Hada",
                                    ],
                                }
                            },
                        },
                        "output_schema": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "x-business-label": "Tipo"},
                                "pokemon": {"type": "array", "x-business-label": "Pokémon del tipo"},
                            },
                        },
                        "risk_level": "info",
                        "read_only": True,
                        "cache_policy": {"allow": True, "ttl_seconds": 3600},
                        "cost_model": {"model": "FREE"},
                    },
                ],
            }
        ],
        "events": [],
    },
    # -----------------------------------------------------------------------
    # Open-Meteo — clima sin credenciales (misión §6 y §34-§35)
    # -----------------------------------------------------------------------
    {
        "slug": "open-meteo",
        "name": "Open-Meteo (demo)",
        "provider": "open-meteo",
        "version": 1,
        "description": "Clima actual y pronóstico diario para demos de schedules, condiciones y agentes.",
        "category": "demo",
        "auth_modes": ["NONE"],
        "pricing": {"model": "FREE"},
        "rate_limits": {"requests_per_minute": 60},
        "data_policy": {},
        "support": {"demo": True, "docs": "https://open-meteo.com"},
        "base_url": "https://api.open-meteo.com/v1",
        "capabilities": [
            {
                "slug": "weather",
                "name": "Clima",
                "description": "Consulta el clima de una ubicación.",
                "actions": [
                    {
                        "action_id": "weather.geocode",
                        "display_name": "Buscar ciudad",
                        "description": "Convierte el nombre de una ciudad en coordenadas.",
                        "business_name": "Buscar ciudad",
                        "base_url": "https://geocoding-api.open-meteo.com/v1",
                        "method": "GET",
                        "path_template": "/search",
                        "query": {"count": 1, "language": "es", "format": "json"},
                        "output_map": {"results": "results"},
                        "input_schema": {
                            "type": "object",
                            "required": ["name"],
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "x-business-label": "Ciudad",
                                    "x-business-placeholder": "Lima",
                                }
                            },
                        },
                        "output_schema": {
                            "type": "object",
                            "properties": {
                                "results": {"type": "array", "x-business-label": "Coincidencias"}
                            },
                        },
                        "risk_level": "info",
                        "read_only": True,
                        "cache_policy": {"allow": True, "ttl_seconds": 86400},
                        "cost_model": {"model": "FREE"},
                    },
                    {
                        "action_id": "weather.current",
                        "display_name": "Obtener clima actual",
                        "description": "Temperatura, humedad y viento actuales.",
                        "business_name": "Obtener clima actual",
                        "method": "GET",
                        "path_template": "/forecast",
                        "query": {
                            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                            "timezone": "auto",
                        },
                        "output_map": {
                            "temperature": "current.temperature_2m",
                            "humidity": "current.relative_humidity_2m",
                            "weather_code": "current.weather_code",
                            "wind_speed": "current.wind_speed_10m",
                            "time": "current.time",
                        },
                        "input_schema": {
                            "type": "object",
                            "required": ["latitude", "longitude"],
                            "properties": {
                                "latitude": {
                                    "type": "number",
                                    "x-business-label": "Latitud",
                                    "x-business-placeholder": "-12.0464",
                                },
                                "longitude": {
                                    "type": "number",
                                    "x-business-label": "Longitud",
                                    "x-business-placeholder": "-77.0428",
                                },
                            },
                        },
                        "output_schema": {
                            "type": "object",
                            "properties": {
                                "temperature": {
                                    "type": "number",
                                    "x-business-label": "Temperatura",
                                    "x-business-unit": "°C",
                                },
                                "humidity": {
                                    "type": "number",
                                    "x-business-label": "Humedad",
                                    "x-business-unit": "%",
                                },
                                "wind_speed": {
                                    "type": "number",
                                    "x-business-label": "Viento",
                                    "x-business-unit": "km/h",
                                },
                                "weather_code": {"type": "integer", "x-business-label": "Código de clima"},
                            },
                        },
                        "risk_level": "info",
                        "read_only": True,
                        "cache_policy": {"allow": True, "ttl_seconds": 900},
                        "cost_model": {"model": "FREE"},
                    },
                    {
                        "action_id": "weather.daily",
                        "display_name": "Obtener pronóstico diario",
                        "description": "Máxima, mínima y probabilidad de lluvia por día.",
                        "business_name": "Obtener pronóstico diario",
                        "method": "GET",
                        "path_template": "/forecast",
                        "query": {
                            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                            "timezone": "auto",
                            "forecast_days": 3,
                        },
                        "output_map": {
                            "dates": "daily.time",
                            "max_temps": "daily.temperature_2m_max",
                            "min_temps": "daily.temperature_2m_min",
                            "precipitation": "daily.precipitation_probability_max",
                        },
                        "input_schema": {
                            "type": "object",
                            "required": ["latitude", "longitude"],
                            "properties": {
                                "latitude": {"type": "number", "x-business-label": "Latitud"},
                                "longitude": {"type": "number", "x-business-label": "Longitud"},
                            },
                        },
                        "output_schema": {
                            "type": "object",
                            "properties": {
                                "dates": {"type": "array", "x-business-label": "Días"},
                                "max_temps": {"type": "array", "x-business-label": "Máximas (°C)"},
                                "min_temps": {"type": "array", "x-business-label": "Mínimas (°C)"},
                                "precipitation": {"type": "array", "x-business-label": "Lluvia (%)"},
                            },
                        },
                        "risk_level": "info",
                        "read_only": True,
                        "cache_policy": {"allow": True, "ttl_seconds": 3600},
                        "cost_model": {"model": "FREE"},
                    },
                ],
            }
        ],
        "events": [],
    },
    # -----------------------------------------------------------------------
    # JSONPlaceholder — DEMO DATA (misión §7)
    # -----------------------------------------------------------------------
    {
        "slug": "jsonplaceholder",
        "name": "Demo Records (JSONPlaceholder)",
        "provider": "jsonplaceholder",
        "version": 1,
        "description": "DEMO DATA — registros falsos para demos de GET/POST. Nunca usar como sistema productivo.",
        "category": "demo",
        "auth_modes": ["NONE"],
        "pricing": {"model": "FREE"},
        "rate_limits": {"requests_per_minute": 60},
        "data_policy": {"demo_only": True},
        "support": {"demo": True, "docs": "https://jsonplaceholder.typicode.com"},
        "base_url": "https://jsonplaceholder.typicode.com",
        "capabilities": [
            {
                "slug": "demo_records",
                "name": "Registros demo",
                "description": "Datos ficticios de usuarios y publicaciones.",
                "actions": [
                    {
                        "action_id": "demo_records.get_user",
                        "display_name": "Obtener usuario demo",
                        "description": "DEMO DATA — usuario ficticio con dirección y empresa.",
                        "business_name": "Obtener usuario demo",
                        "method": "GET",
                        "path_template": "/users/{id}",
                        "output_map": {
                            "name": "name",
                            "email": "email",
                            "city": "address.city",
                            "company": "company.name",
                            "phone": "phone",
                        },
                        "input_schema": {
                            "type": "object",
                            "required": ["id"],
                            "properties": {
                                "id": {
                                    "type": "integer",
                                    "x-business-label": "Usuario",
                                    "x-business-help": "Número del 1 al 10 en la demo.",
                                    "minimum": 1,
                                    "maximum": 10,
                                    "examples": [1, 2, 3],
                                }
                            },
                        },
                        "output_schema": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "x-business-label": "Nombre"},
                                "email": {"type": "string", "x-business-label": "Correo"},
                                "city": {"type": "string", "x-business-label": "Ciudad"},
                                "company": {"type": "string", "x-business-label": "Empresa"},
                            },
                        },
                        "risk_level": "info",
                        "read_only": True,
                        "cache_policy": {"allow": True, "ttl_seconds": 3600},
                        "cost_model": {"model": "FREE"},
                    },
                    {
                        "action_id": "demo_records.list_posts",
                        "display_name": "Listar publicaciones demo",
                        "description": "DEMO DATA — publicaciones ficticias de un usuario.",
                        "business_name": "Listar publicaciones demo",
                        "method": "GET",
                        "path_template": "/posts",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "userId": {
                                    "type": "integer",
                                    "x-business-label": "Usuario",
                                    "x-business-level": "guided",
                                    "minimum": 1,
                                }
                            },
                        },
                        "output_schema": {
                            "type": "object",
                            "properties": {"raw": {"type": "array", "x-business-label": "Publicaciones"}},
                        },
                        "risk_level": "info",
                        "read_only": True,
                        "cost_model": {"model": "FREE"},
                    },
                    {
                        "action_id": "demo_records.create_post",
                        "display_name": "Crear publicación simulada",
                        "description": "DEMO DATA — POST simulado: la API demo responde 201 pero no persiste nada.",
                        "business_name": "Crear publicación simulada",
                        "method": "POST",
                        "path_template": "/posts",
                        "output_map": {
                            "id": "id",
                            "title": "title",
                            "body": "body",
                            "userId": "userId",
                        },
                        "input_schema": {
                            "type": "object",
                            "required": ["title"],
                            "properties": {
                                "title": {"type": "string", "x-business-label": "Título"},
                                "body": {"type": "string", "x-business-label": "Contenido"},
                                "userId": {"type": "integer", "x-business-label": "Usuario", "default": 1},
                            },
                        },
                        "output_schema": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "integer", "x-business-label": "ID simulado"},
                                "title": {"type": "string", "x-business-label": "Título"},
                            },
                        },
                        "risk_level": "normal",
                        "read_only": False,
                        "cost_model": {"model": "FREE"},
                    },
                    {
                        "action_id": "demo_records.update_post",
                        "display_name": "Actualizar publicación simulada",
                        "description": "DEMO DATA — PUT simulado sobre una publicación ficticia.",
                        "business_name": "Actualizar publicación simulada",
                        "method": "PUT",
                        "path_template": "/posts/{id}",
                        "output_map": {"id": "id", "title": "title", "body": "body"},
                        "input_schema": {
                            "type": "object",
                            "required": ["id"],
                            "properties": {
                                "id": {"type": "integer", "x-business-label": "Publicación"},
                                "title": {"type": "string", "x-business-label": "Título"},
                                "body": {"type": "string", "x-business-label": "Contenido"},
                            },
                        },
                        "output_schema": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "integer", "x-business-label": "Publicación"},
                                "title": {"type": "string", "x-business-label": "Título"},
                            },
                        },
                        "risk_level": "normal",
                        "read_only": False,
                        "cost_model": {"model": "FREE"},
                    },
                ],
            }
        ],
        "events": [],
    },
]


_MANIFEST_KEYS = (
    "slug",
    "name",
    "provider",
    "version",
    "description",
    "category",
    "auth_modes",
    "pricing",
    "rate_limits",
    "data_policy",
    "support",
    "base_url",
    "events",
)


async def ensure_demo_integrations() -> dict[str, int]:
    """Upsert idempotente de las integraciones demo. Devuelve contadores."""
    from src.platform.marketplace.models import validate_integration_manifest

    created = 0
    actions = 0
    session = await get_async_session()
    try:
        # Paridad si la migración 111 aún no se aplicó (entornos de test).
        await session.execute(
            text(
                "ALTER TABLE integration_manifests ADD COLUMN IF NOT EXISTS events "
                "JSONB NOT NULL DEFAULT '[]'::jsonb"
            )
        )
        for manifest in DEMO_INTEGRATIONS:
            errors = validate_integration_manifest(_manifest_for_validation(manifest))
            if errors:
                logger.warning("demo manifest inválido", slug=manifest["slug"], errors=errors[:5])
                continue
            row = (
                await session.execute(
                    text(
                        "INSERT INTO integration_manifests "
                        "(slug, name, provider, version, description, category, logo_ref, countries, "
                        "auth_modes, scopes, pricing, rate_limits, data_policy, support, certification, "
                        "status, events) "
                        "VALUES (:slug, :name, :provider, :version, :description, :category, NULL, "
                        "CAST('[\"GLOBAL\"]' AS jsonb), CAST(:auth AS jsonb), '[]'::jsonb, "
                        "CAST(:pricing AS jsonb), CAST(:rate_limits AS jsonb), "
                        "CAST(:data_policy AS jsonb), CAST(:support AS jsonb), 'demo', 'PUBLISHED', "
                        "CAST(:events AS jsonb)) "
                        "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, "
                        "provider = EXCLUDED.provider, version = EXCLUDED.version, "
                        "description = EXCLUDED.description, category = EXCLUDED.category, "
                        "auth_modes = EXCLUDED.auth_modes, pricing = EXCLUDED.pricing, "
                        "rate_limits = EXCLUDED.rate_limits, data_policy = EXCLUDED.data_policy, "
                        "support = EXCLUDED.support, events = EXCLUDED.events, "
                        "status = 'PUBLISHED' "
                        "RETURNING id"
                    ),
                    {
                        "slug": manifest["slug"],
                        "name": manifest["name"],
                        "provider": manifest["provider"],
                        "version": int(manifest["version"]),
                        "description": manifest["description"],
                        "category": manifest["category"],
                        "auth": json.dumps(manifest["auth_modes"]),
                        "pricing": json.dumps(manifest["pricing"]),
                        "rate_limits": json.dumps(manifest["rate_limits"]),
                        "data_policy": json.dumps(manifest["data_policy"]),
                        "support": json.dumps(manifest["support"]),
                        "events": json.dumps(manifest.get("events") or []),
                    },
                )
            ).scalar()
            created += 1
            for capability in manifest["capabilities"]:
                cap_id = (
                    await session.execute(
                        text(
                            "INSERT INTO integration_capabilities "
                            "(integration_id, slug, name, description) "
                            "VALUES (:iid, :slug, :name, :description) "
                            "ON CONFLICT (integration_id, slug) DO UPDATE SET "
                            "name = EXCLUDED.name, description = EXCLUDED.description RETURNING id"
                        ),
                        {
                            "iid": row,
                            "slug": capability["slug"],
                            "name": capability["name"],
                            "description": capability["description"],
                        },
                    )
                ).scalar()
                for action in capability["actions"]:
                    provider_config = {
                        "kind": "public_rest",
                        "base_url": action.get("base_url") or manifest["base_url"],
                        "path_template": action["path_template"],
                        "method": action["method"],
                        "query": action.get("query") or {},
                        "output_map": action.get("output_map") or {},
                    }
                    await session.execute(
                        text(
                            "INSERT INTO integration_actions "
                            "(integration_id, capability_slug, action_id, display_name, description, "
                            "input_schema, output_schema, risk_level, read_only, requires_approval, "
                            "contains_personal_data, sensitive_data_classes, retention_policy, "
                            "cache_policy, timeout_ms, retry_policy, idempotency_support, cost_model, "
                            "provider_config, status) "
                            "VALUES (:iid, :cap, :aid, :dn, :desc, CAST(:ins AS jsonb), "
                            "CAST(:outs AS jsonb), :risk, :ro, false, false, '[]'::jsonb, "
                            "'{}'::jsonb, CAST(:cache AS jsonb), 8000, CAST(:retry AS jsonb), "
                            "false, CAST(:cost AS jsonb), CAST(:pc AS jsonb), 'ACTIVE') "
                            "ON CONFLICT (action_id) DO UPDATE SET integration_id = EXCLUDED.integration_id, "
                            "capability_slug = EXCLUDED.capability_slug, display_name = EXCLUDED.display_name, "
                            "description = EXCLUDED.description, input_schema = EXCLUDED.input_schema, "
                            "output_schema = EXCLUDED.output_schema, risk_level = EXCLUDED.risk_level, "
                            "read_only = EXCLUDED.read_only, cache_policy = EXCLUDED.cache_policy, "
                            "cost_model = EXCLUDED.cost_model, provider_config = EXCLUDED.provider_config, "
                            "status = 'ACTIVE'"
                        ),
                        {
                            "iid": row,
                            "cap": capability["slug"],
                            "aid": action["action_id"],
                            "dn": action["display_name"],
                            "desc": action["description"],
                            "ins": json.dumps(action["input_schema"]),
                            "outs": json.dumps(action["output_schema"]),
                            "risk": action.get("risk_level") or "info",
                            "ro": bool(action.get("read_only", True)),
                            "cache": json.dumps(action.get("cache_policy") or {}),
                            "retry": json.dumps({"max_attempts": 2}),
                            "cost": json.dumps(action.get("cost_model") or {"model": "FREE"}),
                            "pc": json.dumps(provider_config),
                        },
                    )
                    actions += 1
        await session.commit()
    except Exception:  # noqa: BLE001
        await session.rollback()
        logger.warning("Failed to ensure demo integrations")
        raise
    finally:
        await session.close()
    return {"integrations": created, "actions": actions}


def _manifest_for_validation(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        **manifest,
        "status": "PUBLISHED",
        "capabilities": [
            {
                **capability,
                "actions": [
                    {
                        **action,
                        "provider_config": {
                            "kind": "public_rest",
                            "base_url": action.get("base_url") or manifest["base_url"],
                            "path_template": action["path_template"],
                            "method": action["method"],
                        },
                    }
                    for action in capability["actions"]
                ],
            }
            for capability in manifest["capabilities"]
        ],
    }


_POKE_INSTALL = "{{_pack.pokeapi_install}}"
_WEATHER_INSTALL = "{{_pack.open-meteo_install}}"
_RECORDS_INSTALL = "{{_pack.jsonplaceholder_install}}"

DEMO_RECIPES: list[dict[str, Any]] = [
    {
        "slug": "pokemon-analyst",
        "name": "Analizar un Pokémon",
        "description": "Pregunta por un Pokémon, consulta PokéAPI y pide a un agente que resuma sus características.",
        "category": "demo",
        "trigger_type": "webhook",
        "trigger_config": {},
        "steps": [
            {
                "type": "marketplace_action",
                "config": {
                    "install_id": _POKE_INSTALL,
                    "action_id": "pokemon.get",
                    "inputs": {"name": "{{trigger.message}}"},
                },
            },
            {
                "type": "llm",
                "config": {
                    "prompt": (
                        "Resume las fortalezas y características del Pokémon "
                        "{{steps.0.output.name}} (tipos: {{steps.0.output.types}}, "
                        "altura: {{steps.0.output.height}}, peso: {{steps.0.output.weight}})."
                    )
                },
            },
            {
                "type": "notify",
                "config": {
                    "channel": "in_app",
                    "title": "Análisis de Pokémon",
                    "message": "{{steps.1.output.text}}",
                },
            },
        ],
    },
    {
        "slug": "pokemon-daily",
        "name": "Pokémon del día",
        "description": "Cada día a las 09:00 analiza un Pokémon y publica el resumen en Zent (ideal para demos).",
        "category": "demo",
        "trigger_type": "schedule",
        "trigger_config": {"daily": {"time": "09:00"}, "timezone": "America/Lima"},
        "steps": [
            {
                "type": "marketplace_action",
                "config": {
                    "install_id": _POKE_INSTALL,
                    "action_id": "pokemon.get",
                    "inputs": {"name": "pikachu"},
                },
            },
            {
                "type": "llm",
                "config": {
                    "prompt": (
                        "Escribe un resumen corto y divertido del Pokémon "
                        "{{steps.0.output.name}} para el equipo."
                    )
                },
            },
            {
                "type": "notify",
                "config": {
                    "channel": "in_app",
                    "title": "Pokémon del día",
                    "message": "{{steps.1.output.text}}",
                },
            },
        ],
    },
    {
        "slug": "weather-heat-alert",
        "name": "Alerta de calor (Lima)",
        "description": "Cada mañana consulta el clima de Lima y avisa si supera 30 °C. Sin IA.",
        "category": "demo",
        "trigger_type": "schedule",
        "trigger_config": {"daily": {"time": "08:00"}, "timezone": "America/Lima"},
        "steps": [
            {
                "type": "marketplace_action",
                "config": {
                    "install_id": _WEATHER_INSTALL,
                    "action_id": "weather.current",
                    "inputs": {"latitude": -12.0464, "longitude": -77.0428},
                },
            },
            {
                "type": "condition",
                "config": {"field": "steps.0.output.temperature", "operator": ">", "value": "30"},
                "then": [
                    {
                        "type": "notify",
                        "config": {
                            "channel": "in_app",
                            "title": "Alerta de calor",
                            "message": "Lima supera los 30 °C: {{steps.0.output.temperature}} °C.",
                        },
                    }
                ],
                "else": [
                    {
                        "type": "notify",
                        "config": {
                            "channel": "in_app",
                            "title": "Clima normal",
                            "message": "Temperatura actual: {{steps.0.output.temperature}} °C.",
                        },
                    }
                ],
            },
        ],
    },
    {
        "slug": "weather-logistics-analyst",
        "name": "Analista de clima logístico",
        "description": "Cada día revisa el pronóstico y pide a un agente resumir riesgos para operaciones.",
        "category": "demo",
        "trigger_type": "schedule",
        "trigger_config": {"daily": {"time": "07:00"}, "timezone": "America/Lima"},
        "steps": [
            {
                "type": "marketplace_action",
                "config": {
                    "install_id": _WEATHER_INSTALL,
                    "action_id": "weather.daily",
                    "inputs": {"latitude": -12.0464, "longitude": -77.0428},
                },
            },
            {
                "type": "llm",
                "config": {
                    "prompt": (
                        "Analiza el pronóstico (máximas: {{steps.0.output.max_temps}}, "
                        "lluvia: {{steps.0.output.precipitation}}) y resume riesgos para "
                        "la operación logística en 3 bullets."
                    )
                },
            },
            {
                "type": "notify",
                "config": {
                    "channel": "in_app",
                    "title": "Riesgos de clima",
                    "message": "{{steps.1.output.text}}",
                },
            },
        ],
    },
    {
        "slug": "demo-records-brief",
        "name": "Brief de registros demo",
        "description": "DEMO DATA: consulta un usuario ficticio y pide un resumen. Nunca usar en producción.",
        "category": "demo",
        "trigger_type": "webhook",
        "trigger_config": {},
        "steps": [
            {
                "type": "marketplace_action",
                "config": {
                    "install_id": _RECORDS_INSTALL,
                    "action_id": "demo_records.get_user",
                    "inputs": {"id": 1},
                },
            },
            {
                "type": "llm",
                "config": {"prompt": "Resume los datos demo del usuario {{steps.0.output.name}}."},
            },
            {
                "type": "notify",
                "config": {
                    "channel": "in_app",
                    "title": "Registros demo",
                    "message": "{{steps.1.output.text}}",
                },
            },
        ],
    },
]


async def ensure_demo_recipes() -> int:
    """Upsert idempotente de las recetas demo en workflow_templates."""
    session = await get_async_session()
    seeded = 0
    try:
        for recipe in DEMO_RECIPES:
            await session.execute(
                text(
                    "INSERT INTO workflow_templates "
                    "(slug, name, description, category, trigger_type, trigger_config, steps) "
                    "VALUES (:slug, :name, :description, :category, :trigger_type, "
                    "CAST(:trigger_config AS jsonb), CAST(:steps AS jsonb)) "
                    "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, "
                    "description = EXCLUDED.description, category = EXCLUDED.category, "
                    "trigger_type = EXCLUDED.trigger_type, "
                    "trigger_config = EXCLUDED.trigger_config, steps = EXCLUDED.steps"
                ),
                {
                    "slug": recipe["slug"],
                    "name": recipe["name"],
                    "description": recipe["description"],
                    "category": recipe["category"],
                    "trigger_type": recipe["trigger_type"],
                    "trigger_config": json.dumps(recipe["trigger_config"]),
                    "steps": json.dumps(recipe["steps"]),
                },
            )
            seeded += 1
        await session.commit()
    except Exception:  # noqa: BLE001
        await session.rollback()
        logger.warning("Failed to ensure demo recipes")
        raise
    finally:
        await session.close()
    return seeded


__all__ = [
    "DEMO_INTEGRATIONS",
    "DEMO_RECIPES",
    "ensure_demo_integrations",
    "ensure_demo_recipes",
]
