# Criterios de accesibilidad del estudio

El estudio es una sola superficie: describir con IA, partir de una plantilla o crear a mano abren el mismo lienzo. Simple, Guiado y Avanzado cambian el detalle, no el producto.

## Criterios

- Un encabezado pregunta qué debe hacer ZENT y tres acciones con nombre propio llegan al mismo modelo de grafo.
- La ficha de misión se edita con campos. El JSON no es la vista primaria.
- El foco visible usa el anillo del design system. Los controles de la portada y de la ficha tienen etiqueta.
- Un bloqueo crítico se nombra («Requiere configuración»). No se muestra un porcentaje si el flujo no puede publicarse.
- La biblioteca de negocio usa verbos en español: Entender, Consultar, Decidir, Esperar, Actuar, Controlar, Finalizar.
- Marketplace en el lienzo dice Instaladas, Disponibles y Añadir. No mezcla inglés de producto.
- Guardar con `Ctrl+S` o `Cmd+S`. Si la red falla o el servidor responde 409, el grafo local permanece y la pantalla dice qué hacer.
- Un borrador local de un guardado fallido se puede recuperar al volver a abrir el flujo.
- El lienzo en pantalla estrecha conserva el panel de prueba detrás de «Probar» y no abre un segundo editor.

## Qué cubre la prueba automática

- `WorkflowNew.test.tsx`: los tres destinos.
- `MissionCard.test.tsx`: edición por campos.
- `WorkflowHealthBar.test.tsx`: bloqueo sin porcentaje.
- `NodeLibrary.test.tsx`: grupos por propósito.
- `e2e/workflows.spec.ts`: la portada antes de entrar al lienzo manual.
