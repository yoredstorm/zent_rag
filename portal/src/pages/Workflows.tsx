import {
  Code,
  DotsThreeVertical,
  FlowArrow,
  MagicWand,
  PencilSimple,
  Play,
  Plus,
  SquaresFour,
  Trash,
  WarningCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState, type MouseEvent as ReactMouseEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Badge,
  Button,
  ButtonLink,
  ConfirmDialog,
  EmptyState,
  ErrorInline,
  IconButton,
  Menu,
  MenuItem,
  MenuSeparator,
  PageHeader,
  Panel,
  PanelHeader,
  Skeleton,
  StatusBadge,
  SuccessInline,
  cn,
  menuItemClass,
  menuSeparatorClass,
} from "../components/ui";
import { fmtDateTime, timeAgo } from "../lib/format";
import {
  type WorkflowSummary,
  type WorkflowTemplate,
} from "../components/workflowStudio/types";

type RailState = "queued" | "running" | "ready" | "warning" | "failed";

/** Ciclo de vida real del workflow → rail de actividad (sin inventar salud). */
const RAIL_STATE: Record<string, RailState> = {
  active: "ready",
  paused: "warning",
  draft: "queued",
  archived: "queued",
};

const TRIGGER_LABEL: Record<string, string> = {
  webhook: "Cuando llega una llamada al hook",
  schedule: "Según calendario",
  event: "Cuando ocurre un evento",
};

