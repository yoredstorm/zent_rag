import { ArrowRight, CheckCircle, Link as LinkIcon, Sparkle } from "@phosphor-icons/react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Badge,
  Button,
  ErrorInline,
  Field,
  PageHeader,
  Panel,
  PanelHeader,
  SuccessInline,
  Textarea,
} from "../components/ui";

type Blocker = { code: string; message: string; action?: string };
type Compilation = {
  compilation_hash: string;
  status: string;
  can_materialize: boolean;
  mode?: string;
  template_id: string;
  plan: {
    role: { name: string; action: string };
    agent: { name: string; action: string };
    workflow: { name: string; action: string; will_create: boolean };
    sources: { logical_ref: string; physical_id: string }[];
  };
  requirements: { capability_ref: string; status: string; required: boolean }[];
  blockers: Blocker[];
  scenarios: { scenario_id: string; messages?: string[] }[];
};
type Materialization = {
  solution_id: string;
  status: string;
  artifacts: {
    workflow?: { id: string; created: boolean };
    agent?: { id: string; created: boolean };
    role?: { id: string; created: boolean };
  };
  blockers: Blocker[];
};

export default function SolutionBuilderPage() {
  const { session } = useAuth();
  const [params] = useSearchParams();
  const [brief, setBrief] = useState(params.get("brief") || "");
  const [templateId, setTemplateId] = useState("");
  const [mode, setMode] = useState("auto");
  const [compiled, setCompiled] = useState<Compilation | null>(null);
  const [materialized, setMaterialized] = useState<Materialization | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const auth = session
    ? { token: session.token, organizationId: session.organizationId }
    : { token: "", organizationId: "" };

  const payload = {
    brief: brief.trim(),
    template_id: templateId || null,
    mode,
  };

  async function compile() {
    if (!brief.trim()) {
      setError("Describe qué quieres que haga ZENT.");
      return;
    }
    setBusy("compile");
    setError("");
    setSuccess("");
    setMaterialized(null);
    try {
      const result = await api<Compilation>("/api/v1/studio/solutions/compile", {
        ...auth,
        method: "POST",
        body: JSON.stringify(payload),
      });
      setCompiled(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo preparar la solución.");
    } finally {
      setBusy("");
    }
  }

  async function materialize() {
    if (!compiled || !reviewed) return;
    setBusy("materialize");
    setError("");
    setSuccess("");
    try {
      const result = await api<Materialization>("/api/v1/studio/solutions/materialize", {
        ...auth,
        method: "POST",
        body: JSON.stringify({
          ...payload,
          confirm: true,
          idempotency_key: compiled.compilation_hash,
        }),
      });
      setMaterialized(result);
      setSuccess(
        result.status === "READY"
          ? "Solución preparada. Revisa el proceso y pruébalo."
          : "Recursos creados. Faltan dependencias para terminar de configurar.",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo materializar la solución.");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6" data-testid="solution-builder">
      <PageHeader
        title="Preparar una solución"
        subtitle="Describe la misión. ZENT propone rol, agente y proceso; tú revisas antes de crear recursos."
      />

      <Panel>
        <PanelHeader
          title="1. ¿Qué quieres que ZENT haga?"
          description="Una frase con el resultado esperado. Sin JSON, UUID ni SQL."
        />
        <div className="space-y-3 p-4">
          <Field label="Misión">
            <Textarea
              value={brief}
              onChange={(event) => setBrief(event.target.value)}
              rows={3}
              placeholder="Ej: Quiero un mentor de Python con progreso y ejercicios"
              data-testid="solution-brief"
            />
          </Field>
          <Field
            label="Modo de composición"
            hint="Automático usa una plantilla si cubre la misión; Composición crea un flujo nuevo con el Architect."
          >
            <select
              className="min-h-10 w-full rounded-md border border-border bg-surface px-3 text-sm"
              value={mode}
              onChange={(event) => setMode(event.target.value)}
              data-testid="solution-mode"
            >
              <option value="auto">Automático</option>
              <option value="hybrid">Híbrido</option>
              <option value="compose">Composición nueva</option>
              <option value="template">Solo plantilla</option>
            </select>
          </Field>
          <Field label="Plantilla (opcional)" hint="Si no eliges, ZENT infiere la función.">
            <select
              className="min-h-10 w-full rounded-md border border-border bg-surface px-3 text-sm"
              value={templateId}
              onChange={(event) => setTemplateId(event.target.value)}
              data-testid="solution-template"
            >
              <option value="">Automático</option>
              <option value="mentor">Mentor</option>
              <option value="tutor">Tutor</option>
              <option value="sales_advisor">Ventas</option>
              <option value="auditor">Auditoría</option>
              <option value="support_agent">Soporte</option>
              <option value="wellness_companion">Bienestar no clínico</option>
            </select>
          </Field>
          <Button
            variant="primary"
            leadingIcon={Sparkle}
            loading={busy === "compile"}
            disabled={!!busy}
            onClick={() => void compile()}
            data-testid="solution-compile"
          >
            Preparar solución
          </Button>
          <ErrorInline message={error} className="mb-0" />
        </div>
      </Panel>

      {compiled && (
        <Panel data-testid="solution-plan">
          <PanelHeader
            title="2. Revisar recursos"
            description="Nada se creó todavía. Revisa qué se reutilizará y qué falta."
          />
          <div className="space-y-3 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={compiled.can_materialize ? "ok" : "warn"}>
                {compiled.can_materialize ? "Lista para preparar" : "Faltan dependencias"}
              </Badge>
              <Badge tone="info">
                {compiled.template_id === "composed"
                  ? "Composición nueva"
                  : `Plantilla: ${compiled.template_id}`}
              </Badge>
              <span className="text-xs text-faint">
                {compiled.scenarios.length} escenario(s) de prueba preparados
              </span>
            </div>
            <ul className="space-y-2 text-sm" data-testid="solution-resources">
              <li className="rounded-md border border-border p-3">
                <span className="font-medium">Rol:</span> {compiled.plan.role.name}
              </li>
              <li className="rounded-md border border-border p-3">
                <span className="font-medium">Agente:</span> {compiled.plan.agent.name}
              </li>
              <li className="rounded-md border border-border p-3">
                <span className="font-medium">Proceso:</span> {compiled.plan.workflow.name}
              </li>
            </ul>
            {compiled.blockers.length > 0 && (
              <div className="space-y-2" data-testid="solution-blockers">
                {compiled.blockers.map((item) => (
                  <p key={item.code} className="rounded-md border border-warn/40 bg-warn/10 p-3 text-sm">
                    <span className="font-medium">{item.message}</span>{" "}
                    {item.action || "Configúralo antes de publicar."}
                  </p>
                ))}
              </div>
            )}
            {compiled.requirements.length > 0 && (
              <div className="space-y-1 text-xs text-muted" data-testid="solution-requirements">
                {compiled.requirements.map((item) => (
                  <p key={item.capability_ref}>
                    {item.capability_ref}: {item.status}
                  </p>
                ))}
              </div>
            )}
            <label className="flex items-start gap-2 text-sm text-muted">
              <input
                type="checkbox"
                checked={reviewed}
                onChange={(event) => setReviewed(event.target.checked)}
                data-testid="solution-reviewed"
                className="mt-1"
              />
              Revisé los recursos y quiero crearlos como borrador.
            </label>
            <Button
              variant="primary"
              leadingIcon={CheckCircle}
              loading={busy === "materialize"}
              disabled={!!busy || !reviewed}
              onClick={() => void materialize()}
              data-testid="solution-materialize"
            >
              Confirmar y materializar
            </Button>
            <SuccessInline message={success} className="mb-0" />
          </div>
        </Panel>
      )}

      {materialized && (
        <Panel data-testid="solution-result">
          <PanelHeader
            title="3. Resultado"
            description={
              materialized.status === "READY"
                ? "El proceso quedó como borrador ejecutable."
                : "Los recursos creados se conservan; configura lo pendiente y vuelve a preparar."
            }
          />
          <div className="flex flex-wrap items-center gap-2 p-4">
            <Badge tone={materialized.status === "READY" ? "ok" : "warn"}>
              {materialized.status === "READY" ? "Solución preparada" : "Requiere configuración"}
            </Badge>
            {materialized.solution_id && (
              <Link
                to={`/solutions/${materialized.solution_id}`}
                className="inline-flex items-center gap-1 text-sm text-accent"
                data-testid="solution-open-workspace"
              >
                Abrir Solution Workspace <ArrowRight className="h-4 w-4" />
              </Link>
            )}
            {materialized.artifacts.workflow && (
              <Link
                to={`/workflows/${materialized.artifacts.workflow.id}`}
                className="inline-flex items-center gap-1 text-sm text-muted"
                data-testid="solution-open-workflow"
              >
                Abrir proceso <ArrowRight className="h-4 w-4" />
              </Link>
            )}
            <Link to="/agents" className="inline-flex items-center gap-1 text-sm text-muted">
              <LinkIcon className="h-4 w-4" /> Ver agentes
            </Link>
          </div>
        </Panel>
      )}
    </div>
  );
}
