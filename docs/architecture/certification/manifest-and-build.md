# Release Evidence Manifest y build reproducible (Partes A y B)

## 1. El manifest

- Generador: `src/scripts/release_manifest.py` (el artifact **no se escribe a
  mano**).
- Salida: `artifacts/release/<sha>/manifest.json` (machine-readable) y
  `manifest.md` (human-readable).
- Nunca guarda secretos: solo nombres de variables y fingerprints de archivos.

Campos (mínimo garantizado por el generador):

| Campo | Contenido |
|---|---|
| `git` | SHA, branch, tag (`git describe`), dirty, subject |
| `build` | identifier, CI run id, versión de Python/uv, plataforma |
| `dependencies` | sha256 de `uv.lock`, `pyproject.toml`, `.python-version`, locks de portal/sdk, Dockerfiles, compose prod |
| `sbom` | ruta + sha256 del SBOM CycloneDX |
| `migrations` | head calculado del grafo `down_revision`, total de revisiones, head aplicado |
| `frontend` | versión de `portal/package.json` y artifact construido (o `not_built_in_this_run`) |
| `containers` | imagen, image id, flag de pin por digest |
| `checks` | resultado por check (ruff, gitleaks, …) tal como lo reporta el runner |
| `tests` | suite completa, invariantes y batería (con `not_available` cuando no corrió) |
| `evidence` | performance, load, chaos, seguridad, contabilidad (ruta + sha256 + resumen) |
| `known_warnings` | warnings conocidos (lista explícita) |
| `accepted_risks` | riesgos aceptados con severity/owner/mitigation |
| `release_decision` | decisión, motivo, entorno, quién certificó |

Regla de lectura: **`not_available` significa NO DEMOSTRADO**, nunca verde. Si
el código cambia, el manifest caduca.

## 2. Dependencias: mismo SHA ⇒ mismo set esperado

| Control | Comando | Resultado (SHA `edeeb61`) |
|---|---|---|
| Lock alineado con pyproject | `uv lock --check` | OK (170 paquetes resueltos, sin cambios) |
| Instalación congelada | `uv sync --frozen --extra prod --extra dev` (CI) | reproducible; CI lo corre en cada job |
| Lock Python | `uv.lock` | sha256 `da55449bedabd6c187c4c353a941746d…` |
| Lock portal | `portal/package-lock.json` | sha256 `53b88b8ed8745061feab92a397e18390…` |
| Lock SDK Node | `sdk/node/package-lock.json` | sha256 `e9b6257cae3b44649efad7b79640f1e6…` |
| Interpreter | `.python-version` / uv | CPython 3.11.16 (uv-managed); CI usa `setup-python 3.11` |
| uv | pin en CI | `uv==0.12.13` (hardcodeado en `ci.yml` y `nightly.yml`) |

Ninguna actualización de dependencias es implícita: `--frozen` en todos los
pasos, `uv lock --check` en el job de lint, y `npm ci` (no `npm install`) en
portal/SDK.

## 3. SBOM (CycloneDX 1.5)

```bash
python -m src.scripts.sbom --out artifacts/release/<sha>/sbom.json
python -m src.scripts.sbom --check --out artifacts/release/<sha>/sbom.json
```

- Fuente: `uv.lock` + `portal/package-lock.json` + `sdk/node/package-lock.json`
  + `FROM` de los Dockerfile. Sin red y sin dependencias nuevas.
- Resultado en esta corrida: **734 componentes**, content hash
  `458532faae18a687ec08b6e649743408a296b5e7c6147c79356ffdc4406ca478`.
- El `serialNumber` es determinista (deriva del contenido), así que el SBOM es
  verificable en CI (`--check`) y en el job `build` se publica como artifact.

## 4. Contenedor

| Dato | Valor |
|---|---|
| Imagen | `zent-api:cert-edeeb61` (build local, `Dockerfile.api`, target default) |
| Image ID | `sha256:cb7fba67353dd0e40ca58f283f8e67b577937579e2421a74eb381f10a589fbc9` |
| Tamaño | 410 MB |
| Base image (runtime) | `python:3.11-slim` → digest `sha256:0dd364ba7e10242f07755449e3a3d0e35f9efd987952737b90def6709ab0c5ce` |
| CMD | `alembic upgrade head && uvicorn src.api.main:app --host 0.0.0.0 --port 8000` |
| Healthcheck | `python -c "urlopen('http://localhost:8000/health')"` cada 30 s |
| Usuario | `rag` (no root) |

Riesgos de supply chain declarados (P2-11 en `remaining-risks.md`):
- Imágenes base pinneadas por **tag**, no por digest (el digest se captura en el
  manifest, pero `FROM python:3.11-slim` puede moverse).
- Actions de CI por tag mayor (`actions/checkout@v4`, …), no por commit SHA.
- No hay Dependabot/renovate: la actualización de dependencias es deliberada
  (PR + tests), que es el control proporcional pedido por esta fase.

## 5. Entorno de esta corrida (para leer la evidencia sin engañarse)

| Dato | Valor |
|---|---|
| Host | workstation local (Windows, Docker Desktop 29.7.2) |
| DB | Postgres 16 (pgvector) local; para tests: DBs scratch `rag_cert*` creadas desde cero (paridad CI) |
| Redis / Qdrant | contenedores locales (7-alpine / v1.13.4, igual que CI) |
| Providers | reales (Novita primario, DeepInfra fallback) leídos de `.env` local |
| Python del venv local | 3.13.7 (**≠** 3.11 de CI/imagen) → los tests corren en 3.13; la imagen certificada corre 3.11 |
| `.env` | el local tiene ~375 knobs de desarrollo; para las corridas "CI-parity" se pasan las variables del job `test` como env vars (sin tocar `.env`) |
| Drift detectado | el DB de desarrollo local había perdido el seed de `subscriptions` del org demo (`03-billing.sql`): un test de RBAC fallaba por datos, no por código. Se verificó contra DB scratch (pasa) y se documentó como P3-6 |

Estas diferencias son parte de la evidencia: la certificación **no** afirma
paridad total con el entorno de producción (ver `final-report.md`).
