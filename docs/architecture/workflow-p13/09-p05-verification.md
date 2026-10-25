# P13 — 09 P05: certificación con evidencia real

## 1. Autoridad

`src/platform/workflows/verification.py` define `VerificationAdapter`,
`VerificationProbe` y `resolve_readiness`.

La readiness se deriva de:

1. binding activo para cada capacidad externa del grafo;
2. adaptador registrado para el `provider_kind`;
3. `probe` del adaptador con `ready` y `real`;
4. entorno reportado por el adaptador.

Nunca se lee `workflow.metadata.sandbox_ready` ni un flag del cliente.

Sin credenciales/entorno real, los adaptadores por defecto son
`UnavailableAdapter` y bloquean sandbox/provider con razón explícita.

## 2. Niveles

| Nivel | Requisito |
|---|---|
| `design` | readiness + agentes; no ejecuta |
| `simulation` | runner de simulación; nunca `PROVIDER_VERIFIED` |
| `sandbox` | al menos un adaptador real con evidencia sandbox |
| `provider` | adaptador real con evidencia provider |

`issue_certificate` acepta sandbox/provider solo si `run_verification` pasa.
La evidencia se persiste en `workflow_verification_evidence` con:
graph hash, binding fingerprint, provider refs, entorno, escenarios,
side effects, duración, actor y expiración. `workflow_certificates` liga
`verification_id` y `environment`.

## 3. Migración 173

- `workflow_verification_evidence`.
- `workflow_certificates.verification_id` y `environment`.

## 4. Pruebas

```powershell
uv run --frozen --no-sync pytest tests/test_workflow_verification.py -q
```

Resultado: **6 passed**.

- sandbox sin adaptador → `/test` degrada a simulación y certificado 409;
- metadata `sandbox_ready=true` → no certifica;
- adaptador fake (`real=False`) → sandbox/provider DENY;
- provider sin adaptador → `UNVERIFIED`, `provider_verified=false`;
- adaptador que falla con 500 → no emite certificado;
- certificado por workflow_id desde otro workspace → 404.

Regresión: `test_workflow_test_studio.py` + `test_workflow_publication_gate.py`
+ `test_solution_compiler.py` + `test_solution_composer.py` **29 passed**.

## 5. Límites y NOT_VERIFIED

- No hay credenciales de Stripe/IZIPAY, ERP ni sandbox externo: no se emitió
  `SANDBOX_VERIFIED` ni `PROVIDER_VERIFIED` reales.
- No se probaron 429/5xx de un proveedor real; sí el camino de fallo del
  adaptador.
- La UI distingue REQUESTED/EFFECTIVE y `provider_verified`, pero la prueba
  visual con proveedor real queda `NOT_VERIFIED`.
- `ZENT_GOLD_RELEASE_ENABLED=false`: un certificado sandbox no habilita
  publicación productiva de efectos externos.
