/**
 * Asistentes — el mismo agente visto en operación: qué vigila y si algo falló.
 */
import { ArrowRight, Eye, Robot } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Breadcrumb } from "../components/Breadcrumb";
import { ErrorInline, PageHeader, SkeletonBlock } from "../components/ui";
import { COPY, HEALTH_BADGE, type AssistantCard } from "./assistants/assistantCopy";

function timeAgo(value: string | null): string {
  if (!value) return "sin actividad todavía";
  const diff = Date.now() - new Date(value).getTime();
  const minutes = Math.max(1, Math.round(diff / 60_000));
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `hace ${hours} h`;
  return `hace ${Math.round(hours / 24)} días`;
}

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

  return (
    <div className="space-y-5">
      <Breadcrumb items={[{ label: "Operar", to: "/assistants" }, { label: "Asistentes" }]} />
      <PageHeader
        title="Asistentes"
        subtitle={COPY.listSubtitle}
        actions={
          <div className="flex flex-col items-end gap-1">
            <Link to="/agents/new" className="btn btn-secondary min-h-11 text-xs">
              <Robot size={14} aria-hidden className="mr-1" /> {COPY.createAgent}
            </Link>
            <p className="text-[10px] text-faint">{COPY.createHint}</p>
          </div>
        }
      />
      <ErrorInline message={error} />

      {loading ? (
        <div className="panel p-5"><SkeletonBlock rows={4} /></div>
      ) : assistants.length === 0 ? (
        <div className="panel p-5 text-sm text-muted" data-testid="assistants-empty">
          {COPY.empty}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {assistants.map((assistant) => {
            const health = HEALTH_BADGE[assistant.health] ?? HEALTH_BADGE.idle;
            return (
              <article key={assistant.id} className="panel flex flex-col gap-2 p-5" data-testid={`assistant-${assistant.id}`}>
                <div className="flex items-center gap-2">
                  <span className="flex h-8 w-8 items-center justify-center rounded-md bg-accent/15 text-accent" aria-hidden>
                    <Robot size={16} />
                  </span>
                  <h2 className="min-w-0 flex-1 truncate text-sm font-semibold text-text">{assistant.name}</h2>
                  <span className={health.className}>{health.text}</span>
                </div>
                <p className="text-[11px] text-muted">
                  Está vigilando: {assistant.watches.length > 0 ? assistant.watches.join(" · ") : "nada todavía"}
                </p>
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-faint">
                  <span>{assistant.active} automatizaciones activas</span>
                  <span>Última actividad: {timeAgo(assistant.last_activity)}</span>
                  <span>Acciones hoy: {assistant.actions_today}</span>
                </div>
                {assistant.automation_names.length > 0 && (
                  <p className="flex items-center gap-1 text-[10px] text-faint">
                    <Eye size={11} aria-hidden /> {assistant.automation_names.join(" · ")}
                  </p>
                )}
                <Link
                  to={`/assistants/${assistant.id}`}
                  className="btn btn-secondary mt-auto min-h-9 justify-center gap-1.5 text-xs"
                  data-testid={`assistant-open-${assistant.id}`}
                >
                  {COPY.openOperation} <ArrowRight size={13} aria-hidden />
                </Link>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
