/**
 * AskZent — "¿Qué quieres automatizar?".
 * Muestra primero la interpretación de negocio (CUANDO / SI / ANALIZAR /
 * DESPUÉS); el grafo solo aparece en "Ver flujo avanzado". Nunca publica solo:
 * crear deja un borrador en el estudio.
 */
import { ArrowRight, Checks, Code, FloppyDisk, MagicWand, PencilSimple, Sparkle, WarningCircle } from "@phosphor-icons/react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { Badge, Button, ErrorInline, Textarea } from "../ui";

type Issue = { code: string; severity: "error" | "warning" | "info"; message: string; hint?: string | null };

type Summary = {
  when: string;
  conditions: string;
  analysis: string[];
  actions: string[];
  text: string;
};

type Proposal = {
  intent: Record<string, unknown> | null;
  plan: Record<string, unknown> | null;
  summary: Summary | null;
  questions: string[];
  issues: Issue[];
  confidence: number;
  source: string;
  notes: string[];
  must_review: boolean;
};

type CompileOut = {
  graph: {
    nodes: { id?: string; type: string; config?: Record<string, unknown> }[];
    edges?: unknown[];
    entrypoints?: string[];
  };
  valid: boolean;
  issues: Issue[];
  summary: Summary;
};

const EXAMPLES = [
  "Cuando el stock sea menor a 10, avisa por correo al equipo de compras",
  "Cada día a las 6pm dime cómo fueron las ventas y verifica clientes nuevos",
  "Cuando se registre una venta mayor a S/ 20,000 avisa al gerente comercial",
];

function triggerTypeOfGraph(graph: { nodes: { type: string }[] }): "webhook" | "schedule" | "event" {
  const trigger = graph.nodes.find((n) => n.type.startsWith("trigger_"))?.type ?? "";
  if (trigger === "trigger_schedule") return "schedule";
  if (trigger === "trigger_event") return "event";
  return "webhook";
}

