import {
  ArrowCounterClockwise,
  Copy,
  Play,
  SpinnerGap,
  Table,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { useToast } from "../Toast";

type SqlResult = {
  columns: string[];
  rows: (string | null)[][];
  count: number;
};

type SqlResponse =
  | ({ columns: string[]; rows: Record<string, string | null>[]; count: number })
  | { message: string; affected?: number };

export default function SqlRunnerModal({
  sql,
  onClose,
}: {
  sql: string;
  onClose: () => void;
}) {
  const { session } = useAuth();
  const { pushToast } = useToast();
  const [editable, setEditable] = useState(sql);
  const [result, setResult] = useState<SqlResult | null>(null);
  const [affected, setAffected] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    textareaRef.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function run() {
    if (!session || !editable.trim()) return;
    setRunning(true);
    setError("");
    setResult(null);
    setAffected(null);
    setMessage("");
    try {
      const data = await api<SqlResponse>("/api/v1/admin/sql", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ query: editable.trim() }),
      });
      if ("columns" in data) {
        setResult({
          columns: data.columns,
          rows: (data.rows || []).map((r) =>
            data.columns.map((c) => (r[c] === undefined ? null : r[c]))
          ),
          count: data.count ?? (data.rows || []).length,
        });
      } else {
        setMessage(data.message || "Consulta ejecutada.");
        if (data.affected !== undefined) setAffected(data.affected);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error ejecutando la consulta");
    } finally {
      setRunning(false);
    }
  }

  async function copySql() {
    try {
      await navigator.clipboard.writeText(editable);
      pushToast("success", "SQL copiado");
    } catch {
      pushToast("error", "No se pudo copiar");
    }
  }

  const modal = (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Ejecutar consulta SQL"
    >
      <div
        className="absolute inset-0 animate-fade-in bg-black/70 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden
      />
      <div className="panel relative flex max-h-[85dvh] w-full max-w-[860px] animate-page-in flex-col overflow-hidden shadow-pop">
        <header className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-text">
            <Table size={16} className="text-accent" aria-hidden />
            Ejecutar consulta
          </h2>
          <button
            type="button"
            className="cursor-pointer rounded-xs p-1.5 text-faint transition-colors hover:bg-soft hover:text-text"
            aria-label="Cerrar"
            onClick={onClose}
          >
            <X size={16} aria-hidden />
          </button>
        </header>

        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-5">
          <div className="field">
            <div className="flex items-center justify-between">
              <label htmlFor="sql-input">SQL (puedes editarlo antes de ejecutar)</label>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  className="btn btn-ghost px-2 py-1 text-xs"
                  onClick={() => setEditable(sql)}
                  disabled={editable === sql}
                  title="Restaurar la consulta original"
                >
                  <ArrowCounterClockwise size={13} aria-hidden />
                  Restaurar
                </button>
                <button
                  type="button"
                  className="btn btn-ghost px-2 py-1 text-xs"
                  onClick={() => void copySql()}
                  title="Copiar SQL"
                >
                  <Copy size={13} aria-hidden />
                  Copiar
                </button>
              </div>
            </div>
            <textarea
              id="sql-input"
              ref={textareaRef}
              rows={5}
              spellCheck={false}
              className="font-mono text-[13px] leading-relaxed"
              value={editable}
              onChange={(e) => setEditable(e.target.value)}
            />
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void run()}
              disabled={running || !editable.trim()}
            >
              {running ? (
                <>
                  <SpinnerGap size={15} className="animate-spin" aria-hidden />
                  Ejecutando…
                </>
              ) : (
                <>
                  <Play size={15} weight="fill" aria-hidden />
                  Ejecutar
                </>
              )}
            </button>
            <span className="text-[11.5px] text-faint">
              Solo SELECT · máx. 500 filas · deshabilitado en producción
            </span>
          </div>

          {error && (
            <div
              className="flex items-start gap-2 rounded-md border border-danger/25 bg-danger-soft px-3 py-2.5 text-[13px] text-danger"
              role="alert"
            >
              <WarningCircle size={16} className="mt-0.5 shrink-0" aria-hidden />
              <span className="min-w-0 break-words">{error}</span>
            </div>
          )}

          {message && (
            <div
              className="rounded-md border border-ok/25 bg-ok-soft px-3 py-2.5 text-[13px] text-ok"
              role="status"
            >
              {message}
              {affected !== null && (
                <span className="mono ml-1 text-[12px]">
                  · {affected.toLocaleString("es-PE")} filas afectadas
                </span>
              )}
            </div>
          )}

          {result && (
            <div className="min-w-0">
              <div className="mb-2 flex items-center justify-between">
                <p className="text-xs text-faint">
                  <span className="mono text-muted">{result.count.toLocaleString("es-PE")}</span>{" "}
                  filas ·{" "}
                  <span className="mono text-muted">{result.columns.length}</span> columnas
                </p>
              </div>
              <div className="max-h-[340px] overflow-auto rounded-sm border border-border bg-bg/50">
                <table className="table min-w-full text-[12.5px]">
                  <thead className="sticky top-0 bg-surface">
                    <tr>
                      <th className="mono w-10 text-center text-faint">#</th>
                      {result.columns.map((c) => (
                        <th key={c} className="mono">
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.rows.map((row, i) => (
                      <tr key={i}>
                        <td className="mono w-10 text-center text-faint">{i + 1}</td>
                        {row.map((cell, j) => (
                          <td
                            key={j}
                            className="mono max-w-[260px] truncate"
                            title={cell ?? undefined}
                          >
                            {cell ?? <span className="text-faint">NULL</span>}
                          </td>
                        ))}
                      </tr>
                    ))}
                    {result.rows.length === 0 && (
                      <tr>
                        <td
                          colSpan={result.columns.length + 1}
                          className="text-center text-faint"
                        >
                          La consulta no devolvió filas.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );

  return createPortal(modal, document.body);
}
