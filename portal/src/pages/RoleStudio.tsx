/**
 * Role Studio — "Describe la función" before touching prompts or graphs.
 *
 * A role is a mission sheet, not a second Agent. This page proposes an editable
 * draft from a prompt, shows what it will/will not do, and lets the user link
 * the saved role to an existing Agent. Execution stays in the Agent runtime.
 */
import { ArrowRight, CheckCircle, Robot, ShieldCheck, Sparkle, UserCircle } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Breadcrumb } from "../components/Breadcrumb";
import {
  Badge,
  Button,
  ButtonLink,
  EmptyState,
  ErrorInline,
  Field,
  Input,
  PageHeader,
  Panel,
  PanelHeader,
  Select,
  SkeletonBlock,
  SuccessInline,
  Textarea,
} from "../components/ui";

type Role = {
  record_id?: string;
  schema: string;
  role_id: string;
  version: string;
  status: string;
  name: string;
  display_name?: string;
  description: string;
  mission: string;
  audience: string[];
  tone: string[];
  competencies: { name: string; description?: string; level?: string }[];
  constraints: string[];
  allowed_capabilities: string[];
  denied_capabilities: string[];
  allowed_tools: string[];
  knowledge_scope: { kinds?: string[]; domains?: string[]; tags?: string[]; notes?: string };
  memory_policy: Record<string, unknown>;
  autonomy_level: string;
  human_handoff: { triggers?: string[]; destination?: string; message?: string };
  expected_outcomes: { name: string; metric: string; target?: string; window?: string }[];
  evaluation_rubric: unknown[];
  risk_class: string;
  locales: string[];
  compliance_tags: string[];
  safety: Record<string, unknown>;
};

type MissionSheet = {
  role_id: string;
  name: string;
  mission: string;
  will_do: string[];
  will_not_do: string[];
  autonomy_level: string;
  handoff: { triggers?: string[]; destination?: string; message?: string };
  outcomes: { name: string; metric: string; target?: string }[];
  disclaimer?: string;
};

type Proposal = {
  source: string;
  template_id: string;
  confidence: number;
  role: Role;
  mission_sheet: MissionSheet;
  workflow_proposal?: {
    workflow_ref: string;
    name: string;
    trigger: string;
    design_steps: string[];
  } | null;
  requires_review: boolean;
  publishable: boolean;
};

type AgentSummary = { id: string; name: string; status?: string };

const AUTONOMY = [
  { value: "answer_only", label: "Solo responder" },
  { value: "propose_actions", label: "Proponer acciones" },
  { value: "execute_reversible", label: "Ejecutar acciones reversibles" },
  { value: "require_approval", label: "Pedir aprobación para consecuencias" },
];

const RISK = [
  { value: "low", label: "Bajo" },
  { value: "medium", label: "Medio" },
  { value: "high", label: "Alto" },
  { value: "regulated", label: "Regulado / sensible" },
];

