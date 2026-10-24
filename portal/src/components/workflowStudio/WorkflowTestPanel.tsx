import { ArrowUp, Lightning, MagicWand, Warning } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { effectNodes, nodeMeta } from "../../lib/workflowGraph";
import type { GraphIssue, WorkflowGraph } from "../../lib/workflowGraph";
import {
  classifyPlannedEffects,
  effectLabel,
  type EffectVerification,
  type EffectVerificationItem,
} from "../../lib/workflowEffects";
import { humanizeWorkflowError } from "../../lib/workflowErrors";
import { Button, ErrorInline, StatusBadge, Textarea } from "../ui";
import { WorkflowRunInspector, type RunDetail } from "../WorkflowRunInspector";
import { answerFromSteps, normalizeTestPayload, type WorkflowRun } from "./types";

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
  /** Grafo actual: genera ejemplos de prueba coherentes con el flujo. */
  graph?: WorkflowGraph | null;
  /** El estudio lo monta dentro del Drawer inferior: oculta el encabezado propio. */
  embedded?: boolean;
};

type RunOut = {
  run_id: string;
  status: string;
  planned_effects?: { node_id: string; node_type: string; planned: Record<string, unknown> }[];
  effect_verification?: EffectVerification;
  result?: unknown;
};

type TestReportOut = {
  test_report_id?: string;
  requested_level: string;
  effective_level: string;
  capped_reason?: string | null;
  provider_verified: boolean;
  result: string;
  state?: string;
  why?: string;
  hashes?: Record<string, string>;
  timeline?: unknown[];
  executed_nodes?: unknown[];
  report_id?: string;
};

const TEST_LEVELS = [
  { id: "preview", label: "Preview teórico" },
  { id: "simulation", label: "Simulación determinista" },
  { id: "sandbox", label: "Prueba sandbox" },
  { id: "provider", label: "Certificación con proveedor" },
] as const;

type TestLevel = (typeof TEST_LEVELS)[number]["id"];

const UNAVAILABLE_LEVELS: Partial<Record<TestLevel, string>> = {
  sandbox: "Sandbox real no está conectado en este panel. No simulo un pase.",
  provider: "Certificación con proveedor real no está conectada. No simulo un pase.",
};

const ROLE_EXAMPLES: { id: string; label: string; message: string }[] = [
  { id: "ventas", label: "Ventas", message: "Quiero un kilo de arroz" },
  { id: "mentor", label: "Mentor", message: "Ahora quiero restas" },
  { id: "tutor", label: "Tutor", message: "Creo que 2+2 es 5" },
  { id: "auditor", label: "Auditor", message: "Las dos fuentes no coinciden" },
  { id: "soporte", label: "Soporte", message: "La base no responde mi caso" },
  { id: "bienestar", label: "Bienestar", message: "Dime qué enfermedad tengo" },
];

