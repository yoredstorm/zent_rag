/**
 * ArchitectAskZent — creación canónica con IA (Workflow Architect).
 *
 * Muestra el estado real del diseño, lo que Zent entendió, las dependencias
 * y el fallback informado. Nunca compila ni publica desde React: guardar un
 * borrador re-valida plan, permisos y capacidades en el backend.
 */
import {
  ArrowRight,
  ArrowsClockwise,
  Checks,
  Code,
  FloppyDisk,
  ListChecks,
  MagicWand,
  PencilSimple,
  Sparkle,
  WarningCircle,
} from "@phosphor-icons/react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../../auth";
import { ApiError } from "../../lib/errors";
import { Badge, Button, ErrorInline, Textarea } from "../ui";
import {
  PREVIEW_LABEL,
  STATE_LABEL,
  patchArchitectPlan,
  planWithArchitect,
  saveArchitectDraft,
  type ArchitectProposal,
  type DesignState,
} from "./workflowArchitect";

const EXAMPLES = [
  "Cuando el stock sea menor a 10, avisa por correo al equipo de compras",
  "Cada día a las 6pm dime cómo fueron las ventas y verifica clientes nuevos",
  "Cuando se registre una venta mayor a S/ 20,000 avisa al gerente comercial",
];

const PHASE_LABEL: Record<string, string> = {
  discovery: "Capacidades",
  intent: "Entendimiento",
  planning: "Diseño",
  validation: "Validación",
  compilation: "Compilación",
  readiness: "Disponibilidad",
};

const STATE_TONE: Record<DesignState, "neutral" | "accent" | "ok" | "warn" | "danger"> = {
  UNDERSTANDING: "accent",
  DISCOVERING: "accent",
  PLANNING: "accent",
  NEEDS_CLARIFICATION: "warn",
  NEEDS_CONFIGURATION: "warn",
  VALIDATING: "accent",
  DRAFT_READY: "ok",
  BLOCKED: "danger",
};

function draftName(proposal: ArchitectProposal): string {
  const intentGoal = proposal.intent?.goal;
  const planGoal = proposal.plan?.goal;
  const value =
    (typeof intentGoal === "string" && intentGoal) ||
    (typeof planGoal === "string" && planGoal) ||
    "Automatización";
  return value.slice(0, 150);
}

