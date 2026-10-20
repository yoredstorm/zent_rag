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
  ChatCircleDots,
  Checks,
  ClockCounterClockwise,
  Code,
  FloppyDisk,
  FolderOpen,
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
  applyArchitectDesignPatch,
  closeArchitectDesignSession,
  createArchitectDesignSession,
  getArchitectDesignSession,
  listArchitectDesignSessions,
  previewArchitectDesignPatch,
  reopenArchitectDesignSession,
  restoreArchitectDesignRevision,
  saveArchitectDesignDraft,
  sendArchitectDesignMessage,
  simulateArchitectDesignSession,
  type ArchitectDesignSession,
  type ArchitectPatchPreview,
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

type StudioMode = "simple" | "guided" | "advanced";

const STUDIO_MODES: { id: StudioMode; label: string; hint: string }[] = [
  { id: "simple", label: "Simple", hint: "Conversación y resultado" },
  { id: "guided", label: "Guiado", hint: "Pasos, fuentes y permisos" },
  { id: "advanced", label: "Avanzado", hint: "Contratos, plan y Canvas" },
];

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
  const [designSession, setDesignSession] = useState<ArchitectDesignSession | null>(null);
  const [mode, setMode] = useState<StudioMode>("simple");
  const [busy, setBusy] = useState<
    "" | "plan" | "patch" | "save" | "restore" | "simulate"
  >("");
  const [error, setError] = useState("");
  const [clarify, setClarify] = useState("");
  const [patchOpen, setPatchOpen] = useState(false);
  const [patchText, setPatchText] = useState("");
  const [patchPreview, setPatchPreview] = useState<ArchitectPatchPreview | null>(null);
  const [pendingPatchMessage, setPendingPatchMessage] = useState("");
  const [showPlan, setShowPlan] = useState(false);
  const [showFlow, setShowFlow] = useState(false);
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [sessionsBusy, setSessionsBusy] = useState(false);
  const [savedSessions, setSavedSessions] = useState<ArchitectDesignSession[]>([]);
  const [simulationOpen, setSimulationOpen] = useState(false);
  const [scenarioText, setScenarioText] = useState(
    '[{"scenario_id":"camino_feliz","initial_inputs":{}}]',
  );

  function applySessionResult(
    next: ArchitectDesignSession,
    nextProposal?: ArchitectProposal | null,
  ) {
    setDesignSession(next);
    if (nextProposal) {
      setProposal(nextProposal);
      return;
    }
    const stored = next.state?.proposal;
    if (stored && typeof stored === "object") {
      setProposal(stored as ArchitectProposal);
    }
  }

  async function sendConversation(text: string, kind: "plan" | "patch" = "patch") {
    if (!session || text.trim().length < 2) return;
    if (designSession?.status === "closed") {
      setError("La sesión está cerrada; reábrela para seguir editando.");
      return;
    }
    setBusy(kind);
    setError("");
    try {
      if (!designSession) {
        const created = await createArchitectDesignSession(session, {
          prompt: text.trim(),
          title: prompt.trim().slice(0, 120),
          agentId,
        });
        applySessionResult(created.design_session, created.proposal);
      } else {
        const changed = await sendArchitectDesignMessage(session, {
          designSessionId: designSession.id,
          message: text.trim(),
          expectedRevision: designSession.revision,
          agentId,
        });
        applySessionResult(changed.design_session, changed.proposal);
        setPatchText("");
        setClarify("");
        setPatchOpen(false);
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && designSession) {
        try {
          const fresh = await getArchitectDesignSession(session, designSession.id);
          applySessionResult(fresh, (fresh.state?.proposal as ArchitectProposal) ?? null);
          setError(
            "Esta sesión cambió en otra pestaña. Cargué la revisión más reciente; revisa antes de volver a editar.",
          );
        } catch {
          setError("Esta sesión cambió y no pude recargarla. Vuelve a abrirla.");
        }
      } else if (e instanceof ApiError && e.status === 422) {
        setError("El cambio no pasó la validación; no se guardó ninguna modificación.");
      } else {
        setError(e instanceof Error ? e.message : "No pude continuar el diseño.");
      }
    } finally {
      setBusy("");
    }
  }

  async function interpret(extra?: string) {
    if (!session || (!designSession && prompt.trim().length < 8)) return;
    const base = prompt.trim();
    const text = extra?.trim()
      ? designSession
        ? `Datos confirmados por el usuario: ${extra.trim()}`
        : `${base}\n\nDatos confirmados por el usuario: ${extra.trim()}`
      : base;
    setPatchOpen(false);
    setShowFlow(false);
    await sendConversation(text, "plan");
  }

  async function applyPatch() {
    if (!session || !designSession || patchText.trim().length < 3) return;
    if (designSession.status === "closed") {
      setError("La sesión está cerrada; reábrela para corregir el diseño.");
      return;
    }
    setBusy("patch");
    setError("");
    try {
      const preview = await previewArchitectDesignPatch(session, {
        designSessionId: designSession.id,
        message: patchText.trim(),
        expectedRevision: designSession.revision,
      });
      setPatchPreview(preview);
      setPendingPatchMessage(patchText.trim());
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) {
        setError("El cambio no pasó la validación; no se guardó ninguna modificación.");
      } else if (e instanceof ApiError && e.status === 409) {
        setError("La sesión cambió en otra pestaña. Recarga antes de aplicar el cambio.");
      } else {
        setError(e instanceof Error ? e.message : "No pude preparar el cambio.");
      }
    } finally {
      setBusy("");
    }
  }

  async function confirmPatch() {
    if (!session || !designSession || !patchPreview) return;
    setBusy("patch");
    setError("");
    try {
      const changed = await applyArchitectDesignPatch(session, {
        designSessionId: designSession.id,
        message: pendingPatchMessage,
        expectedRevision: designSession.revision,
        patch: patchPreview.patch,
        source: patchPreview.proposal.source,
      });
      applySessionResult(changed.design_session, changed.proposal);
      setPatchPreview(null);
      setPendingPatchMessage("");
      setPatchText("");
      setPatchOpen(false);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError("La sesión cambió en otra pestaña. Recarga antes de aplicar el cambio.");
      } else if (e instanceof ApiError && e.status === 422) {
        setError("El cambio confirmado no pasó la validación; no se guardó.");
      } else {
        setError(e instanceof Error ? e.message : "No pude aplicar el cambio.");
      }
    } finally {
      setBusy("");
    }
  }

  async function restoreRevision(revision: number) {
    if (!session || !designSession) return;
    setBusy("restore");
    setError("");
    try {
      const restored = await restoreArchitectDesignRevision(session, {
        designSessionId: designSession.id,
        revision,
        expectedRevision: designSession.revision,
        instruction: `Restaurar revisión ${revision}`,
      });
      applySessionResult(restored);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pude restaurar la revisión.");
    } finally {
      setBusy("");
    }
  }

  async function runSimulation() {
    if (!session || !designSession || !proposal?.plan) return;
    if (designSession.status === "closed") {
      setError("La sesión está cerrada; reábrela antes de simular.");
      return;
    }
    let scenarios: Record<string, unknown>[];
    try {
      const parsed = JSON.parse(scenarioText);
      if (!Array.isArray(parsed) || parsed.length === 0) {
        throw new Error("Debes enviar al menos un escenario.");
      }
      scenarios = parsed as Record<string, unknown>[];
    } catch (e) {
      setError(e instanceof Error ? e.message : "Los escenarios no son un JSON válido.");
      return;
    }
    setBusy("simulate");
    setError("");
    try {
      const result = await simulateArchitectDesignSession(session, {
        designSessionId: designSession.id,
        expectedRevision: designSession.revision,
        scenarios,
      });
      applySessionResult(result.design_session);
      setSimulationOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pude simular el diseño.");
    } finally {
      setBusy("");
    }
  }

  async function toggleSavedSessions() {
    if (sessionsOpen) {
      setSessionsOpen(false);
      return;
    }
    if (!session) return;
    setSessionsBusy(true);
    setError("");
    try {
      const result = await listArchitectDesignSessions(session);
      setSavedSessions(result.sessions ?? []);
      setSessionsOpen(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pude cargar tus diseños guardados.");
    } finally {
      setSessionsBusy(false);
    }
  }

  async function openSavedSession(designSessionId: string) {
    if (!session) return;
    setBusy("plan");
    setError("");
    try {
      const loaded = await getArchitectDesignSession(session, designSessionId);
      applySessionResult(loaded);
      setPrompt(loaded.original_prompt);
      setSessionsOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pude abrir el diseño.");
    } finally {
      setBusy("");
    }
  }

  async function closeCurrentSession() {
    if (!session || !designSession) return;
    setBusy("save");
    setError("");
    try {
      await closeArchitectDesignSession(session, {
        designSessionId: designSession.id,
        expectedRevision: designSession.revision,
      });
      applySessionResult(await getArchitectDesignSession(session, designSession.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pude cerrar la sesión.");
    } finally {
      setBusy("");
    }
  }

  async function reopenCurrentSession() {
    if (!session || !designSession) return;
    setBusy("save");
    setError("");
    try {
      await reopenArchitectDesignSession(session, {
        designSessionId: designSession.id,
        expectedRevision: designSession.revision,
      });
      applySessionResult(await getArchitectDesignSession(session, designSession.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pude reabrir la sesión.");
    } finally {
      setBusy("");
    }
  }

  async function save(level: "simple" | "guided" | "advanced") {
    if (!session || !proposal || !proposal.graph || !designSession) return;
    setBusy("save");
    setError("");
    try {
      const out = await saveArchitectDesignDraft(session, {
        designSessionId: designSession.id,
        expectedRevision: designSession.revision,
        name: draftName(proposal),
        description: designSession.original_prompt || prompt.trim(),
        configLevel: level,
      });
      setDesignSession(out.design_session);
      navigate(
        `/workflows/${out.workflow.workflow_id}${level === "advanced" ? "?panel=advanced" : ""}`,
        { state: { hookSecret: out.workflow.hook_secret } },
      );
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) {
        setError("El diseño tiene dependencias sin resolver; revisa los bloqueos antes de guardar.");
      } else if (e instanceof ApiError && e.status === 409) {
        setError("La sesión cambió en otra pestaña. Recarga antes de guardar el borrador.");
      } else {
        setError(e instanceof Error ? e.message : "No pude guardar el borrador.");
      }
    } finally {
      setBusy("");
    }
  }

  const state = proposal?.state;
  const sessionClosed = designSession?.status === "closed";
  const canSave =
    Boolean(proposal?.graph) && state !== "BLOCKED" && Boolean(designSession) && !sessionClosed;
  const conversation = designSession?.messages ?? [];
  const revisions = designSession?.revisions ?? [];
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

      <div
        className="flex flex-wrap items-center gap-1.5 rounded-lg border border-border-soft bg-surface p-1"
        role="tablist"
        aria-label="Modo del estudio de diseño"
        data-testid="ask-modes"
      >
        {STUDIO_MODES.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={mode === item.id}
            data-testid={`ask-mode-${item.id}`}
            className={`rounded-md px-2.5 py-1.5 text-left transition-colors duration-150 ${
              mode === item.id
                ? "bg-accent-soft text-text"
                : "text-muted hover:bg-raised hover:text-text"
            }`}
            onClick={() => {
              setMode(item.id);
              if (item.id === "advanced") setShowPlan(true);
            }}
          >
            <span className="block text-[12px] font-medium">{item.label}</span>
            <span className="block text-[10px] text-faint">{item.hint}</span>
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button
          variant="ghost"
          size="sm"
          leadingIcon={FolderOpen}
          loading={sessionsBusy}
          disabled={sessionsBusy}
          data-testid="ask-saved-sessions"
          aria-expanded={sessionsOpen}
          onClick={() => void toggleSavedSessions()}
        >
          Mis diseños
        </Button>
        {designSession && (
          <Button
            variant="ghost"
            size="sm"
            disabled={!!busy}
            data-testid="ask-close-session"
            onClick={() =>
              void (designSession.status === "closed"
                ? reopenCurrentSession()
                : closeCurrentSession())
            }
          >
            {designSession.status === "closed" ? "Reabrir sesión" : "Cerrar sesión"}
          </Button>
        )}
      </div>

      {sessionsOpen && (
        <div
          className="rounded-md border border-border-soft bg-surface px-3 py-2"
          data-testid="ask-session-list"
        >
          {savedSessions.length === 0 ? (
            <p className="text-[12px] text-muted">Todavía no tienes diseños guardados.</p>
          ) : (
            <ul className="space-y-1">
              {savedSessions.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    className="w-full rounded px-2 py-1.5 text-left text-[12px] text-text hover:bg-raised"
                    data-testid={`ask-open-session-${item.id}`}
                    onClick={() => void openSavedSession(item.id)}
                  >
                    <span className="font-medium">{item.title}</span>
                    <span className="ml-2 text-[10px] text-faint">
                      {item.status} · r{item.revision} ·{" "}
                      {item.updated_at ? new Date(item.updated_at).toLocaleString() : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {designSession && (
        <div
          className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border-soft bg-surface px-3 py-2 text-[11px] text-muted"
          data-testid="ask-session-bar"
        >
          <span>
            <span className="text-text">{designSession.title}</span> · revisión{" "}
            <span className="tabular-nums text-text">{designSession.revision}</span> ·{" "}
            {designSession.status}
          </span>
          <span className="text-faint">
            {sessionClosed
              ? "Sesión cerrada · reábrela para editar"
              : designSession.workflow_id
                ? "Borrador guardado"
                : "Solo diseño, sin ejecutar"}
          </span>
        </div>
      )}

      {!designSession && (
        <>
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
        </>
      )}

      {designSession && (
        <p
          className="rounded-md border border-border-soft bg-surface px-3 py-2 text-[12px] leading-relaxed text-muted"
          data-testid="ask-original"
        >
          Pedido original: <span className="text-text">{designSession.original_prompt}</span>
        </p>
      )}

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

      {conversation.length > 0 && (
        <div
          className="rounded-lg border border-border-soft bg-surface p-3"
          data-testid="ask-conversation"
        >
          <div className="mb-2 flex items-center justify-between gap-2">
            <h3 className="flex items-center gap-1.5 text-[13px] font-medium text-text">
              <ChatCircleDots size={14} className="text-accent" aria-hidden /> Conversación de
              diseño
            </h3>
            <span className="text-[10px] text-faint">
              Se guarda con el tenant y sobrevive al cerrar la pestaña
            </span>
          </div>
          <ol className="max-h-56 space-y-2 overflow-auto pr-1">
            {conversation.map((item) => (
              <li
                key={item.id}
                className={`rounded-md px-2.5 py-2 text-[12px] leading-relaxed ${
                  item.role === "user"
                    ? "ml-5 bg-accent-soft/60 text-text"
                    : "mr-5 border border-border-soft bg-control text-muted"
                }`}
              >
                <p className="mb-0.5 text-[10px] uppercase tracking-wide text-faint">
                  {item.role === "user" ? "Tú" : "Zent"} · revisión {item.revision}
                </p>
                <p className="whitespace-pre-wrap">{item.content}</p>
              </li>
            ))}
          </ol>
        </div>
      )}

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
            {proposal.planner.version} · sesión de diseño {designSession?.id ?? proposal.session_id}
            {designSession ? ` · revisión ${designSession.revision}` : ""}
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

          {proposal.resource_resolution && (
            <div
              className="rounded-md border border-border-soft bg-surface px-3 py-2.5"
              data-testid="ask-resources"
            >
              <h3 className="text-h3 mb-2">Recursos reales</h3>
              {proposal.resource_resolution.selected ? (
                <p className="text-[12px] text-text">
                  Fuente resuelta:{" "}
                  <span className="mono text-[11px] text-accent">
                    {proposal.resource_resolution.selected.display_name ||
                      proposal.resource_resolution.selected.resource_ref}
                  </span>
                </p>
              ) : (
                <p className="text-[12px] text-muted">
                  No hay una fuente única resuelta todavía.
                </p>
              )}
              {proposal.resource_resolution.unresolved &&
                proposal.resource_resolution.unresolved.length > 0 && (
                  <ul className="mt-1 list-disc space-y-1 pl-4 text-[12px] text-muted">
                    {proposal.resource_resolution.unresolved.slice(0, 4).map((item, index) => (
                      <li key={`${item.code}-${index}`}>
                        {item.message || item.code}
                        {item.fields?.length ? ` (${item.fields.join(", ")})` : ""}
                      </li>
                    ))}
                  </ul>
                )}
              {proposal.resource_resolution.bindings &&
                proposal.resource_resolution.bindings.length > 0 && (
                  <p className="mt-1 text-[11px] text-faint">
                    Bindings:{" "}
                    {proposal.resource_resolution.bindings
                      .slice(0, 4)
                      .map(
                        (item) =>
                          `${item.capability_ref} (${item.provider_kind || "sin proveedor"})`,
                      )
                      .join(" · ")}
                  </p>
                )}
              {proposal.resource_resolution.guided_configuration &&
                proposal.resource_resolution.guided_configuration.length > 0 && (
                  <p className="mt-1 text-[11px] text-warn">
                    Configuración pendiente:{" "}
                    {proposal.resource_resolution.guided_configuration
                      .slice(0, 3)
                      .map((item) => item.title || item.code)
                      .join(" · ")}
                  </p>
                )}
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
                disabled={clarify.trim().length < 2 || busy === "plan" || sessionClosed}
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

          {proposal.readiness?.checks && proposal.readiness.checks.length > 0 && (
            <details
              className="rounded-md border border-border-soft bg-surface px-3 py-2"
              open={mode !== "simple"}
              data-testid="ask-readiness-checks"
            >
              <summary className="cursor-pointer text-[12px] font-medium text-text">
                Readiness por paso ({proposal.readiness.passed}/{proposal.readiness.total})
              </summary>
              <ul className="mt-2 space-y-1.5">
                {proposal.readiness.checks.map((check) => (
                  <li
                    key={`${check.key}-${check.node_id ?? ""}`}
                    className="flex flex-wrap items-start justify-between gap-2 border-b border-border-soft pb-1.5 last:border-0 last:pb-0"
                  >
                    <span className="text-[12px] text-text">
                      {check.label}
                      {check.node_id ? (
                        <span className="mono ml-1 text-[10px] text-faint">
                          nodo {check.node_id}
                        </span>
                      ) : null}
                      <span className="block text-[11px] text-muted">{check.message}</span>
                      {check.hint ? (
                        <span className="block text-[11px] text-faint">{check.hint}</span>
                      ) : null}
                    </span>
                    <Badge
                      tone={
                        check.status === "ok"
                          ? "ok"
                          : check.status === "error"
                            ? "danger"
                            : "warn"
                      }
                    >
                      {check.status === "ok"
                        ? "validado"
                        : check.status === "error"
                          ? "bloqueado"
                          : "revisar"}
                    </Badge>
                  </li>
                ))}
              </ul>
              {proposal.requirements.length > 0 && (
                <Link
                  to="/integrations"
                  className="mt-2 inline-flex items-center gap-1 text-[11px] font-medium text-accent hover:underline"
                >
                  Resolver integración o binding <ArrowRight size={11} aria-hidden />
                </Link>
              )}
            </details>
          )}

          {proposal.simulation_certification && (
            <div
              className="rounded-md border border-border-soft bg-surface px-3 py-2.5"
              data-testid="ask-certification"
            >
              <h3 className="text-h3 mb-1">Certificación de simulación</h3>
              <p className="text-[12px] text-muted">
                Estado:{" "}
                <span className="mono text-[11px] text-text">
                  {proposal.simulation_certification.state || "DRAFT"}
                </span>
                {proposal.simulation_certification.partial ? " · parcial" : ""}
                {proposal.simulation_certification.publishable ? " · publicable" : " · no publicable"}
              </p>
              {proposal.simulation_certification.scenarios &&
                proposal.simulation_certification.scenarios.length > 0 && (
                  <ul className="mt-1 space-y-0.5 text-[11px] text-muted">
                    {proposal.simulation_certification.scenarios.map((scenario) => (
                      <li key={scenario.scenario_id}>
                        {scenario.scenario_id}:{" "}
                        <span
                          className={
                            scenario.result === "PASSED" ? "text-ok" : "text-danger"
                          }
                        >
                          {scenario.result}
                        </span>
                        {scenario.unverified_nodes?.length
                          ? ` · sin verificar: ${scenario.unverified_nodes.join(", ")}`
                          : ""}
                      </li>
                    ))}
                  </ul>
                )}
              {proposal.simulation_certification.repair_suggestions &&
                proposal.simulation_certification.repair_suggestions.length > 0 && (
                  <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[11px] text-warn">
                    {proposal.simulation_certification.repair_suggestions
                      .slice(0, 3)
                      .map((item, index) => (
                        <li key={`${item.code || "repair"}-${index}`}>
                          {item.step_id ? `${item.step_id}: ` : ""}
                          {item.message || item.code}
                        </li>
                      ))}
                  </ul>
                )}
            </div>
          )}

          {proposal.patch?.summary && (
            <p className="rounded-md border border-border-soft bg-surface px-3 py-2 text-[12px] text-muted" data-testid="ask-patch-note">
              Cambio aplicado: {proposal.patch.summary}. Los pasos no afectados se conservaron.
              {proposal.diff ? (
                <span className="mt-0.5 block text-[11px] text-faint">
                  Diff semántico: {proposal.diff.added?.length ?? 0} agregado(s),{" "}
                  {proposal.diff.removed?.length ?? 0} quitado(s),{" "}
                  {proposal.diff.modified?.length ?? 0} modificado(s).
                </span>
              ) : null}
            </p>
          )}

          {revisions.length > 0 && (
            <details
              className="rounded-md border border-border-soft bg-surface px-3 py-2"
              data-testid="ask-revisions"
            >
              <summary className="flex cursor-pointer items-center gap-1.5 text-[12px] font-medium text-text">
                <ClockCounterClockwise size={13} aria-hidden /> Historial de revisiones (
                {revisions.length})
              </summary>
              <ul className="mt-2 space-y-1.5">
                {revisions.slice(0, 8).map((item) => (
                  <li
                    key={item.revision}
                    className="flex flex-wrap items-center justify-between gap-2 border-b border-border-soft pb-1.5 last:border-0 last:pb-0"
                  >
                    <span className="text-[11px] text-muted">
                      <span className="mono text-[10px] text-accent">r{item.revision}</span>{" "}
                      {item.summary || item.instruction || item.kind}
                      {item.created_at ? ` · ${new Date(item.created_at).toLocaleString()}` : ""}
                    </span>
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={!!busy || !designSession || item.revision === designSession.revision}
                      data-testid={`ask-restore-${item.revision}`}
                      onClick={() => void restoreRevision(item.revision)}
                    >
                      {item.revision === designSession?.revision ? "Actual" : "Restaurar"}
                    </Button>
                  </li>
                ))}
              </ul>
            </details>
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
              disabled={!!busy || sessionClosed}
              data-testid="ask-change"
              aria-expanded={patchOpen}
              onClick={() => {
                setPatchOpen((value) => !value);
                setShowPlan(false);
              }}
            >
              Corregir por conversación
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
            {designSession && proposal.plan && !sessionClosed && (
              <Button
                variant="ghost"
                leadingIcon={Checks}
                loading={busy === "simulate"}
                disabled={!!busy}
                data-testid="ask-simulate"
                aria-expanded={simulationOpen}
                onClick={() => setSimulationOpen((value) => !value)}
              >
                Probar simulación
              </Button>
            )}
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

          {simulationOpen && (
            <div
              className="space-y-2 rounded-md border border-border bg-surface px-3 py-2.5"
              data-testid="ask-simulation"
            >
              <p className="text-[12px] text-muted">
                La simulación corre en el backend con nodos externos fijados. No escribe en base
                de datos ni ejecuta acciones reales; los nodos sin respuesta quedan sin verificar.
              </p>
              <Textarea
                rows={4}
                className="min-h-24 font-mono text-[11px]"
                value={scenarioText}
                data-testid="ask-scenarios"
                onChange={(e) => setScenarioText(e.target.value)}
                aria-label="Escenarios de simulación"
              />
              <Button
                variant="secondary"
                size="sm"
                leadingIcon={Checks}
                loading={busy === "simulate"}
                disabled={busy === "simulate" || !scenarioText.trim()}
                data-testid="ask-simulate-submit"
                onClick={() => void runSimulation()}
              >
                Ejecutar simulación
              </Button>
            </div>
          )}

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
                onChange={(e) => {
                  setPatchText(e.target.value);
                  setPatchPreview(null);
                }}
                aria-label="Cambio pedido"
              />
              <Button
                variant="secondary"
                size="sm"
                leadingIcon={PencilSimple}
                loading={busy === "patch"}
                disabled={patchText.trim().length < 3 || busy === "patch" || sessionClosed}
                data-testid="ask-patch-submit"
                onClick={() => void applyPatch()}
              >
                Previsualizar cambio
              </Button>
              {patchPreview && (
                <div
                  className="space-y-2 rounded-md border border-accent-line bg-accent-soft/40 px-3 py-2"
                  data-testid="ask-patch-preview"
                >
                  <p className="text-[12px] font-medium text-text">
                    Diff semántico antes de aplicar
                  </p>
                  <p className="text-[11px] text-muted">
                    {patchPreview.diff?.summary ||
                      patchPreview.proposal.patch?.summary ||
                      "Cambio preparado"}
                    . Se conservan los pasos no afectados.
                  </p>
                  {patchPreview.diff ? (
                    <ul className="list-disc space-y-0.5 pl-4 text-[11px] text-muted">
                      {(patchPreview.diff.added ?? []).map((item) => (
                        <li key={`add-${item.step_id}`}>Agregar: {item.goal || item.step_id}</li>
                      ))}
                      {(patchPreview.diff.removed ?? []).map((item) => (
                        <li key={`remove-${item.step_id}`}>Quitar: {item.goal || item.step_id}</li>
                      ))}
                      {(patchPreview.diff.modified ?? []).map((item) => (
                        <li key={`mod-${item.step_id}`}>
                          Modificar: {item.step_id} ({Object.keys(item.fields ?? {}).join(", ")})
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="primary"
                      size="sm"
                      leadingIcon={Checks}
                      loading={busy === "patch"}
                      disabled={busy === "patch"}
                      data-testid="ask-patch-confirm"
                      onClick={() => void confirmPatch()}
                    >
                      Confirmar y aplicar
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={busy === "patch"}
                      data-testid="ask-patch-cancel"
                      onClick={() => setPatchPreview(null)}
                    >
                      Descartar
                    </Button>
                  </div>
                </div>
              )}
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