function splitList(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function autonomyLabel(value: string): string {
  return AUTONOMY.find((item) => item.value === value)?.label ?? value;
}

function sheetFromRole(role: Role): MissionSheet {
  return {
    role_id: role.role_id,
    name: role.name,
    mission: role.mission,
    will_do: role.competencies.map((item) => item.name),
    will_not_do: role.constraints.length
      ? role.constraints
      : ["No actúa fuera de su misión declarada."],
    autonomy_level: role.autonomy_level,
    handoff: role.human_handoff,
    outcomes: role.expected_outcomes,
  };
}

export default function RoleStudioPage() {
  const { session } = useAuth();
  const [templates, setTemplates] = useState<{ role_id: string; name: string }[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [prompt, setPrompt] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [draft, setDraft] = useState<Role | null>(null);
  const [sheet, setSheet] = useState<MissionSheet | null>(null);
  const [workflowProposal, setWorkflowProposal] = useState<Proposal["workflow_proposal"]>(null);
  const [selectedAgent, setSelectedAgent] = useState("");
  const [linkMessage, setLinkMessage] = useState("");
  const [solutionMessage, setSolutionMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [proposing, setProposing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const auth = useMemo(
    () => ({ token: session?.token, organizationId: session?.organizationId }),
    [session?.token, session?.organizationId],
  );

  async function load() {
    if (!session) return;
    setLoading(true);
    try {
      const [templateData, roleData, agentData] = await Promise.all([
        api<{ templates: { role_id: string; name: string }[] }>("/api/v1/studio/templates", auth),
        api<{ roles: Role[] }>("/api/v1/studio/roles", auth),
        api<{ agents: AgentSummary[] }>("/api/v1/agents", auth),
      ]);
      setTemplates(templateData.templates || []);
      setRoles(roleData.roles || []);
      setAgents(agentData.agents || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudieron cargar los roles.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.organizationId]);

  async function propose() {
    if (!prompt.trim()) {
      setError("Describe la función en una frase.");
      return;
    }
    setProposing(true);
    setError("");
    setSuccess("");
    try {
      const proposal = await api<Proposal>("/api/v1/studio/roles/propose", {
        ...auth,
        method: "POST",
        body: JSON.stringify({ prompt: prompt.trim(), template_id: templateId || null }),
      });
      setDraft(proposal.role);
      setSheet(proposal.mission_sheet);
      setWorkflowProposal(proposal.workflow_proposal ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo proponer el rol.");
    } finally {
      setProposing(false);
    }
  }

  async function save() {
    if (!draft) return;
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const path = draft.record_id
        ? `/api/v1/studio/roles/${draft.record_id}`
        : "/api/v1/studio/roles";
      const response = await api<{ role: Role; mission_sheet: MissionSheet }>(path, {
        ...auth,
        method: draft.record_id ? "PUT" : "POST",
        body: JSON.stringify({ role: draft }),
      });
      setDraft(response.role);
      setSheet(response.mission_sheet);
      setSuccess("Rol guardado como borrador editable. Revísalo antes de activarlo.");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar el rol.");
    } finally {
      setSaving(false);
    }
  }

  async function linkAgent() {
    if (!draft?.record_id || !selectedAgent) return;
    try {
      await api(`/api/v1/studio/agents/${selectedAgent}/role`, {
        ...auth,
        method: "POST",
        body: JSON.stringify({ role_profile_id: draft.record_id }),
      });
      setLinkMessage("Agente vinculado. Al ejecutar, el rol sólo puede reducir sus herramientas.");
    } catch (e) {
      setLinkMessage(e instanceof Error ? e.message : "No se pudo vincular el agente.");
    }
  }

  async function createDraftSolution() {
    if (!draft?.record_id) return;
    setSolutionMessage("");
    try {
      const solution = {
        schema: "zent.solution/v1",
        solution_id: `${draft.role_id}_solution`,
        version: "1.0.0",
        status: "draft",
        name: `Solución: ${draft.name}`.slice(0, 150),
        description: draft.mission,
        roles: [{ role_ref: draft.role_id, version: draft.version, required: true }],
        agents: [],
        workflows: workflowProposal
          ? [
              {
                workflow_ref: workflowProposal.workflow_ref,
                name: workflowProposal.name,
                role_refs: [draft.role_id],
                agent_refs: [],
                capability_refs: draft.allowed_capabilities,
                trigger: { type: workflowProposal.trigger },
                requirements: [],
              },
            ]
          : [],
        capabilities: draft.allowed_capabilities.map((ref) => ({
          capability_ref: ref,
          required: true,
          purpose: "",
        })),
        knowledge: [],
        channels: [],
        requirements: ["review_roles", "review_workflow"],
        installation: [
          {
            order: 1,
            action: "review_roles",
            module: "studio",
            description: "Revisar el rol y su hoja de misión.",
            required: true,
          },
        ],
        expected_outcomes: draft.expected_outcomes,
        risk_class: draft.risk_class,
        compliance_tags: draft.compliance_tags,
        locales: draft.locales,
      };
      await api("/api/v1/studio/solutions", {
        ...auth,
        method: "POST",
        body: JSON.stringify({ solution }),
      });
      setSolutionMessage("Solución borrador creada. Revísala en la API de Studio antes de instalar.");
    } catch (e) {
      setSolutionMessage(e instanceof Error ? e.message : "No se pudo crear la solución.");
    }
  }

  function edit<K extends keyof Role>(key: K, value: Role[K]) {
    setDraft((current) => {
      if (!current) return current;
      if (key === "name") {
        return { ...current, name: value as string, display_name: value as string };
      }
      return { ...current, [key]: value };
    });
  }

  const canSave = Boolean(draft?.name.trim() && draft?.mission.trim() && draft?.role_id.trim());

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb items={[{ label: "Construir", to: "/roles" }, { label: "Roles" }]} />
      <PageHeader
        className="mb-0"
        title="Roles"
        subtitle="Describe la función. Zent propone una identidad, límites, recursos y métricas; tú revisas antes de guardar."
        actions={draft ? <Badge tone="warn">Borrador editable</Badge> : undefined}
      />
      <ErrorInline message={error} className="mb-0" />
      <SuccessInline message={success} className="mb-0" />

      <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        <div className="flex flex-col gap-4">
          <Panel>
            <PanelHeader
              title="1. Describe la función"
              description="Una frase basta: qué necesita lograr, para quién y con qué límites."
            />
            <div className="flex flex-col gap-3 p-4">
              <Field label="¿Qué función quieres cubrir?" id="role-prompt">
                <Textarea
                  id="role-prompt"
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  rows={3}
                  placeholder="Ej. Un mentor que ayude a profesionales a convertir objetivos en un plan de práctica medible."
                  data-testid="role-prompt"
                />
              </Field>
              <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
                <Field label="Plantilla base" id="role-template">
                  <Select
                    id="role-template"
                    value={templateId}
                    onChange={(event) => setTemplateId(event.target.value)}
                  >
                    <option value="">Detectar automáticamente</option>
                    {templates.map((template) => (
                      <option key={template.role_id} value={template.role_id}>
                        {template.name}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Button
                  variant="primary"
                  leadingIcon={Sparkle}
                  onClick={() => void propose()}
                  disabled={proposing || !prompt.trim()}
                >
                  {proposing ? "Proponiendo..." : "Proponer rol"}
                </Button>
              </div>
            </div>
          </Panel>

          {draft && sheet ? (
            <Panel data-testid="role-review">
              <PanelHeader
                title="2. Revisa la hoja de misión"
                description="Lo que hará y lo que no hará. Editable antes de guardar."
                actions={
                  <Badge tone={draft.risk_class === "regulated" ? "danger" : "neutral"}>
                    {draft.risk_class}
                  </Badge>
                }
              />
              <div className="grid gap-4 p-4">
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Nombre" id="role-name">
                    <Input
                      id="role-name"
                      value={draft.name}
                      onChange={(event) => edit("name", event.target.value)}
                    />
                  </Field>
                  <Field label="ID estable" id="role-id" hint="a-z, 0-9, _ y -">
                    <Input
                      id="role-id"
                      value={draft.role_id}
                      onChange={(event) => edit("role_id", event.target.value)}
                    />
                  </Field>
                </div>
                <Field label="Misión" id="role-mission">
                  <Textarea
                    id="role-mission"
                    value={draft.mission}
                    rows={2}
                    onChange={(event) => edit("mission", event.target.value)}
                  />
                </Field>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Público" id="role-audience" hint="separado por comas">
                    <Input
                      id="role-audience"
                      value={draft.audience.join(", ")}
                      onChange={(event) => edit("audience", splitList(event.target.value))}
                    />
                  </Field>
                  <Field label="Nivel de autonomía" id="role-autonomy">
                    <Select
                      id="role-autonomy"
                      value={draft.autonomy_level}
                      onChange={(event) => edit("autonomy_level", event.target.value)}
                    >
                      {AUTONOMY.map((item) => (
                        <option key={item.value} value={item.value}>
                          {item.label}
                        </option>
                      ))}
                    </Select>
                  </Field>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Límites" id="role-constraints" hint="uno por línea">
                    <Textarea
                      id="role-constraints"
                      rows={3}
                      value={draft.constraints.join("\n")}
                      onChange={(event) => edit("constraints", splitList(event.target.value))}
                    />
                  </Field>
                  <Field label="Capacidades permitidas" id="role-caps" hint="separadas por comas">
                    <Textarea
                      id="role-caps"
                      rows={3}
                      value={draft.allowed_capabilities.join(", ")}
                      onChange={(event) => edit("allowed_capabilities", splitList(event.target.value))}
                    />
                  </Field>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Riesgo" id="role-risk">
                    <Select
                      id="role-risk"
                      value={draft.risk_class}
                      onChange={(event) => edit("risk_class", event.target.value)}
                    >
                      {RISK.map((item) => (
                        <option key={item.value} value={item.value}>
                          {item.label}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field
                    label="Estado"
                    id="role-status"
                    hint="Activo aplica restricciones al ejecutar."
                  >
                    <Select
                      id="role-status"
                      value={draft.status}
                      onChange={(event) => edit("status", event.target.value)}
                    >
                      <option value="draft">Borrador</option>
                      <option value="active">Activo</option>
                      <option value="archived">Archivado</option>
                    </Select>
                  </Field>
                </div>

                <div
                  className="grid gap-3 rounded-md border border-border bg-raised p-3 sm:grid-cols-2"
                  data-testid="mission-sheet"
                >
                  <div>
                    <p className="mb-2 flex items-center gap-2 text-sm font-medium">
                      <CheckCircle className="text-ok" /> Hará
                    </p>
                    <ul className="list-disc pl-5 text-sm text-muted">
                      {sheet.will_do.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <p className="mb-2 flex items-center gap-2 text-sm font-medium">
                      <ShieldCheck className="text-warn" /> No hará
                    </p>
                    <ul className="list-disc pl-5 text-sm text-muted">
                      {sheet.will_not_do.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                </div>
                {sheet.outcomes.length ? (
                  <div className="rounded-md border border-border p-3">
                    <p className="text-sm font-medium">Métricas</p>
                    <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
                      {sheet.outcomes.map((outcome) => (
                        <li key={outcome.name}>
                          {outcome.name}: {outcome.metric}
                          {outcome.target ? ` · ${outcome.target}` : ""}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {workflowProposal ? (
                  <div className="rounded-md border border-border p-3" data-testid="workflow-proposal">
                    <p className="text-sm font-medium">{workflowProposal.name}</p>
                    <p className="mt-1 text-xs text-faint">
                      Proceso sugerido, no publicado. Se revisa y se crea como workflow aparte.
                    </p>
                    <ol className="mt-2 flex flex-wrap gap-2 text-xs text-muted">
                      {workflowProposal.design_steps.map((step, index) => (
                        <li key={step} className="rounded-sm border border-border bg-raised px-2 py-1">
                          {index + 1}. {step}
                        </li>
                      ))}
                    </ol>
                  </div>
                ) : null}
                <p className="text-xs text-faint">
                  Autonomía efectiva: {autonomyLabel(draft.autonomy_level)}. La autoridad real
                  sigue siendo la intersección de usuario, servicio, tenant, políticas y
                  herramienta instalada.
                </p>
                {sheet.disclaimer ? (
                  <p className="rounded-md border border-warn/40 bg-warn/10 p-3 text-sm text-warn">
                    {sheet.disclaimer}
                  </p>
                ) : null}
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    variant="primary"
                    onClick={() => void save()}
                    disabled={saving || !canSave}
                    data-testid="save-role"
                  >
                    {saving ? "Guardando..." : draft.record_id ? "Guardar nueva versión" : "Guardar borrador"}
                  </Button>
                  <ButtonLink
                    to={`/solutions/new?brief=${encodeURIComponent(draft.mission || prompt)}`}
                    variant="secondary"
                    data-testid="prepare-solution"
                  >
                    Preparar solución completa
                  </ButtonLink>
                  <span className="text-xs text-faint">
                    {draft.record_id ? `Versión ${draft.version}` : "Aún no guardado"}
                  </span>
                </div>
              </div>
            </Panel>
          ) : (
            <Panel>
              <EmptyState
                icon={UserCircle}
                title="Todavía no hay una hoja de misión"
                body="Escribe la función y pide una propuesta. No se publica nada hasta que la revises y guardes."
              />
            </Panel>
          )}

          {draft?.record_id ? (
            <Panel data-testid="role-agent-link">
              <PanelHeader
                title="3. Vincular a un agente existente"
                description="El rol no crea otro agente. Sólo restringe las herramientas del agente que ya existe."
              />
              <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-end">
                <Field label="Agente" id="role-agent" className="flex-1">
                  <Select
                    id="role-agent"
                    value={selectedAgent}
                    onChange={(event) => setSelectedAgent(event.target.value)}
                  >
                    <option value="">Elige un agente</option>
                    {agents.map((agent) => (
                      <option key={agent.id} value={agent.id}>
                        {agent.name}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Button
                  leadingIcon={Robot}
                  onClick={() => void linkAgent()}
                  disabled={!selectedAgent}
                >
                  Vincular
                </Button>
              </div>
              {linkMessage ? <p className="px-4 pb-4 text-sm text-muted">{linkMessage}</p> : null}
              {selectedAgent ? (
                <div className="px-4 pb-4">
                  <ButtonLink to={`/agents/${selectedAgent}`} size="sm">
                    Probar en Agent Studio
                  </ButtonLink>
                </div>
              ) : null}
              <div className="flex flex-wrap items-center gap-3 border-t border-border px-4 py-3">
                <Button size="sm" variant="secondary" onClick={() => void createDraftSolution()}>
                  Crear solución borrador
                </Button>
                <span className="text-xs text-faint">
                  Agrupa este rol, el proceso sugerido y sus requisitos. No instala nada.
                </span>
              </div>
              {solutionMessage ? (
                <p className="px-4 pb-4 text-sm text-muted">{solutionMessage}</p>
              ) : null}
            </Panel>
          ) : null}
        </div>

        <Panel className="self-start">
          <PanelHeader
            title="Roles del workspace"
            description="Borradores y roles activos. Un rol es identidad; el agente es quien ejecuta."
          />
          <div className="p-4">
            {loading ? (
              <SkeletonBlock rows={5} />
            ) : roles.length === 0 ? (
              <p className="text-sm text-muted">
                Aún no hay roles. El primero empieza con la descripción de arriba.
              </p>
            ) : (
              <ul className="flex flex-col gap-2" data-testid="role-list">
                {roles.map((role) => (
                  <li key={role.record_id || role.role_id}>
                    <button
                      type="button"
                      className="flex w-full items-start justify-between gap-3 rounded-md border border-border bg-raised p-3 text-left transition-colors hover:border-accent"
                      onClick={() => {
                        setDraft(role);
                        setSheet(sheetFromRole(role));
                        setWorkflowProposal(null);
                        setLinkMessage("");
                        setSolutionMessage("");
                        setSuccess("");
                        setError("");
                        if (role.record_id) {
                          void api<MissionSheet>(
                            `/api/v1/studio/roles/${role.record_id}/mission-sheet`,
                            auth,
                          )
                            .then(setSheet)
                            .catch(() => undefined);
                        }
                      }}
                    >
                      <span>
                        <span className="block text-sm font-medium">{role.name}</span>
                        <span className="mt-1 block text-xs text-faint">
                          {role.role_id} · v{role.version}
                        </span>
                      </span>
                      <Badge tone={role.status === "active" ? "ok" : "neutral"}>{role.status}</Badge>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="mt-4 flex items-center gap-2 text-xs text-faint">
              <ArrowRight /> Elige un rol para editarlo o crear una nueva versión.
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}
