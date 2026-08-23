# Tools

No hay un REST de tools. Las tools se declaran al crear/editar el agente:

```json
{ "name": "Soporte", "tools": ["search_knowledge"] }
```

El runtime carga tools builtin y módulos verticales. Nombres inválidos se rechazan en el servidor. Ver [agents](agents.md).
