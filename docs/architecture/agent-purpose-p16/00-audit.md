# P16 — Auditoría del Purpose Builder

Fecha: `2026-10-26`. Base: `b9e8859` (cierre P15).

## 1. Caso reproducido

Entrada:

> Responde como un narrador de cuentos infantil.

Salida anterior insatisfactoria:

> El agente Principito debe responder como un narrador de cuentos infantiles a
> una audiencia técnica, apoyándose en el documento el_principito.pdf como
> fuente de conocimiento. Para lograrlo, utiliza las herramientas
> search_knowledge, query_tabular_data, query_database y call_api...

Defectos confirmados:

1. `build_purpose_prompt()` pedía 1 a 3 frases y no separaba identidad de
   comportamiento.
2. `PURPOSE_MAX_CHARS = 600` limitaba el propósito a una descripción corta.
3. El endpoint usaba sólo `agent.config_json` persistido; el frontend enviaba
   `{}` y perdía cambios sin guardar.
4. El contexto incluía herramientas internas y el modelo las enumeraba.
5. La audiencia del perfil se presentaba como si fuera la del usuario.
6. El fallback determinista podía reemplazar la intención por un texto genérico.
7. La respuesta sólo contenía `draft`; no había instrucciones operativas
   separadas ni validación de calidad.

## 2. Causa raíz

El generador trataba el propósito como una **descripción corporativa del
agente**, no como una interpretación de lo que el usuario quiere que el agente
sea y haga. Además, el endpoint no recibía el borrador actual del formulario y
el prompt no distinguía contexto técnico de intención.

## 3. Decisión

- Propósito e instrucciones son campos separados.
- El usuario ve texto natural, nunca el JSON.
- La generación usa el borrador actual, no sólo lo persistido.
- La identidad se conserva al aplicar cualquier perfil P14/P15.
- El validador es independiente del modelo generador.
- Si la generación falla, se conserva la entrada original con una limitación
  explícita; no se sustituye por un texto genérico.
- No se crea una segunda autoridad persistente de persona: `purpose`,
  `system_prompt` y `response_profile` siguen siendo las fuentes del runtime.