type Message =
  | { role: "user"; text: string }
  | { role: "agent"; text: string; echo: boolean; node_id: string | null }
  | { role: "system"; text: string; tone: "info" | "warn" | "danger" };

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
  graph,
  embedded = false,
}: Props) {
  const { session } = useAuth();
  const [raw, setRaw] = useState("");
  const [level, setLevel] = useState<TestLevel>("simulation");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [planned, setPlanned] = useState<RunOut["planned_effects"]>(undefined);
  const [testReport, setTestReport] = useState<TestReportOut | null>(null);
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
    setTestReport(null);
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

  function generateSample() {
    const conversational = graph?.nodes.some(
      (n) => n.type === "llm" || n.type === "kb_query" || n.type === "query_business_data",
    );
    setRaw(
      JSON.stringify(
        conversational ? { message: "¿Cuál es el stock actual?" } : { message: "ejemplo" },
      ),
    );
  }

  async function loadLastSample() {
    if (!session) return;
    setError("");
    try {
      const data = await api<{ run_id?: string | null; trigger_payload?: Record<string, unknown> }>(
        `/api/v1/workflows/${workflowId}/sample-outputs`,
        { token: session.token, organizationId: session.organizationId },
      );
      const payload = data.trigger_payload ?? {};
      if (data.run_id && Object.keys(payload).length > 0) {
        setRaw(JSON.stringify(payload));
      } else {
        setError("Todavía no hay una prueba anterior con datos; usa «Generar ejemplo».");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function executeTest() {
    if (!session || busy) return;
    const asked = raw.trim();
    setBusy("test");
    setError("");
    setTestReport(null);
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
      const report = await api<TestReportOut>(`/api/v1/workflows/${workflowId}/test`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          requested_level: level,
          scenario: {
            scenario_id: "studio",
            messages: asked ? [asked] : [],
            max_segments: 8,
          },
        }),
      });
      setTestReport(report);
      const steps = (report.executed_nodes ?? []).map((raw, index) => {
        const item = (raw ?? {}) as Record<string, unknown>;
        return {
          step_index: index,
          step_type: String(item.type ?? item.node_type ?? "node"),
          node_id: item.node_id ? String(item.node_id) : null,
          node_type: item.node_type ? String(item.node_type) : null,
          status: String(item.status ?? "simulated"),
          output: (item.output as Record<string, unknown> | undefined) ?? {},
          error: item.error ? String(item.error) : null,
        };
      });
      const testRun: RunDetail = {
        id: report.test_report_id ?? report.report_id ?? "test-report",
        status: report.result.toLowerCase(),
        steps,
        result: {},
      };
      setRun(testRun);
      onRun(testRun);
      const requested = report.requested_level;
      const effective = report.effective_level;
      const result = report.result;
      if (result === "PREVIEW") {
        const plannedLabels = graph
          ? effectNodes(graph).map((node) => node.label || nodeMeta(node.type).label)
          : [];
        push({
          role: "system",
          text:
            plannedLabels.length > 0
              ? `Preview teórico. No ejecuta efectos y no es un pase. Efectos previstos: ${plannedLabels.join(", ")}.`
              : "Preview teórico. No ejecuta efectos y no es un pase.",
          tone: "info",
        });
      } else if (requested !== effective) {
        push({
          role: "system",
          text: `Nivel ${requested} no está conectado (${report.capped_reason ?? "sin adaptador"}). El servidor ejecutó ${effective}; no acredita proveedor real.`,
          tone: "danger",
        });
      } else if (result === "UNVERIFIED") {
        push({
          role: "system",
          text: report.why || "UNVERIFIED: falta un doble o proveedor real. No es PASSED.",
          tone: "danger",
        });
      } else if (result === "PASSED") {
        push({
          role: "system",
          text: `PASSED en ${effective} determinista. No certifica proveedor real ni publica solo.`,
          tone: "info",
        });
      } else {
        push({
          role: "system",
          text: report.why || `El test terminó en ${result} en nivel ${effective}.`,
          tone: result === "FAILED" || result === "BLOCKED" ? "danger" : "warn",
        });
      }
      await loadRuns();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function execute(simulate: boolean) {
    if (!session || busy) return;
    if (simulate) {
      await executeTest();
      return;
    }
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
      if (simulate) {
        const verification =
          out.effect_verification ?? classifyPlannedEffects(out.planned_effects);
        const labels = (items: EffectVerificationItem[]) =>
          items.map((item) => effectLabel(item)).join(", ");
        if (verification.level === "UNVERIFIED") {
          push({
            role: "system",
            text: `UNVERIFIED: efecto externo sin doble en ${labels(verification.unverified)}. Fija la salida (doble declarado) o usa proveedor real. No es PASSED.`,
            tone: "danger",
          });
        } else if (verification.level === "DECLARED") {
          push({
            role: "system",
            text: `DECLARED: efecto fijado con datos de prueba en ${labels(verification.declared)}. No es PASSED; falta sandbox/proveedor.`,
            tone: "warn",
          });
        } else if (verification.level === "SIMULATED") {
          const verb =
            verification.simulated.length === 1
              ? "quedó en modo simulación"
              : "quedaron en modo simulación";
          push({
            role: "system",
            text: `SIMULADO: ${labels(verification.simulated)} ${verb}. No es PASSED.`,
            tone: "info",
          });
        }
      }
      const detail = await api<RunDetail>(`/api/v1/workflows/runs/${out.run_id}`, {
        token: session.token,
        organizationId: session.organizationId,
      });
      setRun(detail);
      onRun(detail);
      const answer = answerFromSteps(detail.steps);
      if (answer?.error) {
        push({ role: "system", text: humanizeWorkflowError(answer.error), tone: "danger" });
      } else if (answer) {
        push({ role: "agent", text: answer.text, echo: answer.echo, node_id: answer.node_id });
      } else {
        push({
          role: "system",
          text:
            humanizeWorkflowError(detail.error) ||
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
      className="panel flex min-h-0 w-full flex-col overflow-hidden"
      data-testid="wf-test-panel"
      aria-label="Probar el workflow"
    >
      {!embedded && (
        <header className="panel-header">
          <h2 className="text-h3">Probar automatización</h2>
          {dirty && (
            <span className="badge badge-pending" title="El motor corre la versión guardada">
              se guarda al probar
            </span>
          )}
        </header>
      )}

      <div ref={feedRef} className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {embedded && dirty && (
          <span className="badge badge-pending" title="El motor corre la versión guardada">
            se guarda al probar
          </span>
        )}
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
                m.tone === "danger"
                  ? "border-danger/40 bg-danger-soft text-danger"
                  : m.tone === "warn"
                    ? "border-warn/40 bg-warn-soft text-warn"
                    : "border-border bg-soft text-muted"
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

        {testReport && (
          <details className="rounded-md border border-border bg-soft/60 px-2 py-1.5" open data-testid="wf-test-report">
            <summary className="cursor-pointer text-[11px] font-medium text-muted">
              Reporte del test · {testReport.effective_level} · {testReport.result}
            </summary>
            <div className="mt-2 space-y-1 text-[10px] text-muted">
              <p>
                Solicitado: {testReport.requested_level}. Ejecutado: {testReport.effective_level}.
                {testReport.capped_reason ? ` Motivo: ${testReport.capped_reason}.` : ""}
              </p>
              <p>
                Nodos ejecutados: {testReport.executed_nodes?.length ?? 0}. Timeline:{" "}
                {testReport.timeline?.length ?? 0}.
              </p>
              {testReport.hashes && (
                <p className="break-all font-mono">
                  graph {testReport.hashes.graph_hash?.slice(0, 12)} · plan{" "}
                  {testReport.hashes.plan_hash?.slice(0, 12)} · rol{" "}
                  {testReport.hashes.role_hash?.slice(0, 12)} · binding{" "}
                  {testReport.hashes.binding_hash?.slice(0, 12)}
                </p>
              )}
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
                  className="flex w-full items-center gap-2 rounded-sm bg-soft px-2 py-1.5 text-left text-[10px] transition-colors duration-150 hover:bg-raised"
                  onClick={() => void showRun(r.id)}
                >
                  <StatusBadge status={r.status} />
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
        <fieldset className="flex flex-wrap gap-1" data-testid="wf-test-levels">
          <legend className="sr-only">Nivel de prueba</legend>
          {TEST_LEVELS.map((item) => (
            <button
              key={item.id}
              type="button"
              aria-pressed={level === item.id}
              className="min-h-8 rounded-md border border-border px-2 text-[11px] text-muted aria-pressed:border-accent aria-pressed:text-text"
              data-testid={`wf-level-${item.id}`}
              onClick={() => setLevel(item.id)}
            >
              {item.label}
            </button>
          ))}
        </fieldset>
        {UNAVAILABLE_LEVELS[level] && (
          <p className="text-[10px] text-warn" data-testid="wf-level-unavailable">
            {UNAVAILABLE_LEVELS[level]}
          </p>
        )}
        <div className="flex flex-wrap gap-1" data-testid="wf-role-examples">
          {ROLE_EXAMPLES.map((role) => (
            <button
              key={role.id}
              type="button"
              className="min-h-8 rounded-md bg-soft px-2 text-[11px] text-muted hover:text-text"
              data-testid={`wf-role-${role.id}`}
              onClick={() => setRaw(role.message)}
            >
              {role.label}
            </button>
          ))}
        </div>
        <ErrorInline message={error} className="mb-0" />
        <div className="flex flex-wrap items-center gap-1.5">
          <Button
            variant="ghost"
            size="sm"
            leadingIcon={MagicWand}
            className="text-[11px]"
            data-testid="wf-sample-generate"
            onClick={generateSample}
          >
            Generar ejemplo
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="text-[11px]"
            data-testid="wf-sample-last"
            onClick={() => void loadLastSample()}
          >
            Usar último
          </Button>
          <span className="text-[10px] text-faint">o edita los valores abajo</span>
        </div>
        <div className="flex items-end gap-2">
          <Textarea
            className="min-h-11 flex-1 resize-none text-[12px]"
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
          <Button
            variant="primary"
            className="min-h-11 px-3"
            loading={busy === "test"}
            leadingIcon={ArrowUp}
            disabled={!!busy}
            onClick={() => void execute(true)}
            data-testid="wf-test"
            aria-label="Probar"
          />
        </div>
        {normalized.wrapped && (
          <p className="text-[10px] text-faint" data-testid="wf-payload-wrapped">
            Se envía como <code className="font-mono text-muted">{JSON.stringify(normalized.payload)}</code>
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            loading={busy === "run"}
            leadingIcon={Lightning}
            disabled={!!busy}
            onClick={() => void execute(false)}
            data-testid="wf-run"
          >
            Ejecutar de verdad
          </Button>
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
