# Certificación de release — ZENT

Este directorio contiene la evidencia de la fase de certificación para canary y
producción. **Nada acá es una opinión**: cada afirmación está ligada a un SHA,
un entorno, una configuración, un dataset y un timestamp, y se puede reproducir
con los comandos que la acompañan.

## Reglas de esta carpeta (no negociables)

1. Todo resultado declara: SHA, fecha, entorno, comando y fuente de evidencia.
2. Un resultado **caduca** cuando cambia el código: si el SHA cambió, hay que
   regenerar la evidencia antes de promover.
3. Lo que no se midió se escribe `not_available` / `NO DEMOSTRADO`. Nunca verde.
4. Prohibido pegar cifras históricas como si fueran el estado actual.
5. El manifest se **genera** (`src/scripts/release_manifest.py`), no se escribe
   a mano. Nunca contiene secretos (solo nombres de variables y fingerprints).

## Índice

| Documento | Qué responde |
|---|---|
| `README.md` | Política de evidencia e índice (este archivo) |
| `manifest-and-build.md` | Release Evidence Manifest, build reproducible, SBOM |
| `perf-baseline.md` | Baseline de performance medido (cold/warm, cache, rutas degradadas) |
| `slo.md` | SLI/SLO, error budget y qué cuenta como error |
| `load-backpressure.md` | Carga sostenida, saturación y degradación controlada |
| `chaos-report.md` | Matriz de chaos (hermético + ensayos reales acotados) |
| `security-report.md` | Batería adversarial: 22 escenarios, hallazgos y fixes |
| `tenant-isolation.md` | Aislamiento A/B con contenido idéntico |
| `accounting-validation.md` | Cadena contable: ledger = usage = billing = observability |
| `observability.md` | Dashboards-as-code, alertas y su contrato |
| `delivery.md` | Branch protection, nightly, canary y rollback, migraciones |
| `remaining-risks.md` | Riesgos P0–P3, aceptados y pendientes |
| `final-report.md` | **Entregable**: SHA, scorecard y GO/NO-GO |
| `workflow-ai-go-no-go.md` | Prompt 08: certificación del AI Workflow Studio, P0 de pagos, reinicio real y NO-GO de IA |

## Cómo se genera la evidencia

```bash
# 1. Base de datos limpia (paridad CI) — evita el drift del DB de desarrollo
python scripts/cert/scratch_db.py create --name rag_cert && \
python scripts/cert/scratch_db.py init   --name rag_cert

# 2. Suite completa con el entorno del job `test` de CI
pwsh scripts/cert/run_ci_parity_suite.ps1 -Label full-suite -Database rag_cert -Targets tests/

# 3. Invariantes de arquitectura (lista extraída de ci.yml)
python scripts/cert/run_invariants.py

# 4. Batería de certificación (seguridad, chaos, determinismo, contabilidad, tenant)
python -m src.scripts.certification_battery --suite all --out-dir artifacts/certification/<sha>/battery

# 5. Performance / load / rutas degradadas
pwsh scripts/cert/run_perf_matrix.ps1

# 6. SBOM y manifest
python -m src.scripts.sbom --out artifacts/release/<sha>/sbom.json
python -m src.scripts.release_manifest --sha <sha> --decision <DECISION> ...
```

## Estado

El estado vigente está en `final-report.md` (§SHA certificado). Este archivo no
repite cifras a propósito: cualquier número que necesites vive en el documento
de su dominio, con su SHA y su fuente.
