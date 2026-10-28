# P18.1-00 — Baseline, reproducibilidad y mapa de riesgos

Base P18: `06415700e7c4a312a938ab9d81375026750b6dd9`.
Rama de trabajo: `fix/p18-1-knowledge-integrity-explorer`.

## Causas confirmadas

1. `workspace_chat()` validaba `source_ids` por organización/workspace, no por
   corpus. Sin `source_ids` recuperaba todo el workspace. `source_file()` no
   comprobaba que el corpus perteneciera al workspace actual.
2. `_resolve_upload_corpus()` elegía el corpus más antiguo y aceptaba una KB con
   corpus de otro workspace.
3. El wizard movía el paso a `check` ante cambios de `initialSessionId` y
   reutilizaba sesiones selladas.
4. El visor de evidencia dependía de una navegación `<a>` con cookie.
5. `source_profile()` declaraba `technical_specification` con dos campos y
   `_domain_from()` heredaba `document_type` como dominio.
6. La puerta de reglas usaba modalidad por regex sin contexto normativo.

## Fixtures

`tests/fixtures/p18_1/`: narrativa con diálogo y números, manual ATPCO,
política, contrato, CSV, vacío, contradictorio y PDF con ruido textual.
Son sintéticos. No se versiona ningún documento con licencia.

## Baseline

Ejecutar en un entorno con la base real:

```powershell
.\.venv\Scripts\python.exe scripts\p18_1_baseline.py
```

Salida: `artifacts/certification/p18-1/baseline.json` con SHA de Git,
configuración, hashes de fixtures, fuentes, perfiles, conteos de objetos,
evidencia, reglas y calidad. Es read-only.

## Puertas de salida

- G0: baseline reproducible y sin cambios productivos.
- G1: cero fugas de corpus, workspace, tenant o ACL.
- G2: destino de carga determinista y concurrente.
- G3: wizard reconstruible desde sesión durable.
- G4: evidencia abrible con cookie y Bearer.
- G5: narrativa fuera de `technical_specification`; fragmentos fuera del
  catálogo normal; manual técnico sin regresión.
- G6: Explorador explicable con pasajes y estados de certeza.
- G7: CI, rendimiento, matriz GO/NO-GO y rollback reproducido.

## Rollback

- UI del Explorador: `KNOWLEDGE_EXPLORER_V2_ENABLED=false`.
- Wizard: `KNOWLEDGE_IMPORT_WIZARD_V2_ENABLED=false`.
- Saneamiento histórico: `action=restore` sobre la metadata de presentación.
- Aislamiento de corpus: no tiene flag de apagado en producción; el rollback
  es revertir el release. Un flag que desactive la restricción reabre la fuga.
