/**
 * Asistentes — el mismo agente visto en operación: qué vigila y si algo falló.
 */
import { Clock, Robot } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Breadcrumb } from "../components/Breadcrumb";
import {
  Badge,
  ButtonLink,
  EmptyState,
  ErrorInline,
  PageHeader,
  Panel,
  SkeletonBlock,
  Toolbar,
  ToolbarSpacer,
} from "../components/ui";
import { COPY, HEALTH_STATUS, type AssistantCard } from "./assistants/assistantCopy";

function timeAgo(value: string | null): string {
  if (!value) return "sin actividad todavía";
  const diff = Date.now() - new Date(value).getTime();
  const minutes = Math.max(1, Math.round(diff / 60_000));
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `hace ${hours} h`;
  return `hace ${Math.round(hours / 24)} días`;
}

/** Salud real del asistente para el activity rail. */
function railState(health: string): "ready" | "queued" | "failed" {
  if (health === "healthy") return "ready";
  if (health === "needs_attention") return "failed";
  return "queued";
}

const HEALTH_TONE: Record<string, "ok" | "danger" | "warn" | "neutral"> = {
  healthy: "ok",
  needs_attention: "danger",
  paused: "warn",
  idle: "neutral",
};

export default function AssistantsPage() {
  const { session } = useAuth();
  const [assistants, setAssistants] = useState<AssistantCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    api<{ assistants: AssistantCard[] }>("/api/v1/agents/assistants", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => setAssistants(data.assistants || []))
      .catch((e) => setError(e instanceof Error ? e.message : "Error"))
      .finally(() => setLoading(false));
  }, [session]);

  const needingAttention = assistants.filter((a) => a.health === "needs_attention").length;

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb items={[{ label: "Operar", to: "/assistants" }, { label: "Asistentes" }]} />
      <PageHeader
        className="mb-0"
        title="Asistentes"
        subtitle={COPY.listSubtitle}
        actions={
          <div className="flex flex-col items-end gap-1">
            <ButtonLink to="/agents/new" size="sm" leadingIcon={Robot}>
              {COPY.createAgent}
            </ButtonLink>
            <p className="text-xs text-faint">{COPY.createHint}</p>
          </div>
        }
      />
      <ErrorInline message={error} className="mb-0" />

      {loading ? (
        <Panel className="p-4">
          <SkeletonBlock rows={4} />
        </Panel>
      ) : assistants.length === 0 ? (
        <Panel data-testid="assistants-empty">
          <EmptyState
            icon={Robot}
            title="Ningún asistente en operación"
            body={COPY.empty}
            action={
              <ButtonLink to="/agents/new" variant="primary" leadingIcon={Robot}>
                {COPY.createAgent}
              </ButtonLink>
            }
          />
        </Panel>
      ) : (
        <>
          <Toolbar>
            <p className="text-xs text-muted tabular-nums">
              {assistants.length === 1 ? "1 asistente" : `${assistants.length} asistentes`}
              {needingAttention > 0
                ? ` · ${needingAttention} necesita${needingAttention === 1 ?" atención" : "n atención"}`
                : " · todo en orden"}
            </p>
            <ToolbarSpacer />
            <span className="text-xs text-faint">
              Un asistente es un agente en operación: sus automatizaciones lo mantienen trabajando.
            </span>
          </Toolbar>

          <ul className="grid gap-3">
            {assistants.map((assistant) => {
              const health = HEALTH_STATUS[assistant.health] ?? HEALTH_STATUS.idle;
              return (
                <li key={assistant.id}>
                  <article className="panel" data-testid={`assistant-${assistant.id}`}>
                    <div className="state-rail p-4 pl-5" data-state={railState(assistant.health)}>
                      <div className="flex flex-wrap items-start justify-between gap-4">
                        <div className="flex min-w-0 gap-3">
                          <span
                            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-accent-line bg-accent-soft text-accent"
                            aria-hidden
                          >
                            <Robot size={17} />
                          </span>
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <h2 className="min-w-0 text-h3">{assistant.name}</h2>
                              <Badge tone={HEALTH_TONE[assistant.health] ?? "neutral"} dot>
                                {health}
                              </Badge>
                            </div>
                            {assistant.description && (
                              <p className="mt-0.5 text-[13px] leading-relaxed text-muted">
                                {assistant.description}
                              </p>
                            )}
                            <p className="eyebrow mt-2">Qué está vigilando</p>
                            {assistant.watches.length === 0 ? (
                              <p className="mt-1 text-[13px] text-muted">
                                Nada todavía. Agrega una automatización para que trabaje solo.
                              </p>
                            ) : (
                              <ul className="mt-1 space-y-1">
                                {assistant.watches.map((watch) => (
                                  <li key={watch} className="flex items-start gap-2 text-[13px] text-muted">
                                    <Clock size={13} className="mt-0.5 shrink-0 text-faint" aria-hidden />
                                    {watch}
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>
                        </div>

                        <div className="flex min-w-0 flex-col items-start gap-2 sm:items-end">
                          <p className="text-xs text-faint">
                            Última actividad: {timeAgo(assistant.last_activity)}
                          </p>
                          <p className="text-xs text-faint">
                            Acciones hoy: {assistant.actions_today}
                          </p>
                          <p className="text-xs text-faint">
                            {assistant.active} de {assistant.automations} automatizaciones activas
                          </p>
                          {assistant.automation_names.length > 0 && (
                            <ul className="flex flex-wrap gap-1.5 sm:justify-end">
                              {assistant.automation_names.map((name) => (
                                <li key={name} className="chip">
                                  {name}
                                </li>
                              ))}
                            </ul>
                          )}
                          <ButtonLink
                            to={`/assistants/${assistant.id}`}
                            size="sm"
                            variant="secondary"
                            data-testid={`assistant-open-${assistant.id}`}
                            className="mt-1"
                          >
                            {COPY.openOperation}
                          </ButtonLink>
                        </div>
                      </div>
                    </div>
                  </article>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}
