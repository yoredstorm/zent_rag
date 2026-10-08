# Plan de deprecación de pdfplumber

Estado actual: **Stage A** — OpenDataLoader es el parser PDF productivo;
pdfplumber sigue instalado y disponible como shadow/legacy, pero el runtime
productivo ya no lo necesita para el probe.

## Etapas

| Etapa | Acción | Criterio de salida |
| --- | --- | --- |
| **A (hoy)** | ODL producción; pdfplumber instalado; shadow disponible (`PDF_PARSER_MODE=shadow`). El probe de PDF usa `pdfminer.six` (sin importar pdfplumber). | Ningún camino productivo importa `pdfplumber` (excepto `PdfParser` legacy y el shadow). |
| **B** | 30+ días / corpus representativo con métricas ODL ≥ pdfplumber (reading order, headings, tablas, premisas, CanonicalRule precision, citas). | Reporte del benchmark (`parser_shadow_benchmark`, `bundle_benchmark`) sin regresiones y shadow sin hallazgos nuevos. |
| **C** | Reemplazar dependencias internas restantes del fallback (p. ej. cualquier probe/altura de página/tags). | Ningún módulo de `src/` importa `pdfplumber` en runtime productivo; el probe ya es pdfminer (hecho en Stage A). |
| **D** | Mover `pdfplumber` a dependencia opcional de parser-lab/dev (`[project.optional-dependencies]`). | Import perezoso + tests de parser lab marcados como opcionales. |
| **E** | Quitar pdfplumber de la imagen productiva si no queda ningún `import pdfplumber` alcanzable. | `rg "import pdfplumber" src/` sin resultados productivos. |

## Reglas

- **No desinstalar por estética**: cada etapa exige evidencia de la etapa previa.
- El **shadow nunca duplica Knowledge Objects**: pdfplumber solo compara
  (`ShadowPdfParser._evaluate_and_record`); la persistencia, compilación e
  indexado son exclusivamente del lado ODL de producción.
- El probe de página/tags del parser ODL (`probe_pdf`) usa `pdfminer.six`,
  que ya era dependencia transitiva y sobrevive a la remoción de pdfplumber.
- Markdown/generación LLM no cambia este plan: JSON sigue siendo la autoridad
  estructural y el parser legacy no participa de la representación dual.
