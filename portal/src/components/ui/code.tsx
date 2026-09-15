import { Check, Copy } from "@phosphor-icons/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "./cn";

/** Botón de copiar con confirmación momentánea (microinteracción, no toast). */
export function CopyButton({
  value,
  label = "Copiar",
  copiedLabel = "Copiado",
  className,
  variant = "ghost",
}: {
  value: string;
  label?: string;
  copiedLabel?: string;
  className?: string;
  variant?: "ghost" | "secondary";
}) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      // Fallback para contextos sin permiso de clipboard
      const ta = document.createElement("textarea");
      ta.value = value;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
      } finally {
        document.body.removeChild(ta);
      }
    }
    setCopied(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <button
      type="button"
      onClick={() => void copy()}
      className={cn(
        "btn btn-sm",
        variant === "secondary" ? "btn-secondary" : "btn-ghost",
        className
      )}
      aria-label={copied ? copiedLabel : label}
    >
      {copied ? (
        <Check size={13} weight="bold" className="text-ok" aria-hidden />
      ) : (
        <Copy size={13} aria-hidden />
      )}
      <span className="sr-only" aria-live="polite">
        {copied ? copiedLabel : label}
      </span>
    </button>
  );
}

export type CodeBlockProps = {
  code: string;
  language?: string;
  filename?: string;
  /** Altura máxima antes de scroll interno. */
  maxHeight?: number;
  showLineNumbers?: boolean;
  actions?: ReactNode;
  className?: string;
};

/** Bloque de código con lenguaje identificable, copia y scroll contenido. */
export function CodeBlock({
  code,
  language,
  filename,
  maxHeight = 380,
  showLineNumbers = false,
  actions,
  className,
}: CodeBlockProps) {
  const lines = code.replace(/\n$/, "").split("\n");
  return (
    <figure
      className={cn(
        "overflow-hidden rounded-md border border-border bg-control",
        className
      )}
    >
      <figcaption className="flex items-center justify-between gap-3 border-b border-border px-3 py-2">
        <span className="flex min-w-0 items-center gap-2">
          {filename && <span className="truncate font-mono text-xs text-muted">{filename}</span>}
          <span className="badge badge-muted">{language || "text"}</span>
        </span>
        <span className="flex shrink-0 items-center gap-1.5">
          {actions}
          <CopyButton value={code} />
        </span>
      </figcaption>
      <div className="overflow-auto" style={{ maxHeight }}>
        <pre className="p-3 font-mono text-[12.5px] leading-relaxed">
          <code>
            {showLineNumbers
              ? lines.map((line, i) => (
                  <span key={i} className="flex">
                    <span className="mr-3 w-7 shrink-0 text-right text-ghost select-none" aria-hidden>
                      {i + 1}
                    </span>
                    <span className="min-w-0 whitespace-pre">{line || " "}</span>
                  </span>
                ))
              : code}
          </code>
        </pre>
      </div>
    </figure>
  );
}

/** Tecla o atajo de teclado. */
export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return <kbd className={cn("kbd", className)}>{children}</kbd>;
}

/** Par clave/valor para paneles de detalle técnico. */
export function KeyValue({
  items,
  className,
  columns = 1,
}: {
  items: { key: string; value: ReactNode; mono?: boolean }[];
  className?: string;
  columns?: 1 | 2;
}) {
  return (
    <dl className={cn("grid gap-x-6 gap-y-3", columns === 2 && "sm:grid-cols-2", className)}>
      {items.map((item) => (
        <div key={item.key} className="min-w-0">
          <dt className="eyebrow">{item.key}</dt>
          <dd className={cn("mt-1 min-w-0 text-[13px] break-words text-text", item.mono && "mono text-xs")}>
            {item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
