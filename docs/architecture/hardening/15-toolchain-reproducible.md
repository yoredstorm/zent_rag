# Toolchain reproducible — Python 3.11 + uv.lock

Estado: implementado. Fuente única de verdad para versiones exactas.

## 1. Fuente única

- `pyproject.toml`: **declaración de compatibilidad** (rangos `>=`). No se
  convierte a `==`: es el contrato de qué versiones soporta el paquete.
- `uv.lock`: **resolución exacta** de todos los extras (prod, dev, connectors,
  pdf-odl, ...). Es el artifact reproducible y queda versionado.
- `.python-version`: `3.11` (misma versión efectiva en local, CI y release).
- `uv` se instala con versión fijada (`pip install "uv==0.12.13"`) — no "latest".

## 2. Ambientes

| Ámbito | Comando |
|---|---|
| Developer | `uv sync --frozen --extra prod --extra dev` |
| Lint (CI) | `uv sync --frozen --extra dev` + `uv run --frozen --no-sync ruff check src/ tests/ sdk/python` |
| Test / nightly (CI) | `uv sync --frozen --extra prod --extra dev` + `uv run --frozen --no-sync pytest ...` |
| Gate de lock | `uv lock --check` (falla si `pyproject.toml` y `uv.lock` divergen) |

`--no-sync` en `uv run` usa exactamente el entorno sincronizado (con los extras
pedidos), sin re-sincronizar ni degradar extras.

## 3. Preguntas que responde

- **¿Qué versiones exactas se probaron para este SHA?** Las de `uv.lock` en ese
  commit. La CI consume el lock con `--frozen`: si el lock no está, o no cubre
  el entorno, el job falla.
- **¿Puedo reconstruir el mismo ambiente en tres meses?**
  `uv sync --frozen` sobre el mismo commit; uv resuelve Python 3.11 vía
  `.python-version` y las versiones exactas del lock.
- **¿Cómo actualizo dependencias intencionalmente?**

```bash
uv lock --upgrade-package <paquete>     # o: uv lock --upgrade (todas)
uv sync --frozen --extra prod --extra dev
uv run --frozen --no-sync pytest tests/ -v --timeout=300
uv run --frozen --no-sync ruff check src/ tests/ sdk/python
git add uv.lock pyproject.toml          # commit dedicado: build(deps): ...
```

## 4. Reglas

1. No fijar versiones manualmente en varios archivos: el único pin es el lock.
2. Toda actualización de dependencias pasa por la suite completa antes de
   commitear el lock.
3. Los jobs que corren la plataforma (test/nightly/portal-e2e) consumen el lock;
   `pip-audit` queda con pip por ser una auditoría puntual (informativa).
4. El SDK Python tiene su propio `pyproject` y sigue con pip hasta que se
   unifique el workspace (deuda conocida, fuera del alcance de esta fase).
