export type UnderstandingTreeNode = {
  type?: string;
  heading?: string;
  text?: string;
  children?: UnderstandingTreeNode[];
};

export type UnderstandingPayload = {
  mode?: string;
  pipeline_state?: string;
  report?: {
    document?: string;
    pages?: number;
    sections?: number;
    tables?: number;
    figures?: number;
    definitions?: number;
    technical_fields?: number;
    exact_literals?: number;
    cross_references?: number;
    ocr_pages?: number[];
    warnings?: string[];
    extraction_quality?: number;
    pipeline_state?: string;
  };
  tree?: {
    title?: string;
    children?: UnderstandingTreeNode[];
  };
};

function count(value: number | undefined): string {
  return String(value ?? 0);
}

function TreeList({ nodes }: { nodes: UnderstandingTreeNode[] }) {
  if (nodes.length === 0) return null;
  return (
    <ul className="ml-3 list-disc space-y-0.5 text-[12px] text-zinc-600">
      {nodes.map((node, index) => (
        <li key={`${node.type || "n"}-${index}`}>
          <span className="font-medium text-zinc-800">{node.heading || node.type}</span>
          {node.text ? <span className="text-zinc-500"> · {node.text}</span> : null}
          {node.children && node.children.length > 0 ? <TreeList nodes={node.children} /> : null}
        </li>
      ))}
    </ul>
  );
}

/** Informe de ingesta. Texto plano: no interpreta markdown como HTML. */
export function UnderstandingReport({ data }: { data: UnderstandingPayload }) {
  const report = data.report;
  if (!report) return null;
  const state = report.pipeline_state || data.pipeline_state || "READY";
  const quality =
    typeof report.extraction_quality === "number"
      ? `${Math.round(report.extraction_quality * 100)}%`
      : "—";
  const warnings = report.warnings || [];
  return (
    <section
      data-testid="understanding-report"
      className="mt-2 rounded-md border border-zinc-200 bg-zinc-50 p-3"
    >
      <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
        Documento {report.document || "sin título"} · {state}
      </p>
      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[12px] text-zinc-700 sm:grid-cols-4">
        <div>Páginas {count(report.pages)}</div>
        <div>Secciones {count(report.sections)}</div>
        <div>Tablas {count(report.tables)}</div>
        <div>Figuras {count(report.figures)}</div>
        <div>Definiciones {count(report.definitions)}</div>
        <div>Campos {count(report.technical_fields)}</div>
        <div>Literales {count(report.exact_literals)}</div>
        <div>Calidad {quality}</div>
      </dl>
      {(report.ocr_pages || []).length > 0 ? (
        <p className="mt-2 text-[12px] text-zinc-500">
          OCR en páginas {report.ocr_pages?.join(", ")}
        </p>
      ) : null}
      {warnings.length > 0 ? (
        <ul className="mt-2 list-disc pl-4 text-[12px] text-amber-800">
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}
      <details className="mt-2">
        <summary className="cursor-pointer text-[12px] font-medium text-indigo-700">
          Estructura
        </summary>
        <div className="mt-1">
          <TreeList nodes={data.tree?.children || []} />
        </div>
      </details>
    </section>
  );
}
