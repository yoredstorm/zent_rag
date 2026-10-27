# P0 — ACL del chat grounded

**HEAD base:** `11aeec7`.
**Estado:** corregido; pendiente de CI.

## Hallazgo

`src/api/routes/knowledge_workspaces.py` hacía:

```python
role = str(getattr(ctx, "role", "admin"))
```

`TenantContext` no expone `role`; el fallback `"admin"` se aplicaba a todos los
usuarios. El retrieval de Qdrant usa `role != "admin"` para activar el filtro
de visibilidad/ACL. El resultado era un bypass de ACL dentro de la misma
organización y workspace.

## Corrección

```python
role = "admin" if ctx.is_organization_admin() else "user"
```

`TenantContext.is_organization_admin()` es la autoridad real: roles owner/admin
o scope `admin:*`. No se cambia la semántica ACL ni el pipeline.

## Pruebas

`tests/test_knowledge_workspaces_api.py`:

- reader → `RetrievalQuery.role == "user"`.
- owner → `RetrievalQuery.role == "admin"`.
- el contrato del chat vacío sigue respondiendo.

Las pruebas negativas de ACL de Qdrant siguen en
`tests/test_hybrid_retrieval.py` y `tests/test_structured_retriever.py`.

## Fuera de alcance

`src/platform/cognitive.py:102` tiene un patrón similar; se registra como P0
separado. No se mezcla en este PR para no cambiar el runtime cognitivo.

## Rollback

Revertir el cambio y las pruebas. Sin migración.