export function AskZent({ initialPrompt = "", agentId = "", agentName = "" }: {
  initialPrompt?: string;
  agentId?: string;
  agentName?: string;
}) {
  const { session } = useAuth();
  const navigate = useNavigate();
  const [prompt, setPrompt] = useState(initialPrompt);
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState("");
  const [error, setError] = useState("");
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [showDetails, setShowDetails] = useState(false);
  const [showFlow, setShowFlow] = useState(false);
  const [compiledPreview, setCompiledPreview] = useState<CompileOut | null>(null);

  async function interpret() {
    if (!session || prompt.trim().length < 8) return;
    setBusy(true);
    setError("");
    setProposal(null);
    setShowDetails(false);
    setShowFlow(false);
    setCompiledPreview(null);
    try {
      const result = await api<Proposal>("/api/v1/workflows/copilot/intent", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ prompt: prompt.trim() }),
      });
      setProposal(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  async function compile(): Promise<CompileOut> {
    if (!session || !proposal?.plan) throw new Error("No hay plan para compilar");
    const out = await api<CompileOut>("/api/v1/workflows/copilot/compile", {
      method: "POST",
      token: session.token,
      organizationId: session.organizationId,
      body: JSON.stringify({ plan: proposal.plan }),
    });
    // Asistente preseleccionado (misión §26): el LLM puede reasignarse luego.
    if (agentId && Array.isArray(out.graph?.nodes)) {
      out.graph = {
        ...out.graph,
        nodes: out.graph.nodes.map((node) =>
          node.type === "llm"
            ? { ...node, config: { ...(node.config || {}), agent_id: agentId, agent_name: agentName } }
            : node,
        ),
      };
    }
    return out;
  }

  async function create(level: "simple" | "advanced") {
    if (!session || !proposal?.plan) return;
    setCreating(level);
    setError("");
    try {
      const out = await compile();
      if (!out.valid) {
        const first = out.issues.find((i) => i.severity === "error");
        setError(first?.message || "El flujo todavía necesita ajustes.");
        return;
      }
      const created = await api<{ workflow_id: string; hook_secret?: string }>("/api/v1/workflows", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          name: String((proposal.intent?.name as string) || "Automatización"),
          description: String((proposal.intent?.description as string) || proposal.summary?.text || ""),
          trigger_type: triggerTypeOfGraph(out.graph),
          graph: out.graph,
          workflow_version: 2,
          editor_state: { mode: "canvas", config_level: level },
        }),
      });
      navigate(
        `/workflows/${created.workflow_id}${level === "advanced" ? "?panel=advanced" : ""}`,
        { state: { hookSecret: created.hook_secret } },
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setCreating("");
    }
  }

  async function previewFlow() {
    setCreating("preview");
    setError("");
    try {
      setCompiledPreview(await compile());
      setShowFlow(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setCreating("");
    }
  }

  const warnings = proposal?.issues.filter((i) => i.severity !== "error") ?? [];
  const errors = proposal?.issues.filter((i) => i.severity === "error") ?? [];

  return (
    <section className="panel space-y-4 p-5" data-testid="ask-zent">
      <div>
        <h2 className="flex items-center gap-2 text-h2">
          <MagicWand size={18} className="text-accent" aria-hidden /> ¿Qué quieres automatizar?
        </h2>
        <p className="mt-1 text-[13px] leading-relaxed text-muted">
          Descríbelo como se lo dirías a una persona. Zent te dirá primero qué entendió.
        </p>
        {agentName && (
          <p className="mt-2 rounded-md border border-border bg-soft/50 px-2.5 py-2 text-[12px] leading-relaxed text-muted" data-testid="ask-agent-note">
            Quedará asociado al asistente <strong className="text-text">{agentName}</strong>. Si el flujo no necesita
            razonamiento, puede funcionar sin IA y ahorrar costo.
          </p>
        )}
      </div>

      <Textarea
        className="min-h-28 resize-y"
        rows={4}
        placeholder="Cuando tengamos una venta mayor a S/ 20,000, avisa al gerente comercial y haz que el agente revise si el cliente es nuevo."
        value={prompt}
        data-testid="ask-prompt"
        onChange={(e) => setPrompt(e.target.value)}
        aria-label="Qué quieres automatizar"
      />

      <div className="flex flex-wrap gap-1.5">
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            className="chip max-w-full cursor-pointer truncate transition-colors duration-150 hover:bg-raised hover:text-text"
            onClick={() => setPrompt(example)}
          >
            {example}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          leadingIcon={Sparkle}
          loading={busy}
          disabled={prompt.trim().length < 8}
          data-testid="ask-submit"
          onClick={() => void interpret()}
        >
          {busy ? "Interpretando…" : "Continuar"}
        </Button>
        <span className="text-[12px] text-faint">
          Todavía no se crea nada: primero revisas lo que Zent entendió.
        </span>
      </div>

      <ErrorInline message={error} className="mb-0" />

      {proposal?.summary && (
        <div className="space-y-3.5 rounded-lg border border-accent-line bg-accent-soft/40 p-4" data-testid="ask-understanding">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-h3">Entendí esto</h3>
            <span data-testid="ask-confidence">
              <Badge tone="info">confianza {Math.round((proposal.confidence ?? 0) * 100)}%</Badge>
            </span>
            {proposal.source === "heuristics" && <Badge tone="warn">borrador por reglas</Badge>}
          </div>

          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <UnderstandingBlock label="CUANDO" value={proposal.summary.when} />
            {proposal.summary.conditions && <UnderstandingBlock label="SI" value={proposal.summary.conditions} />}
            {proposal.summary.analysis.length > 0 && (
              <UnderstandingBlock label="ANALIZAR" items={proposal.summary.analysis} />
            )}
            {proposal.summary.actions.length > 0 && (
              <UnderstandingBlock label="DESPUÉS" items={proposal.summary.actions} />
            )}
          </dl>

          <p className="rounded-md border border-border-soft bg-surface px-3 py-2.5 text-[13px] leading-relaxed text-muted" data-testid="ask-summary">
            {proposal.summary.text}
          </p>

          {proposal.notes.length > 0 && (
            <p className="flex items-center gap-1.5 text-[12px] text-warn">
              <WarningCircle size={12} aria-hidden /> {proposal.notes.join(" ")}
            </p>
          )}

          {(proposal.questions.length > 0 || warnings.length > 0 || errors.length > 0) && (
            <div className="space-y-1.5 rounded-md border border-warn/40 bg-warn-soft px-3 py-2.5" data-testid="ask-questions">
              <p className="text-[13px] font-medium text-text">
                {errors.length > 0 ? "Necesito resolver esto antes de crear:" : "Necesito dos cosas:"}
              </p>
              <ul className="list-disc space-y-1 pl-4 text-[12px] leading-relaxed text-muted">
                {[...errors, ...warnings].map((issue) => (
                  <li key={`${issue.code}-${issue.message}`}>
                    {issue.message}
                    {issue.hint && <span className="text-faint"> {issue.hint}</span>}
                  </li>
                ))}
                {proposal.questions.map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            <Button
              variant="primary"
              leadingIcon={FloppyDisk}
              loading={creating === "simple"}
              disabled={!!creating}
              data-testid="ask-create"
              onClick={() => void create("simple")}
            >
              Crear automatización
            </Button>
            <Button
              variant="secondary"
              leadingIcon={PencilSimple}
              data-testid="ask-change"
              onClick={() => {
                setProposal(null);
                setShowDetails(false);
                setShowFlow(false);
              }}
            >
              Cambiar algo
            </Button>
            <Button
              variant="ghost"
              leadingIcon={Code}
              data-testid="ask-details"
              aria-expanded={showDetails}
              onClick={() => setShowDetails((v) => !v)}
            >
              Ver detalles
            </Button>
            <Button
              variant="ghost"
              leadingIcon={ArrowRight}
              loading={creating === "preview"}
              disabled={!!creating}
              data-testid="ask-advanced"
              onClick={() => void previewFlow()}
            >
              Ver flujo avanzado
            </Button>
            {showFlow && compiledPreview?.valid && (
              <Button
                variant="secondary"
                leadingIcon={Checks}
                disabled={!!creating}
                data-testid="ask-create-advanced"
                onClick={() => void create("advanced")}
              >
                Abrir en el canvas
              </Button>
            )}
          </div>

          {showDetails && (
            <pre
              className="max-h-64 overflow-auto rounded-md border border-border-soft bg-control p-3 font-mono text-[11px] leading-relaxed text-muted"
              data-testid="ask-plan-json"
            >
              {JSON.stringify({ intent: proposal.intent, plan: proposal.plan }, null, 2)}
            </pre>
          )}
          {showFlow && compiledPreview && (
            <div className="text-[12px] text-muted" data-testid="ask-flow-preview">
              {compiledPreview.valid ? (
                <span>
                  Flujo listo: {compiledPreview.graph.nodes.map((n) => n.type).join(" → ")}
                </span>
              ) : (
                <span className="text-danger">
                  {compiledPreview.issues.find((i) => i.severity === "error")?.message}
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function UnderstandingBlock({ label, value, items }: { label: string; value?: string; items?: string[] }) {
  return (
    <div>
      <dt className="eyebrow">{label}</dt>
      {value && <dd className="mt-0.5 text-[13px] leading-relaxed text-text">{value}</dd>}
      {items && (
        <dd className="mt-0.5 space-y-0.5">
          {items.map((item) => (
            <p key={item} className="text-[13px] leading-relaxed text-text">
              • {item}
            </p>
          ))}
        </dd>
      )}
    </div>
  );
}
