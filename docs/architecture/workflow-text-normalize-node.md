# Nodo Normalizar texto

Herramienta determinista para preparar un texto antes de buscar, validar o
comparar. No consulta fuentes, no usa un LLM y no inventa datos. Todo se
configura desde el nodo.

## Cuándo usarlo

- Una pregunta de chat debe convertirse en términos de búsqueda.
- El texto puede traer saludos, artículos, unidades o frases de venta.
- Se necesita extraer un correo o limpiar un nombre.
- El siguiente paso espera un texto limpio, no la frase completa del cliente.

## Campos

| Campo | Tipo | Uso |
| --- | --- | --- |
| `text` | texto | Texto de entrada. Normalmente `{{trigger.text}}`. |
| `mode` | enum | `product_query`, `email`, `name` o `free`. |
| `ignore_phrases` | texto | Frases extra separadas por coma. |
| `lowercase` | sí/no | Convierte a minúsculas. |
| `strip_accents` | sí/no | Quita acentos antes de comparar. |
| `max_terms` | número | Límite de términos de salida. |

## Modos

- `product_query`: quita preguntas, artículos, unidades y frases de venta.
  Ejemplo: `tienes bicicleta en venta?` devuelve `bicicleta`.
- `email`: extrae la primera dirección de correo.
- `name`: limpia puntuación y espacios; puede conservar mayúsculas y acentos.
- `free`: solo colapsa espacios y aplica las frases configuradas.

## Salidas

- `text`: texto normalizado.
- `terms`: lista de términos.
- `original`: texto original.
- `removed`: términos descartados.
- `status`: `OK` o `EMPTY`.
- `mode`: modo aplicado.

## Ejemplo en Bodega

1. `Entrada · Guardar cliente y pedido`
2. `Producto · Preparar búsqueda` con:
   - `text`: `{{trigger.text}}`
   - `mode`: `product_query`
   - `ignore_phrases`: `en venta, venden, productos`
3. `Producto · Buscar catálogo` con:
   - `query`: `{{nodes.normalizar_busqueda.output.text}}`

Así la búsqueda recibe `bicicleta` aunque el cliente escriba
`tienes bicicleta en venta?`.
