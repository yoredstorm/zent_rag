function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function Scalar({ value }: { value: unknown }) {
  if (value === null) return <span className="text-faint">null</span>;
  if (value === undefined) return <span className="text-faint">no disponible</span>;
  if (typeof value === "boolean") {
    return <span className="text-text">{value ? "true" : "false"}</span>;
  }
  return <span className="break-words text-text">{String(value)}</span>;
}

function Branch({ label, value, depth }: { label: string; value: unknown; depth: number }) {
  if (!isRecord(value) && !Array.isArray(value)) {
    return (
      <div className="grid grid-cols-[minmax(7rem,0.8fr)_minmax(0,1.2fr)] gap-3 border-b border-border-soft py-1.5 last:border-0">
        <dt className="break-words text-faint">{label}</dt>
        <dd className="min-w-0 mono text-[11px]">
          <Scalar value={value} />
        </dd>
      </div>
    );
  }

  const entries = Array.isArray(value)
    ? value.map((item, index) => [String(index + 1), item] as const)
    : Object.entries(value);
  return (
    <details open={depth === 0} className="border-b border-border-soft py-1.5 last:border-0">
      <summary className="cursor-pointer break-words text-[11.5px] text-accent">
        {label} <span className="text-faint">({entries.length})</span>
      </summary>
      <dl className="mt-1 border-l border-border pl-2">
        {entries.length ? (
          entries.map(([key, item]) => (
            <Branch key={key} label={key} value={item} depth={depth + 1} />
          ))
        ) : (
          <div className="py-1 text-[11px] text-faint">Sin valores</div>
        )}
      </dl>
    </details>
  );
}

export function TechnicalValueTree({ value }: { value: unknown }) {
  if (!isRecord(value) && !Array.isArray(value)) return <Scalar value={value} />;
  const entries = Array.isArray(value)
    ? value.map((item, index) => [String(index + 1), item] as const)
    : Object.entries(value);
  return (
    <dl className="min-w-0 text-[11.5px]">
      {entries.map(([key, item]) => (
        <Branch key={key} label={key} value={item} depth={0} />
      ))}
    </dl>
  );
}

export default TechnicalValueTree;