export default function WorkflowsPage() {
  const { session } = useAuth();
  const navigate = useNavigate();
  const [wfs, setWfs] = useState<WorkflowSummary[]>([]);
  const [tpls, setTpls] = useState<WorkflowTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [toDelete, setToDelete] = useState<WorkflowSummary | null>(null);

  const load = useCallback(async () => {
    if (!session) return;
    setError("");
    try {
      const [w, t] = await Promise.all([
        api<{ workflows: WorkflowSummary[] }>("/api/v1/workflows", {
          token: session.token,
          organizationId: session.organizationId,
        }),
        api<{ templates: WorkflowTemplate[] }>("/api/v1/workflows/templates", {
          token: session.token,
          organizationId: session.organizationId,
        }),
      ]);
      setWfs(w.workflows || []);
      setTpls(t.templates || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => {
    void load();
  }, [load]);

  const summary = useMemo(() => {
    const active = wfs.filter((w) => w.status === "active").length;
    const runs = wfs.reduce((total, w) => total + (w.runs || 0), 0);
    const ok = wfs.reduce((total, w) => total + (w.ok_runs || 0), 0);
    return { active, runs, ok, withoutSuccess: runs - ok };
  }, [wfs]);

  async function install(slug: string) {
    if (!session) return;
    setBusy(`i-${slug}`);
    setError("");
    setMsg("");
    try {
      const out = await api<{ workflow_id: string; hook_secret?: string }>(
        `/api/v1/workflows/templates/${slug}/install`,
        { method: "POST", token: session.token, organizationId: session.organizationId },
      );
      navigate(`/workflows/${out.workflow_id}`, { state: { hookSecret: out.hook_secret } });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
      setBusy("");
    }
  }

  async function toggle(wf: WorkflowSummary) {
    if (!session) return;
    const action = wf.status === "active" ? "pause" : "activate";
    setBusy(`${action}-${wf.id}`);
    setError("");
    setMsg("");
    try {
      await api(`/api/v1/workflows/${wf.id}/${action}`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg(action === "activate" ? `"${wf.name}" está activo.` : `"${wf.name}" pausado.`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function remove(wf: WorkflowSummary) {
    if (!session) return;
    setBusy(`del-${wf.id}`);
    setError("");
    setMsg("");
    try {
      await api(`/api/v1/workflows/${wf.id}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg(`Workflow "${wf.name}" eliminado.`);
      setToDelete(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  /** `last_run_at` no viene en el listado actual: si el payload lo trae, se muestra. */
  function lastRunLabel(wf: WorkflowSummary): string {
    const lastRunAt = (wf as WorkflowSummary & { last_run_at?: string | null }).last_run_at;
    if (lastRunAt) return fmtDateTime(lastRunAt);
    return wf.runs > 0 ? "—" : "todavía no corrió";
  }

  function openWorkflow(wf: WorkflowSummary, event: ReactMouseEvent) {
    if ((event.target as HTMLElement).closest("a, button")) return;
    navigate(`/workflows/${wf.id}`);
  }

  return (
    <div>
      <PageHeader
        title="Workflow Automation"
        subtitle="Cada automatización dice qué hace, cuándo corre y si está activa. Sin diagramas de por medio."
        actions={
          <>
            <ButtonLink to="/workflows/new" variant="secondary" leadingIcon={Plus} data-testid="wf-new-modes">
              Nuevo workflow
            </ButtonLink>
            <ButtonLink to="/workflows/new/ask" variant="primary" leadingIcon={MagicWand} data-testid="wf-new-ai">
              Crear con IA
            </ButtonLink>
          </>
        }
      />
      <ErrorInline message={error} />
      <SuccessInline message={msg} />

      {loading ? (
        <Panel className="overflow-hidden">
          <div className="flex items-center gap-3 border-b border-border px-4 py-3" aria-hidden>
            <Skeleton className="h-4 w-52" />
            <Skeleton className="ml-auto h-4 w-24" />
          </div>
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="flex items-center gap-4 border-b border-border-soft px-4 py-4 last:border-b-0" aria-hidden>
              <div className="flex min-w-0 flex-1 flex-col gap-2">
                <Skeleton className="h-4 w-64" />
                <Skeleton className="h-3 w-80" />
              </div>
              <Skeleton className="h-8 w-24 rounded-md" />
            </div>
          ))}
        </Panel>
      ) : wfs.length === 0 ? (
        <Panel>
          <EmptyState
            icon={FlowArrow}
            title="Sin workflows todavía"
            body="Cuéntale a Zent qué quieres automatizar, instala una plantilla o diseña el lienzo tú mismo."
            hint="El listado se llena con cada automatización que crees; aquí verás su estado y sus corridas."
            action={
              <ButtonLink to="/workflows/new/ask" variant="primary" leadingIcon={MagicWand}>
                Crear con IA
              </ButtonLink>
            }
            secondaryAction={
              <ButtonLink to="/workflows/new/manual" variant="secondary" leadingIcon={PencilSimple}>
                Diseñar manualmente
              </ButtonLink>
            }
          />
        </Panel>
      ) : (
        <Panel>
          <PanelHeader
            title={`Automatizaciones (${wfs.length})`}
            description={
              <>
                <span className="tabular-nums">{summary.active} activas</span> ·{" "}
                <span className="tabular-nums">{summary.runs} corridas</span>
                {summary.withoutSuccess > 0 ? (
                  <>
                    {" "}
                    · <span className="tabular-nums text-warn">{summary.withoutSuccess} sin éxito</span>
                  </>
                ) : (
                  <> · todas con éxito</>
                )}
              </>
            }
          />
          <ul className="divide-y divide-border-soft">
            {wfs.map((w) => {
              const rail = RAIL_STATE[w.status] ?? "queued";
              const toggleAction = w.status === "active" ? "pause" : "activate";
              const noSuccess = w.runs > 0 && w.ok_runs === 0;
              return (
                <li
                  key={w.id}
                  data-testid="wf-card"
                  data-state={rail}
                  onClick={(event) => openWorkflow(w, event)}
                  className="state-rail cursor-pointer px-4 py-3.5 transition-colors duration-150 hover:bg-soft/40"
                >
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
                        <Link
                          to={`/workflows/${w.id}`}
                          className="text-h3 rounded-xs hover:text-accent"
                        >
                          {w.name}
                        </Link>
                        <StatusBadge status={w.status} />
                        {noSuccess && (
                          <Badge tone="warn" icon={WarningCircle}>
                            Sin corridas exitosas
                          </Badge>
                        )}
                      </div>
                      <p className="prose-measure mt-1 text-[13px] leading-relaxed text-muted">
                        {w.description || "Sin descripción todavía."}
                      </p>
                      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-faint">
                        <span className="inline-flex items-center gap-1.5">
                          <FlowArrow size={12} aria-hidden />
                          {TRIGGER_LABEL[w.trigger_type] ?? w.trigger_type}
                        </span>
                        <span>Última corrida: {lastRunLabel(w)}</span>
                        <span className="tabular-nums">
                          {w.runs} corridas · {w.ok_runs} con éxito
                        </span>
                        <span>Editado {timeAgo(w.updated_at ?? w.created_at)}</span>
                      </div>
                    </div>
                    <div className="flex shrink-0 flex-wrap items-center gap-2">
                      <ButtonLink
                        to={`/workflows/${w.id}`}
                        variant="secondary"
                        size="sm"
                        leadingIcon={PencilSimple}
                      >
                        Abrir
                      </ButtonLink>
                      <Button
                        size="sm"
                        variant={w.status === "active" ? "ghost" : "secondary"}
                        loading={busy === `${toggleAction}-${w.id}`}
                        disabled={!!busy && busy !== `${toggleAction}-${w.id}`}
                        data-testid={`wf-toggle-${w.id}`}
                        onClick={() => void toggle(w)}
                      >
                        {w.status === "active" ? "Pausar" : "Activar"}
                      </Button>
                      <Menu
                        label={`Más acciones para ${w.name}`}
                        trigger={
                          <IconButton label={`Más acciones para ${w.name}`} icon={DotsThreeVertical} />
                        }
                      >
                        <MenuItem className={menuItemClass} asChild>
                          <Link to={`/workflows/${w.id}?panel=test`}>
                            <Play size={15} aria-hidden />
                            Probar con datos
                          </Link>
                        </MenuItem>
                        <MenuItem className={menuItemClass} asChild>
                          <Link to={`/workflows/${w.id}?panel=api`}>
                            <Code size={15} aria-hidden />
                            API y hook
                          </Link>
                        </MenuItem>
                        <MenuSeparator className={menuSeparatorClass} />
                        <MenuItem
                          className={cn(
                            menuItemClass,
                            "text-danger data-[highlighted]:bg-danger-soft data-[highlighted]:text-danger",
                          )}
                          onSelect={() => setToDelete(w)}
                        >
                          <Trash size={15} aria-hidden />
                          Eliminar
                        </MenuItem>
                      </Menu>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        </Panel>
      )}

      {!loading && (
        <Panel className="mt-4">
          <PanelHeader
            title="Plantillas"
            description="Instalar abre el estudio con el flujo ya armado."
            actions={<SquaresFour size={16} className="text-faint" aria-hidden />}
          />
          {tpls.length === 0 ? (
            <p className="px-4 py-3 text-xs text-faint">Sin plantillas disponibles.</p>
          ) : (
            <ul className="divide-y divide-border-soft">
              {tpls.map((t) => (
                <li key={t.slug} className="flex items-center gap-3 px-4 py-2.5">
                  <SquaresFour size={14} className="shrink-0 text-faint" aria-hidden />
                  <span className="min-w-0 flex-1 truncate text-[13px] text-text">{t.name}</span>
                  <span className="shrink-0 text-[11px] text-faint tabular-nums">
                    {t.steps.length} pasos
                  </span>
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={busy === `i-${t.slug}`}
                    disabled={!!busy && busy !== `i-${t.slug}`}
                    data-testid={`wf-install-${t.slug}`}
                    onClick={() => void install(t.slug)}
                  >
                    Instalar
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      )}

      <p className="mt-4 text-[11px] text-faint">
        La URL del hook inbound, el secret, los snippets y el contrato Android viven en el drawer
        API de cada workflow.
      </p>

      <ConfirmDialog
        open={toDelete !== null}
        onOpenChange={(open) => {
          if (!open) setToDelete(null);
        }}
        title="Eliminar workflow"
        body={
          toDelete
            ? `¿Eliminar "${toDelete.name}"? Sus corridas dejarán de ser accesibles.`
            : undefined
        }
        confirmLabel="Eliminar"
        loading={toDelete !== null && busy === `del-${toDelete.id}`}
        onConfirm={() => {
          if (toDelete) void remove(toDelete);
        }}
      />
    </div>
  );
}
