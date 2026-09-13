import { ArrowUp, Lightning, Warning } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import type { GraphIssue } from "../../lib/workflowGraph";
import { ErrorInline, Spinner } from "../ui";
import { WorkflowRunInspector, type RunDetail } from "../WorkflowRunInspector";
import { STATUS_BADGE, answerFromSteps, normalizeTestPayload, type WorkflowRun } from "./types";

type Props = {
  workflowId: string;
  status: string;
  /** Nodos de escritura del grafo: se confirman antes de ejecutar de verdad. */
  effectLabels: string[];
  /** Avisos del grafo (nodo `llm` sin agente, etc.). */
  issues: GraphIssue[];
  dirty: boolean;
  /** Alimenta el overlay del lienzo con el run recién hecho. */
  onRun: (run: RunDetail | null) => void;
  onSelectNode: (id: string) => void;
  onRan?: () => void;
  /**
   * Persiste el grafo antes de correr. El motor ejecuta la versión guardada:
   * sin esto el usuario prueba lo que hay en el servidor, no lo que ve.
   */
  onSaveBeforeRun?: () => Promise<boolean>;
};

type RunOut = {
  run_id: string;
  status: string;
  planned_effects?: { node_id: string; node_type: string; planned: Record<string, unknown> }[];
  result?: unknown;
};

type Message =
  | { role: "user"; text: string }
  | { role: "agent"; text: string; echo: boolean; node_id: string | null }
  | { role: "system"; text: string; tone: "info" | "danger" };

