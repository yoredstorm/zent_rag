# P16 — Diseño del constructor de propósito

## 1. Contrato API

`POST /api/v1/agents/{agent_id}/config/purpose`

Entrada compatible:

```json
{
  "purpose": "Responde como un narrador de cuentos infantil",
  "instructions": "Instrucciones actuales sin guardar",
  "name": "Principito",
  "description": "Cuentos para chicos",
  "profile": { "preset": "balanced" },
  "mode": "auto",
  "source_ids": [],
  "tools": ["search_knowledge"]
}
```

`purpose` e `instructions` son el borrador actual del formulario; no hace falta
guardarlos. `mode` acepta `auto`, `expand`, `improve` o `create`. El modo legacy
`instructions` sigue funcionando como propósito si no se envía `purpose`.

Respuesta:

```json
{
  "draft": "texto del propósito, compatible con clientes anteriores",
  "purpose": "texto del propósito",
  "additional_instructions": "directivas operativas",
  "intent_summary": "...",
  "persona": {"role": "...", "audience": "...", "voice": "...", "communication_principles": []},
  "behavioral_objectives": [],
  "knowledge_boundaries": [],
  "warnings": [],
  "source": "model | model_repaired | rules",
  "generation_source": "...",
  "mode": "auto | expand | improve | create",
  "input_purpose": "...",
  "quality": {
    "schema": "zent.agent_purpose_quality/v1",
    "passed": true,
    "score": 1.0,
    "criteria": {},
    "issues": [],
    "generic_phrases": [],
    "unnecessary_tools": [],
    "repaired": false
  },
  "grounded_in": {"sources": [], "source_kinds": [], "capabilities": [], "profile_id": "", "profile_audience": ""},
  "saved": false
}
```

`zent.agent_purpose/v2` es un contrato interno de transporte; la UI muestra
textos naturales. No se persiste automáticamente.

## 2. Prompt

`build_purpose_prompt()` exige resolver:

- quién es el agente;
- qué consigue para el usuario;
- cómo actúa;
- cómo interpreta preguntas informativas, valorativas y de seguimiento;
- cómo usa el conocimiento sin inventar;
- qué evita;
- qué hace sin evidencia;
- cómo conserva identidad ante perfiles P14/P15.

Reglas duras:

- preservar la intención original;
- no imponer la audiencia del perfil;
- no enumerar herramientas internas;
- no inventar capacidades, autorizaciones, hechos ni datos;
- separar propósito de instrucciones;
- longitud adaptativa, dentro de 2000 y 16000 caracteres.

## 3. Validador independiente

`evaluate_purpose_intent()` evalúa:

- `intent_preservation`
- `mission_specificity`
- `persona_consistency`
- `behavioral_actionability`
- `audience_consistency`
- `capability_grounding`
- `instruction_coherence`
- `unnecessary_tool_listing`
- `genericness`
- `safety_compliance`

Una reparación acotada se ejecuta una vez. Si sigue fallando, el endpoint
devuelve la entrada original, `source=rules` y warnings. No inventa un propósito
corporativo de reemplazo.

## 4. UX

`AgentPurposeForm`:

- envía propósito e instrucciones actuales aunque no estén guardados;
- selector Auto / Expandir / Mejorar / Crear;
- muestra objetivo original, propósito propuesto editable, instrucciones
  editables, persona, calidad y warnings;
- permite Aplicar propósito, Aplicar propósito e instrucciones, Regenerar o
  Cancelar;
- si ya hay instrucciones, ofrece Conservar, Combinar sin duplicar o Reemplazar;
- nunca guarda ni reemplaza `system_prompt` sin acción explícita;
- una respuesta tardía sólo actualiza la propuesta, nunca el formulario actual.

## 5. Identidad y compatibilidad

El propósito generado alimenta `config.purpose`; las instrucciones se aplican a
`system_prompt`. P15 deriva la identidad persistente del propósito y P14 aplica
estilo. El perfil no puede borrar la identidad: narrador + Conciso sigue siendo
narrador breve; narrador + Analítico sigue siendo narrador con razones.

No se alteran workflows publicados ni instancias durables; un cambio de
propósito es configuración del agente y queda sujeto al guardado normal.
