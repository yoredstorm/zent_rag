# P16 — Docker local

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
| PostgreSQL | healthy, Alembic `173` |
| `ZENT_GOLD_RELEASE_ENABLED` | `false` |

Verificación real del endpoint en Docker:

- agente con `purpose` guardado y perfil `technical_detailed`;
- POST con `purpose` sin guardar `"Responde como un narrador de cuentos infantil"`,
  `instructions` sin guardar y `mode=expand`;
- resultado: `source=model`, `mode=expand`, `quality.passed=true`,
  `persona.role="Narrador de cuentos infantiles"`,
  `persona.audience="infantil"`;
- propósito de 979 caracteres e instrucciones de 2452 caracteres;
- no se guardó el agente; el registro de prueba se eliminó al final.

La generación no modificó workflows publicados ni instancias durables.

Verificación responsive de la propuesta con un `intent_summary` largo (825,
1024, 1280 y 1440 px): `scrollWidth == clientWidth` en el panel, el textarea y
el documento. El contenedor scrolleable del Agent Studio ahora usa una columna
`minmax(0, 1fr)` explícita, así no se dimensiona al contenido más largo.