export function ArchitectAskZent({
  initialPrompt = "",
  agentId = "",
  agentName = "",
}: {
  initialPrompt?: string;
  agentId?: string;
  agentName?: string;
}) {
  const { session } = useAuth();
  const navigate = useNavigate();
  const [prompt, setPrompt] = useState(initialPrompt);
  const [proposal, setProposal] = useState<ArchitectProposal | null>(null);
  const [busy, setBusy] = useState<"" | "plan" | "patch" | "save">("");
  const [error, setError] = useState("");
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [clarify, setClarify] = useState("");
  const [patchOpen, setPatchOpen] = useState(false);
  const [patchText, setPatchText] = useState("");
  const [showPlan, setShowPlan] = useState(false);
  const [showFlow, setShowFlow] = useState(false);

  async function interpret(extra?: string) {
    if (!session || prompt.trim().length < 8) return;
    setBusy("plan");
    setError("");
    setProposal(null);
    setPatchOpen(false);
    setShowFlow(false);
    try {
      const base = prompt.trim();
      const text = extra?.trim()
        ? `${base}\n\nDatos confirmados por el usuario: ${extra.trim()}`
        : base;
      const result = await planWithArchitect(session, text, sessionId, agentId);
      setProposal(result);
      setSessionId(result.session_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pude interpretar el pedido.");
    } finally {
      setBusy("");
    }
  }

  async function applyPatch() {
    if (!session || !proposal || !proposal.plan || !proposal.plan_hash || patchText.trim().length < 3) return;
    setBusy("patch");
    setError("");
    try {
      const next = await patchArchitectPlan(session, {
        plan: proposal.plan,
        instruction: patchText.trim(),
        sessionId: proposal.session_id,
        planHash: proposal.plan_hash,
      });
      setProposal(next);
      setPatchText("");
      setPatchOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pude aplicar el cambio.");
    } finally {
      setBusy("");
    }
  }

  async function save(level: "simple" | "advanced") {
    if (!session || !proposal || !proposal.graph) return;
    setBusy("save");
    setError("");
    try {
      const out = await saveArchitectDraft(session, {
        proposal,
        name: draftName(proposal),
        description: prompt.trim(),
        configLevel: level,
      });
      navigate(`/workflows/${out.workflow_id}${level === "advanced" ? "?panel=advanced" : ""}`, {
        state: { hookSecret: out.hook_secret },
      });
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) {
        setError("El diseño tiene dependencias sin resolver; revisa los bloqueos antes de guardar.");
      } else {
        setError(e instanceof Error ? e.message : "No pude guardar el borrador.");
      }
    } finally {
      setBusy("");
    }
  }

  const state = proposal?.state;
  const canSave = Boolean(proposal?.graph) && state !== "BLOCKED";
  const hasClarifications = Boolean(proposal?.clarifications.length);
  const hasRequirements = Boolean(proposal?.requirements.length);
  const sourceLabel =
    proposal?.planner.source === "heuristics" ? "borrador por reglas" : "planificado con IA";

  return (
    <section className="panel space-y-4 p-5" data-testid="ask-zent">
      <div>
        <h2 className="flex items-center gap-2 text-h2">
          <MagicWand size={18} className="text-accent" aria-hidden /> ¿Qué quieres automatizar?
        </h2>
        <p className="mt-1 text-[13px] leading-relaxed text-muted">
          Descríbelo como se lo dirías a una persona. Zent revisa tus capacidades, te muestra lo
          que entendió y te pide confirmación antes de guardar.
        </p>
        {agentName && (
          <p
            className="mt-2 rounded-md border border-border bg-soft/50 px-2.5 py-2 text-[12px] leading-relaxed text-muted"
            data-testid="ask-agent-note"
          >
            Quedará asociado al asistente <strong className="text-text">{agentName}</strong>. Si el
            flujo no necesita razonamiento, puede funcionar sin IA y ahorrar costo.
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
          loading={busy === "plan"}
          disabled={prompt.trim().length < 8 || busy === "plan"}
          data-testid="ask-submit"
          onClick={() => void interpret()}
        >
          {busy === "plan" ? "Entendiendo…" : "Continuar"}
        </Button>
        <span className="text-[12px] text-faint">
          Todavía no se crea nada: primero revisas lo que Zent entendió.
        </span>
      </div>

      {busy === "plan" && (
        <div
          className="flex items-center gap-2 rounded-md border border-border-soft bg-surface px-3 py-2.5 text-[12px] text-muted"
          data-testid="ask-working"
          data-state="UNDERSTANDING"
        >
          <ArrowsClockwise size={14} className="animate-spin text-accent" aria-hidden />
          Entendiendo el pedido y revisando tus capacidades…
        </div>
      )}

      <ErrorInline message={error} className="mb-0" />

      {proposal && (
        <div className="space-y-3.5 rounded-lg border border-accent-line bg-accent-soft/40 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-h3">{STATE_LABEL[proposal.state]}</h3>
            <span data-testid="ask-state" data-state={proposal.state}>
              <Badge tone={STATE_TONE[proposal.state]}>{proposal.state}</Badge>
            </span>
            <span data-testid="ask-planner">
              <Badge tone="info">{sourceLabel}</Badge>
            </span>
            {proposal.planner.model && (
              <span className="text-[11px] text-faint">{proposal.planner.model}</span>
            )}
          </div>

          <p className="text-[11px] text-faint" data-testid="ask-session">
            {proposal.planner.version} · sesión {proposal.session_id}
          </p>

          {proposal.phases.length > 0 && (
            <ol className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-faint" data-testid="ask-phases">
              {proposal.phases.map((phase) => (
                <li key={phase.name}>
                  {PHASE_LABEL[phase.name] ?? phase.name}
                  <span className="ml-1 tabular-nums text-ghost">{phase.duration_ms}ms</span>
                </li>
              ))}
            </ol>
          )}

          {proposal.fallback && (
            <div
              className="space-y-1.5 rounded-md border border-warn/40 bg-warn-soft px-3 py-2.5"
              data-testid="ask-fallback"
            >
              <p className="flex items-center gap-1.5 text-[13px] font-medium text-text">
                <WarningCircle size={14} aria-hidden /> El modelo no estuvo disponible
              </p>
              <p className="text-[12px] leading-relaxed text-muted">
                Armé un borrador con reglas. No reemplaza el pedido original y no se publica sin tu
                confirmación.
              </p>
              <ul className="list-disc space-y-1 pl-4 text-[12px] leading-relaxed text-muted">
                {proposal.fallback.limitations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
              <p className="text-[11px] text-faint">
                Pedido conservado: {proposal.fallback.preserved_requirement}
              </p>
            </div>
          )}

          <div data-testid="ask-understanding">
            <h3 className="text-h3 mb-2">Entendí esto</h3>
            <ol className="space-y-1.5">
              {proposal.preview.map((item) => (
                <li key={`${item.step_id}-${item.kind}-${item.text}`} className="flex gap-2 text-[13px] leading-relaxed">
                  <span className="mono mt-0.5 shrink-0 text-[10px] text-ghost">
                    {PREVIEW_LABEL[item.kind] ?? item.kind.toUpperCase()}
                  </span>
                  <span className="text-text">{item.text}</span>
                </li>
              ))}
            </ol>
          </div>

          {proposal.matches && proposal.matches.length > 0 && (
            <div data-testid="ask-matches">
              <h3 className="text-h3 mb-2">Capacidades seleccionadas</h3>
              <ul className="space-y-1.5">
                {proposal.matches.map((item) => (
                  <li
                    key={`${item.need}-${item.capability_ref}`}
                    className="rounded-md border border-border-soft bg-surface px-3 py-2 text-[12px] leading-relaxed"
                  >
                    <p className="text-text">
                      <span className="mono text-[11px] text-accent">{item.capability_ref}</span>
                      {item.version ? ` v${item.version}` : ""} · {item.need}
                    </p>
                    {item.reason && <p className="mt-0.5 text-muted">{item.reason}</p>}
                    <p className="mt-0.5 text-faint">
                      {item.availability ?? "sin verificar"}
                      {item.unresolved && item.unresolved.length > 0
                        ? ` · falta: ${item.unresolved.join(", ")}`
                        : ""}
                      {item.alternatives && item.alternatives.length > 0
                        ? ` · alternativas: ${item.alternatives.join(", ")}`
                        : ""}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {proposal.requires_durable_instance && (
            <p
              className="rounded-md border border-border-soft bg-surface px-3 py-2 text-[12px] text-muted"
              data-testid="ask-durable"
            >
              Este plan usa esperas o repeticiones: debe iniciarse como proceso durable
              para conservar el estado.
            </p>
          )}

          {proposal.trace && proposal.trace.tool_calls.length > 0 && (
            <details
              className="rounded-md border border-border-soft bg-surface px-3 py-2"
              data-testid="ask-trace"
            >
              <summary className="cursor-pointer text-[12px] font-medium text-text">
                Cómo lo investigué: {proposal.trace.tool_calls.length} consulta(s) al
                catálogo
              </summary>
              <ol className="mt-2 flex flex-wrap gap-x-2 gap-y-1 text-[11px] text-faint">
                {proposal.trace.stages.map((stage, index) => (
                  <li key={`${stage.name}-${index}`}>
                    {stage.name} ({stage.duration_ms} ms)
                  </li>
                ))}
              </ol>
              <ul className="mt-2 space-y-1 text-[11px] text-muted">
                {proposal.trace.tool_calls.map((call, index) => (
                  <li key={`${call.tool}-${index}`}>
                    <span className={call.ok ? "text-text" : "text-danger"}>
                      {call.ok ? "OK" : "RECHAZADA"}
                    </span>{" "}
                    {call.tool}
                    {call.error ? ` · ${call.error}` : ""}
                  </li>
                ))}
              </ul>
            </details>
          )}

          {hasClarifications && (
            <div
              className="space-y-2 rounded-md border border-warn/40 bg-warn-soft px-3 py-2.5"
              data-testid="ask-questions"
            >
              <p className="text-[13px] font-medium text-text">Necesito que confirmes esto:</p>
              <ul className="list-disc space-y-1 pl-4 text-[12px] leading-relaxed text-muted">
                {proposal.clarifications.map((item) => (
                  <li key={`${item.code}-${item.question}`}>{item.question}</li>
                ))}
              </ul>
              <Textarea
                rows={2}
                className="min-h-16"
                placeholder="Responde acá; se agrega a tu pedido antes de reinterpretar."
                value={clarify}
                data-testid="ask-clarify-answer"
                onChange={(e) => setClarify(e.target.value)}
                aria-label="Datos que faltan"
              />
              <Button
                variant="secondary"
                size="sm"
                leadingIcon={ArrowsClockwise}
                loading={busy === "plan"}
                disabled={clarify.trim().length < 2 || busy === "plan"}
                data-testid="ask-clarify-submit"
                onClick={() => void interpret(clarify)}
              >
                Responder y reintentar
              </Button>
            </div>
          )}

          {hasRequirements && (
            <div
              className="space-y-2 rounded-md border border-warn/40 bg-warn-soft px-3 py-2.5"
              data-testid="ask-requirements"
            >
              <p className="flex items-center gap-1.5 text-[13px] font-medium text-text">
                <ListChecks size={14} aria-hidden /> Falta conectar o configurar
              </p>
              <ul className="space-y-1 text-[12px] leading-relaxed text-muted">
                {proposal.requirements.map((item) => (
                  <li key={item.requirement}>• {item.message}</li>
                ))}
              </ul>
              <Link
                to="/integrations"
                className="inline-flex items-center gap-1 text-[12px] font-medium text-accent hover:underline"
                data-testid="ask-integrations"
              >
                Ir a Integraciones <ArrowRight size={12} aria-hidden />
              </Link>
            </div>
          )}

          {proposal.blockers.filter((item) => item.kind !== "requirement").length > 0 && (
            <div className="rounded-md border border-danger/40 bg-danger-soft px-3 py-2.5" data-testid="ask-blockers">
              <p className="text-[13px] font-medium text-text">No puedo continuar todavía:</p>
              <ul className="mt-1 list-disc space-y-1 pl-4 text-[12px] leading-relaxed text-muted">
                {proposal.blockers
                  .filter((item) => item.kind !== "requirement")
                  .map((item) => (
                    <li key={`${item.code}-${item.message}`}>{item.message}</li>
                  ))}
              </ul>
            </div>
          )}

          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" data-testid="ask-checks">
            <div>
              <dt className="eyebrow">DISPONIBILIDAD</dt>
              <dd className="mt-0.5 text-[13px] text-text">
                {proposal.readiness
                  ? proposal.readiness.ready
                    ? "Sin bloqueos"
                    : `${proposal.readiness.errors} bloqueo(s)`
                  : "Sin verificar"}
              </dd>
            </div>
            <div>
              <dt className="eyebrow">COSTO ESTIMADO</dt>
              <dd className="mt-0.5 text-[13px] text-text tabular-nums">
                {proposal.cost ? `${proposal.cost.currency} ${proposal.cost.per_run}/run` : "—"}
              </dd>
            </div>
            <div>
              <dt className="eyebrow">PASOS</dt>
              <dd className="mt-0.5 text-[13px] text-text tabular-nums">
                {proposal.graph?.nodes.length ?? 0} nodos
              </dd>
            </div>
            <div>
              <dt className="eyebrow">CATÁLOGO</dt>
              <dd className="mt-0.5 text-[13px] text-text tabular-nums" data-testid="ask-catalog">
                {proposal.capability_snapshot?.counts?.capabilities
                  ? `${proposal.capability_snapshot.counts.capabilities} capacidades`
                  : "—"}
                {typeof proposal.capability_snapshot?.coverage?.business_completeness === "number" &&
                  ` · ${Math.round(
                    proposal.capability_snapshot.coverage.business_completeness * 100,
                  )}% contratos`}
              </dd>
            </div>
          </dl>

          {proposal.patch?.summary && (
            <p className="rounded-md border border-border-soft bg-surface px-3 py-2 text-[12px] text-muted" data-testid="ask-patch-note">
              Cambio aplicado: {proposal.patch.summary}. Los pasos no afectados se conservaron.
            </p>
          )}

          <div className="flex flex-wrap gap-2">
            {state === "DRAFT_READY" && (
              <Button
                variant="primary"
                leadingIcon={FloppyDisk}
                loading={busy === "save"}
                disabled={!!busy}
                data-testid="ask-create"
                onClick={() => void save("simple")}
              >
                Crear borrador
              </Button>
            )}
            {canSave && state !== "DRAFT_READY" && (
              <Button
                variant="secondary"
                leadingIcon={FloppyDisk}
                loading={busy === "save"}
                disabled={!!busy}
                data-testid="ask-save-draft"
                onClick={() => void save("simple")}
              >
                Guardar borrador incompleto
              </Button>
            )}
            {state === "BLOCKED" && (
              <Button
                variant="secondary"
                leadingIcon={ArrowsClockwise}
                loading={busy === "plan"}
                disabled={!!busy}
                data-testid="ask-retry"
                onClick={() => void interpret()}
              >
                Reintentar
              </Button>
            )}
            <Button
              variant="secondary"
              leadingIcon={PencilSimple}
              disabled={!!busy}
              data-testid="ask-change"
              aria-expanded={patchOpen}
              onClick={() => {
                setPatchOpen((value) => !value);
                setShowPlan(false);
              }}
            >
              Cambiar algo
            </Button>
            <Button
              variant="ghost"
              leadingIcon={Code}
              data-testid="ask-details"
              aria-expanded={showPlan}
              onClick={() => setShowPlan((value) => !value)}
            >
              Ver plan
            </Button>
            <Button
              variant="ghost"
              leadingIcon={ArrowRight}
              data-testid="ask-advanced"
              aria-expanded={showFlow}
              onClick={() => setShowFlow((value) => !value)}
            >
              Ver flujo avanzado
            </Button>
            {canSave && (
              <Button
                variant="ghost"
                leadingIcon={Checks}
                disabled={!!busy}
                data-testid="ask-open-advanced"
                onClick={() => void save("advanced")}
              >
                Abrir en el canvas
              </Button>
            )}
          </div>

          {patchOpen && (
            <div className="space-y-2 rounded-md border border-border bg-surface px-3 py-2.5" data-testid="ask-patch">
              <p className="text-[12px] text-muted">
                Pide un cambio sobre este plan. Se conservan los pasos que no toca.
              </p>
              <Textarea
                rows={2}
                className="min-h-16"
                placeholder="Ej.: cambia el umbral a 50000, quita la aprobación o avisa por correo."
                value={patchText}
                data-testid="ask-patch-text"
                onChange={(e) => setPatchText(e.target.value)}
                aria-label="Cambio pedido"
              />
              <Button
                variant="secondary"
                size="sm"
                leadingIcon={PencilSimple}
                loading={busy === "patch"}
                disabled={patchText.trim().length < 3 || busy === "patch"}
                data-testid="ask-patch-submit"
                onClick={() => void applyPatch()}
              >
                Aplicar cambio
              </Button>
            </div>
          )}

          {showPlan && (
            <pre
              className="max-h-64 overflow-auto rounded-md border border-border-soft bg-control p-3 font-mono text-[11px] leading-relaxed text-muted"
              data-testid="ask-plan-json"
            >
              {JSON.stringify({ intent: proposal.intent, plan: proposal.plan }, null, 2)}
            </pre>
          )}

          {showFlow && proposal.graph && (
            <div className="text-[12px] text-muted" data-testid="ask-flow-preview">
              <p className="flex items-center gap-1.5">
                <Checks size={12} className="text-ok" aria-hidden />
                Flujo validado: {proposal.graph.nodes.map((node) => node.type).join(" → ")}
              </p>
              <p className="mt-1 text-[11px] text-faint">
                Guardar el borrador vuelve a validar permisos, capacidades y dependencias en el
                servidor.
              </p>
            </div>
          )}

          {agentId && proposal.planner.source === "llm" && (
            <p className="text-[11px] text-faint">
              El asistente elegido se usó como preferencia para los pasos de IA.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
