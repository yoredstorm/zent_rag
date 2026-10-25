# 15 — API keys de desarrollo y exposición temporal

Fecha: `2026-10-24`. Extiende P00–P12 sin crear otro sistema de auth.

## 1. Qué existe

- `POST /api/v1/organizations/api-keys` crea claves con `environment: live|test`.
- Las claves `test` usan prefijo `zent_sk_test_` y **expiran a las 24 h**.
- Las claves `live` usan `zent_sk_live_` y no expiran por este mecanismo (pueden
  rotarse o revocarse).
- Una clave `test` **no puede consultar un deployment cuyo entorno sea
  `production`**. El endpoint responde 403.
- El endpoint de agente desplegado es
  `POST /api/v1/deployments/{slug}/query`; requiere `Authorization: Bearer
  zent_sk_...` con scope/permiso `agents:execute`.

## 2. Flujo de prueba externa

1. Crear una versión del agente y publicarla en entorno `development` o
   `staging`.
2. En **API Keys**, crear una clave **Development**.
3. Copiar el endpoint del deployment y la clave; la clave vence en 1 día.
4. Al vencer, el middleware devuelve 401 y hay que crear/rotar otra.
5. Para producción, desplegar en entorno `production` y usar una clave `live`
   (o la que emita la organización); el endpoint no es anónimo.

## 3. Workflows

El hook público de workflow no usa API keys: usa
`X-Zent-Workflow-Secret` y exige workflow activo. No existe una “clave de
workflow de 1 día” separada; para una prueba temporal se puede rotar el hook
secret y volver a rotarlo al terminar. El secreto se muestra solo en la
creación/rotación.

## 4. Límites

- Una clave de desarrollo no es un entorno de datos separado: comparte datos
  del tenant, con cuota menor y bloqueo de deployments productivos.
- No hay endpoint anónimo permanente. “Solo endpoint” no es suficiente sin
  credencial.
- WhatsApp sigue necesitando un middleware externo que llame al hook/endpoint.
