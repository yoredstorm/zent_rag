# Evidencia P00

Corte: `0cbb494ce4264077a1e6d4823f4520fbc32928b9` + WIP declarado en
`docs/architecture/workflow-vnext/00-baseline.md`.

| Archivo | Contenido |
|---|---|
| `sha.txt`, `branch.txt` | SHA y rama |
| `git-status.txt`, `git-diff-stat.txt`, `worktree.diff`, `untracked.txt` | Árbol de trabajo al inicio |
| `junit-targeted.xml` | 146 passed en architecture + workflows dirigidos |
| `junit-red-xfail.xml` | 8 xfailed (rojos contenidos) |
| `junit-red-proof.xml` | 8 failed con `--runxfail` (prueba real) |
| `junit-gold-sales.xml` | 1 passed, Gold ventas end-to-end |
| `junit-restart.xml` | 1 passed, reinicio con venta exacta |

## No verificado

- `junit-full.xml` no se generó: la suite completa terminó con exit 1 a los
  17 m 33 s, log vacío. Estado `NOT_VERIFIED`.
- Lote completo de `tests/certification/workflows`: 2 passed y timeout a los
  600 s en el tercer test. Resto `NOT_VERIFIED`.
- Playwright: no se levantó API/servidor. Estado `NOT_VERIFIED`.
