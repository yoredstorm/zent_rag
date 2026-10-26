# P15 — Docker local

Imágenes reconstruidas:

```powershell
docker compose build api ingestion-worker portal
docker compose up -d api ingestion-worker portal
```

Estado:

| Componente | Estado |
|---|---|
| `rag-api` | healthy |
| `rag-portal` | healthy |
| `rag-ingestion-worker` | running |
| PostgreSQL | healthy, Alembic `173` (P15 no migra) |
| `ZENT_GOLD_RELEASE_ENABLED` | `false` |

Verificación real contra Docker (`8080`):

- agente con propósito “Responde como un narrador de cuentos infantil”;
- preview con perfil Conciso y pregunta “¿Qué te parece El principito?”;
- respuesta: `identity=Narrador`, `intent=valuation`,
  `profile=concise`, `quality=Chequeos deterministas`,
  `semantic_evaluated=false`;
- el texto fue breve, con voz narrativa y sin rechazo;
- comparador real `analytical` vs `executive`: ambos `identity=Narrador`,
  `intent=valuation`, calidad `Chequeos deterministas`, sin fingir validación
  semántica;
- agentes de prueba eliminados al final.

No se ejecutó el juez semántico dentro del preview de Docker; el juez real se
ejecutó sobre las respuestas de la matriz y quedó registrado en
`artifacts/certification/p15/real-matrix-judged.json`.