export function WorkflowTestPanel({
  workflowId,
  status,
  effectLabels,
  issues,
  dirty,
  onRun,
  onSelectNode,
  onRan,
  onSaveBeforeRun,
}: Props) {
  const { session } = useAuth();
  const [raw, setRaw] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [planned, setPlanned] = useState<RunOut["planned_effects"]>(undefined);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const feedRef = useRef<HTMLDivElement>(null);

  const normalized = normalizeTestPayload(raw);

  const loadRuns = useCallback(async () => {
    if (!session) return;
    try {
      const d = await api<{ runs: WorkflowRun[] }>(`/api/v1/workflows/${workflowId}/runs`, {
        token: session.token,
        organizationId: session.organizationId,
      });
      setRuns(d.runs || []);
    } catch {
      setRuns([]);
    }
  }, [session, workflowId]);

  useEffect(() => {
    setRun(null);
    setPlanned(undefined);
    setMessages([]);
    void loadRuns();
  }, [loadRuns]);

  useEffect(() => {
    const feed = feedRef.current;
    if (feed) feed.scrollTop = feed.scrollHeight;
  }, [messages, run]);

  function push(msg: Message) {
    setMessages((prev) => [...prev, msg]);
  }

  async function execute(simulate: boolean) {
    if (!session || busy) return;
    if (!simulate && effectLabels.length > 0) {
      const ok = window.confirm(
        `Ejecutar de verdad va a disparar ${effectLabels.length} nodo(s) con efectos reales: ` +
          `${effectLabels.join(", ")}. ¿Continuar?`,
      );
      if (!ok) return;
    }
    const asked = raw.trim();
    setBusy(simulate ? "test" : "run");
    setError("");
    if (asked) push({ role: "user", text: asked });
    try {
      if (dirty && onSaveBeforeRun) {
        const saved = await onSaveBeforeRun();
        if (!saved) {
          push({
            role: "system",
            text: "No pude guardar el grafo, así que no ejecuto: correría una versión vieja.",
            tone: "danger",
          });
          return;
        }
      }
      const out = await api<RunOut>(`/api/v1/workflows/${workflowId}/run`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ payload: normalized.payload, simulate }),
      });
      setPlanned(simulate ? out.planned_effects : undefined);
      const detail = await api<RunDetail>(`/api/v1/workflows/runs/${out.run_id}`, {
        token: session.token,
        organizationId: session.organizationId,
      });
      setRun(detail);
      onRun(detail);
      const answer = answerFromSteps(detail.steps);
      if (answer?.error) {
        push({ role: "system", text: answer.error, tone: "danger" });
      } else if (answer) {
        push({ role: "agent", text: answer.text, echo: answer.echo, node_id: answer.node_id });
      } else {
        push({
          role: "system",
          text:
            detail.error ||
            `El flujo terminó en ${out.status} sin texto de respuesta. Conecta un nodo “Preguntar a un agente” al trigger.`,
          tone: "info",
        });
      }
      await loadRuns();
      if (!simulate) onRan?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function showRun(runId: string) {
    if (!session) return;
    try {
      const detail = await api<RunDetail>(`/api/v1/workflows/runs/${runId}`, {
        token: session.token,
        organizationId: session.organizationId,
      });
      setPlanned(undefined);
      setRun(detail);
      onRun(detail);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  return (
    <section
      className="flex min-h-0 w-full flex-col overflow-hidden rounded-lg border border-border bg-surface"
      data-testid="wf-test-panel"
      aria-label="Probar el workflow"
    >
      <header className="flex items-center gap-2 border-b border-border px-3 py-2.5">
        <h2 className="flex-1 text-[13px] font-semibold text-text">Probar</h2>
        {dirty && (
          <span className="badge badge-pending" title="El motor corre la versión guardada">
            se guarda al probar
          </span>
        )}
      </header>

      <div ref={feedRef} className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {messages.length === 0 && (
          <div className="rounded-md border border-border bg-soft px-3 py-2.5 text-[11px] text-muted">
            <p className="font-medium text-text">Escribe una pregunta y pulsa Probar.</p>
            <p className="mt-1">
              El texto llega a los nodos como{" "}
              <code className="font-mono text-text">{"{{trigger.message}}"}</code>. Los nodos de
              lectura (agente, knowledge base, datos) corren de verdad; los de escritura solo se
              simulan hasta que uses “Ejecutar de verdad”.
            </p>
          </div>
        )}

        {issues.length > 0 && (
          <div className="rounded-md border border-warn/40 bg-warn-soft px-3 py-2 text-[11px]" data-testid="wf-issues">
            <p className="flex items-center gap-1 font-medium text-text">
              <Warning size={13} aria-hidden /> Revisa el grafo
            </p>
            <ul className="mt-1 space-y-1">
              {issues.map((i) => (
                <li key={`${i.node_id}-${i.message}`}>
                  <button
                    type="button"
                    className="text-left text-muted hover:text-text"
                    onClick={() => onSelectNode(i.node_id)}
                    data-testid="wf-issue-jump"
                  >
                    <span className="font-medium text-text">{i.label}</span>: {i.message}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {messages.map((m, idx) =>
          m.role === "user" ? (
            <p
              key={idx}
              className="ml-auto max-w-[85%] rounded-lg rounded-br-none bg-accent-soft px-3 py-2 text-[12px] text-text"
              data-testid="wf-chat-user"
            >
              {m.text}
            </p>
          ) : m.role === "agent" ? (
            <div key={idx} className="max-w-[90%]">
              <p
                className="rounded-lg rounded-bl-none border border-border bg-soft px-3 py-2 text-[12px] whitespace-pre-wrap text-text"
                data-testid="wf-chat-answer"
              >
                {m.text}
              </p>
              {m.echo && (
                <p className="mt-1 text-[10px] text-warn" data-testid="wf-chat-echo">
                  Es un eco: el nodo no tiene agente asignado.
                </p>
              )}
              {m.node_id && (
                <button
                  type="button"
                  className="mt-1 text-[10px] text-faint hover:text-accent"
                  onClick={() => onSelectNode(m.node_id!)}
                >
                  ver el nodo en el lienzo
                </button>
              )}
            </div>
          ) : (
            <p
              key={idx}
              className={`rounded-md border px-3 py-2 text-[11px] ${
                m.tone === "danger" ? "border-danger/40 bg-danger-soft text-danger" : "border-border bg-soft text-muted"
              }`}
              data-testid="wf-chat-system"
            >
              {m.text}
            </p>
          ),
        )}

        {run && (
          <details className="rounded-md border border-border bg-soft/60 px-2 py-1.5" open>
            <summary className="cursor-pointer text-[11px] font-medium text-muted">
              Pasos del flujo ({run.steps?.length ?? 0})
            </summary>
            <div className="mt-2">
              <WorkflowRunInspector run={run} plannedEffects={planned} onSelectNode={onSelectNode} />
            </div>
          </details>
        )}

        {runs.length > 0 && (
          <details className="rounded-md border border-border px-2 py-1.5">
            <summary className="cursor-pointer text-[11px] font-medium text-muted">
              Runs recientes ({runs.length})
            </summary>
            <div className="mt-1.5 space-y-1">
              {runs.slice(0, 8).map((r) => (
                <button
                  key={r.id}
                  type="button"
                  className="flex w-full items-center gap-2 rounded-md bg-soft px-2 py-1.5 text-left text-[10px] hover:bg-raised"
                  onClick={() => void showRun(r.id)}
                >
                  <span className={`badge ${STATUS_BADGE[r.status] ?? "badge-muted"}`}>{r.status}</span>
                  <span className="min-w-0 flex-1 truncate text-text">
                    {new Date(r.started_at).toLocaleTimeString()}
                  </span>
                  <span className="text-faint">{r.duration_ms != null ? `${r.duration_ms}ms` : "—"}</span>
                </button>
              ))}
            </div>
          </details>
        )}
      </div>

      <footer className="space-y-2 border-t border-border p-3">
        <ErrorInline message={error} />
        <div className="flex items-end gap-2">
          <textarea
            className="min-h-11 w-full flex-1 resize-none rounded-md border border-border bg-soft px-2.5 py-2.5 text-[12px]"
            rows={2}
            placeholder="¿Quién es el gerente?"
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void execute(true);
              }
            }}
            data-testid="wf-test-payload"
            aria-label="Pregunta o payload de prueba"
          />
          <button
            type="button"
            className="btn btn-primary min-h-11 px-3"
            disabled={!!busy}
            onClick={() => void execute(true)}
            data-testid="wf-test"
            aria-label="Probar"
          >
            {busy === "test" ? <Spinner size={14} /> : <ArrowUp size={16} aria-hidden />}
          </button>
        </div>
        {normalized.wrapped && (
          <p className="text-[10px] text-faint" data-testid="wf-payload-wrapped">
            Se envía como <code className="font-mono text-muted">{JSON.stringify(normalized.payload)}</code>
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="btn btn-secondary min-h-9 px-2 text-[11px]"
            disabled={!!busy}
            onClick={() => void execute(false)}
            data-testid="wf-run"
          >
            {busy === "run" ? <Spinner size={13} /> : <Lightning size={14} aria-hidden />}
            Ejecutar de verdad
          </button>
          {effectLabels.length > 0 && (
            <span className="text-[10px] text-faint">
              {effectLabels.length} nodo(s) con efectos: {effectLabels.join(", ")}
            </span>
          )}
        </div>
        {status !== "active" && (
          <p className="text-[10px] text-faint">
            En <span className="font-medium text-muted">{status}</span>: las pruebas funcionan, pero
            el hook público y los schedules necesitan activarlo.
          </p>
        )}
      </footer>
    </section>
  );
}
