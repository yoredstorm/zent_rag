import DOMPurify from "dompurify";
import { marked } from "marked";

marked.setOptions({ gfm: true, breaks: true });

// La salida del LLM es influenciable por contenido ingerido (indirect prompt
// injection). SIEMPRE sanitizar antes de inyectar en el DOM (anti XSS).
export function renderMarkdownHtml(text: string): { __html: string } {
  const raw = marked.parse(text, { async: false }) as string;
  const clean = DOMPurify.sanitize(raw, {
    ALLOWED_TAGS: [
      "p", "br", "strong", "em", "b", "i", "u", "s", "code", "pre",
      "ul", "ol", "li", "blockquote", "h1", "h2", "h3", "h4", "h5",
      "h6", "a", "table", "thead", "tbody", "tr", "th", "td", "hr",
      "span", "div",
    ],
    ALLOWED_ATTR: ["href", "title", "colspan", "rowspan"],
    ALLOW_DATA_ATTR: false,
  });
  return { __html: clean };
}
