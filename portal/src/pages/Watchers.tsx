import { ArrowClockwise, Eye, Plus, Trash } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Breadcrumb } from "../components/Breadcrumb";
import { ErrorInline, PageHeader, SkeletonBlock, Spinner, SuccessInline } from "../components/ui";

type Watcher = {
  id: string;
  name: string;
  entity: string;
  strategy: string;
  table_name: string;
  primary_key: string | null;
  timestamp_field: string | null;
  selected_fields: string[];
  condition: { field?: string; operator?: string; value?: unknown };
  transition_mode: string;
  interval_seconds: number;
  cooldown_seconds: number;
  debounce_seconds: number;
  event_type: string;
  workflow_id: string | null;
  status: string;
  last_check_at: string | null;
};

type WatcherState = {
  last_value: Record<string, unknown>;
  last_condition_result: boolean | null;
  last_triggered_at: string | null;
  cooldown_until: string | null;
  failure_count: number;
  last_error: string | null;
  check_count: number;
  trigger_count: number;
  last_check_at: string | null;
};

type CheckOutcome = {
  status: string;
  reason: string;
  triggered: boolean;
  transition: string | null;
  after: Record<string, unknown>;
};

type WorkflowOption = { id: string; name: string; status: string };
type EventOption = { id: string; business_name: string; category: string };

const OPERATORS = [
  { value: "<", label: "es menor que" },
  { value: "<=", label: "es como máximo" },
  { value: ">", label: "es mayor que" },
  { value: ">=", label: "es al menos" },
  { value: "==", label: "es" },
  { value: "!=", label: "no es" },
  { value: "contains", label: "contiene" },
  { value: "is_empty", label: "está vacío" },
];

const MODES = [
  { value: "on_enter", label: "Cuando entre en la condición" },
  { value: "on_exit", label: "Cuando salga de la condición" },
  { value: "on_change", label: "Cuando cambie el valor" },
  { value: "while_true", label: "Mientras se cumpla" },
];

const STATUS_BADGE: Record<string, string> = {
  listening: "badge-ok",
  checking: "badge-info",
  paused: "badge-muted",
  error: "badge-danger",
};

function conditionText(watcher: Watcher): string {
  const condition = watcher.condition || {};
  const field = String(condition.field || "?");
  const operator = OPERATORS.find((o) => o.value === condition.operator)?.label ?? String(condition.operator ?? "");
  return `${field} ${operator} ${condition.value ?? ""}`.trim();
}

export default function WatchersPage() {
  const { session } = useAuth();
  const [watchers, setWatchers] = useState<Watcher[]>([]);
  const [states, setStates] = useState<Record<string, WatcherState>>({});
  const [workflows, setWorkflows] = useState<WorkflowOption[]>([]);
  const [events, setEvents] = useState<EventOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [outcome, setOutcome] = useState<Record<string, CheckOutcome>>({});
  const [form, setForm] = useState({
    name: "",
    entity: "producto",
    table_name: "",
    primary_key: "id",
    timestamp_field: "",
    field: "stock",
    operator: "<",
    value: "10",
    transition_mode: "on_enter",
    interval_seconds: 300,
    cooldown_seconds: 0,
    debounce_seconds: 0,
    event_type: "",
    workflow_id: "",
  });

  const load = useCallback(async () => {
    if (!session) return;
    setError("");
    try {
      const [watcherData, workflowData, catalog] = await Promise.all([
        api<{ watchers: Watcher[] }>("/api/v1/workflows/watchers", {
          token: session.token,
          organizationId: session.organizationId,
        }),
        api<{ workflows: WorkflowOption[] }>("/api/v1/workflows", {
          token: session.token,
          organizationId: session.organizationId,
        }),
        api<{ categories: { key: string; label: string; events: { id: string; business_name: string }[] }[] }>(
          "/api/v1/workflows/event-catalog",
          { token: session.token, organizationId: session.organizationId },
        ),
      ]);
      setWatchers(watcherData.watchers || []);
      setWorkflows(workflowData.workflows || []);
      setEvents(
        (catalog.categories || []).flatMap((category) =>
          (category.events || []).map((event) => ({ ...event, category: category.label })),
        ),
      );
      const stateEntries = await Promise.all(
        (watcherData.watchers || []).slice(0, 30).map((watcher) =>
          api<WatcherState>(`/api/v1/workflows/watchers/${watcher.id}/state`, {
            token: session.token,
            organizationId: session.organizationId,
          })
            .then((state) => [watcher.id, state] as const)
            .catch(() => null),
        ),
      );
      setStates(Object.fromEntries(stateEntries.filter((entry): entry is readonly [string, WatcherState] => entry !== null)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => {
    void load();
  }, [load]);

  const activeWorkflows = useMemo(
    () => workflows.filter((w) => w.status !== "archived"),
    [workflows],
  );

  async function create() {
    if (!session || !form.name.trim() || !form.table_name.trim()) return;
    setBusy("create");
    setError("");
    setMsg("");
    try {
      await api("/api/v1/workflows/watchers", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          name: form.name.trim(),
          entity: form.entity.trim() || "registro",
          strategy: "watermark_polling",
          table_name: form.table_name.trim(),
          primary_key: form.primary_key.trim() || null,
          timestamp_field: form.timestamp_field.trim() || null,
          selected_fields: [form.field.trim()],
          condition: {
            field: form.field.trim(),
            operator: form.operator,
            value: Number.isFinite(Number(form.value)) && form.value !== "" ? Number(form.value) : form.value,
          },
          transition_mode: form.transition_mode,
          interval_seconds: Number(form.interval_seconds) || 300,
          cooldown_seconds: Number(form.cooldown_seconds) || 0,
          debounce_seconds: Number(form.debounce_seconds) || 0,
          event_type: form.event_type.trim(),
          workflow_id: form.workflow_id || null,
        }),
      });
      setMsg(`Vigilancia "${form.name.trim()}" creada.`);
      setShowForm(false);
      setForm((prev) => ({ ...prev, name: "", table_name: "" }));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function check(watcher: Watcher) {
    if (!session) return;
    setBusy(`check-${watcher.id}`);
    setError("");
    try {
      const result = await api<CheckOutcome>(`/api/v1/workflows/watchers/${watcher.id}/check`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      setOutcome((prev) => ({ ...prev, [watcher.id]: result }));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function toggleStatus(watcher: Watcher) {
    if (!session) return;
    setBusy(`status-${watcher.id}`);
    try {
      await api(`/api/v1/workflows/watchers/${watcher.id}`, {
        method: "PATCH",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ status: watcher.status === "paused" ? "listening" : "paused" }),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function remove(watcher: Watcher) {
    if (!session) return;
    if (!window.confirm(`¿Eliminar la vigilancia "${watcher.name}"?`)) return;
    setBusy(`del-${watcher.id}`);
    try {
      await api(`/api/v1/workflows/watchers/${watcher.id}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="space-y-5">
      <Breadcrumb items={[{ label: "Workflows", to: "/workflows" }, { label: "Vigilancia de datos" }]} />
      <PageHeader
        title="Vigilancia de datos"
        subtitle="Zent revisa tus tablas de forma incremental y despierta la automatización solo cuando algo cambia."
        actions={
          <button
            type="button"
            className="btn btn-primary min-h-11"
            data-testid="watcher-new"
            onClick={() => setShowForm((v) => !v)}
          >
            <Plus size={15} aria-hidden />
            Nueva vigilancia
          </button>
        }
      />
      <ErrorInline message={error} />
      <SuccessInline message={msg} />

      {showForm && (
        <section className="panel space-y-3 p-4" data-testid="watcher-form">
          <h2 className="text-sm font-semibold text-text">¿Qué quieres vigilar?</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-xs text-muted">
              Nombre
              <input
                className="mt-1 w-full rounded-md border border-border bg-soft px-2 py-1.5 text-xs"
                placeholder="Stock bajo"
                value={form.name}
                data-testid="watcher-name"
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </label>
            <label className="text-xs text-muted">
              ¿Qué representa? (etiqueta)
              <input
                className="mt-1 w-full rounded-md border border-border bg-soft px-2 py-1.5 text-xs"
                placeholder="producto"
                value={form.entity}
                onChange={(e) => setForm({ ...form, entity: e.target.value })}
              />
            </label>
            <label className="text-xs text-muted">
              Tabla
              <input
                className="mt-1 w-full rounded-md border border-border bg-soft px-2 py-1.5 text-xs"
                placeholder="inventory"
                value={form.table_name}
                data-testid="watcher-table"
                onChange={(e) => setForm({ ...form, table_name: e.target.value })}
              />
            </label>
            <label className="text-xs text-muted">
              Clave incremental (id)
              <input
                className="mt-1 w-full rounded-md border border-border bg-soft px-2 py-1.5 text-xs"
                value={form.primary_key}
                onChange={(e) => setForm({ ...form, primary_key: e.target.value })}
              />
            </label>
            <label className="text-xs text-muted">
              Campo a evaluar
              <input
                className="mt-1 w-full rounded-md border border-border bg-soft px-2 py-1.5 text-xs"
                value={form.field}
                data-testid="watcher-field"
                onChange={(e) => setForm({ ...form, field: e.target.value })}
              />
            </label>
            <div className="flex items-end gap-2">
              <label className="flex-1 text-xs text-muted">
                Condición
                <select
                  className="mt-1 w-full rounded-md border border-border bg-soft px-2 py-1.5 text-xs"
                  value={form.operator}
                  onChange={(e) => setForm({ ...form, operator: e.target.value })}
                >
                  {OPERATORS.map((op) => (
                    <option key={op.value} value={op.value}>{op.label}</option>
                  ))}
                </select>
              </label>
              <input
                className="w-20 rounded-md border border-border bg-soft px-2 py-1.5 text-xs"
                value={form.value}
                aria-label="Valor"
                data-testid="watcher-value"
                onChange={(e) => setForm({ ...form, value: e.target.value })}
              />
            </div>
            <label className="text-xs text-muted">
              Modo
              <select
                className="mt-1 w-full rounded-md border border-border bg-soft px-2 py-1.5 text-xs"
                value={form.transition_mode}
                onChange={(e) => setForm({ ...form, transition_mode: e.target.value })}
              >
                {MODES.map((mode) => (
                  <option key={mode.value} value={mode.value}>{mode.label}</option>
                ))}
              </select>
            </label>
            <label className="text-xs text-muted">
              Enfriamiento (segundos)
              <input
                className="mt-1 w-full rounded-md border border-border bg-soft px-2 py-1.5 text-xs"
                type="number"
                min={0}
                value={form.cooldown_seconds}
                onChange={(e) => setForm({ ...form, cooldown_seconds: Number(e.target.value) })}
              />
            </label>
            <label className="text-xs text-muted">
              Espera antes de avisar (debounce, segundos)
              <input
                className="mt-1 w-full rounded-md border border-border bg-soft px-2 py-1.5 text-xs"
                type="number"
                min={0}
                value={form.debounce_seconds}
                onChange={(e) => setForm({ ...form, debounce_seconds: Number(e.target.value) })}
              />
            </label>
            <label className="text-xs text-muted">
              Cada (segundos)
              <input
                className="mt-1 w-full rounded-md border border-border bg-soft px-2 py-1.5 text-xs"
                type="number"
                min={60}
                value={form.interval_seconds}
                onChange={(e) => setForm({ ...form, interval_seconds: Number(e.target.value) })}
              />
            </label>
            <label className="text-xs text-muted">
              Evento que despierta
              <input
                className="mt-1 w-full rounded-md border border-border bg-soft px-2 py-1.5 text-xs"
                list="watcher-events"
                placeholder="inventory.stock.low"
                value={form.event_type}
                onChange={(e) => setForm({ ...form, event_type: e.target.value })}
              />
              <datalist id="watcher-events">
                {events.map((event) => (
                  <option key={event.id} value={event.id}>{event.business_name}</option>
                ))}
              </datalist>
            </label>
            <label className="text-xs text-muted">
              Automatización (opcional)
              <select
                className="mt-1 w-full rounded-md border border-border bg-soft px-2 py-1.5 text-xs"
                value={form.workflow_id}
                onChange={(e) => setForm({ ...form, workflow_id: e.target.value })}
              >
                <option value="">—</option>
                {activeWorkflows.map((workflow) => (
                  <option key={workflow.id} value={workflow.id}>{workflow.name}</option>
                ))}
              </select>
            </label>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn btn-primary min-h-9 px-3 text-xs"
              disabled={busy === "create" || !form.name.trim() || !form.table_name.trim()}
              data-testid="watcher-create"
              onClick={() => void create()}
            >
              {busy === "create" ? <Spinner size={13} /> : <Eye size={14} aria-hidden />}
              Empezar a vigilar
            </button>
            {form.table_name.trim() === "" && (
              <span className="text-[10px] text-faint">
                Sin tabla conectada puedes probar con la tabla interna que uses en tus datos gestionados.
              </span>
            )}
          </div>
        </section>
      )}

      {loading ? (
        <div className="panel p-5"><SkeletonBlock rows={4} /></div>
      ) : watchers.length === 0 ? (
        <div className="panel p-5 text-sm text-muted" data-testid="watchers-empty">
          Todavía no vigilas nada. Crea una vigilancia y Zent revisará los cambios sin ejecutar agentes.
        </div>
      ) : (
        <div className="space-y-3">
          {watchers.map((watcher) => {
            const state = states[watcher.id];
            const result = outcome[watcher.id];
            return (
              <article key={watcher.id} className="panel space-y-2 p-4" data-testid="watcher-card">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-sm font-semibold text-text">{watcher.name}</h2>
                  <span className={`badge ${STATUS_BADGE[watcher.status] ?? "badge-muted"}`}>{watcher.status}</span>
                  <span className="text-[11px] text-faint">
                    {watcher.entity} · {watcher.table_name}
                  </span>
                  {watcher.workflow_id && (
                    <Link to={`/workflows/${watcher.workflow_id}`} className="text-[11px] text-accent hover:underline">
                      Ver automatización
                    </Link>
                  )}
                </div>
                <p className="text-xs text-muted">
                  Cuando <span className="text-text">{conditionText(watcher)}</span> ({watcher.transition_mode})
                  · revisa cada {watcher.interval_seconds}s
                  {watcher.cooldown_seconds > 0 ? ` · enfriamiento ${watcher.cooldown_seconds}s` : ""}
                  {watcher.debounce_seconds > 0 ? ` · espera ${watcher.debounce_seconds}s` : ""}
                  {watcher.event_type ? ` · despierta "${watcher.event_type}"` : ""}
                </p>
                <div className="grid gap-1 text-[11px] text-faint sm:grid-cols-4">
                  <span>Último check: {state?.last_check_at ? new Date(state.last_check_at).toLocaleString() : "—"}</span>
                  <span>Valor: {state?.last_value?.stock !== undefined ? String(state.last_value.stock) : "—"}</span>
                  <span>Condición: {state?.last_condition_result === null || state?.last_condition_result === undefined ? "—" : state.last_condition_result ? "cumple" : "no cumple"}</span>
                  <span>Activaciones: {state?.trigger_count ?? 0}</span>
                </div>
                {result && (
                  <p
                    className={`rounded-md px-2 py-1.5 text-[11px] ${result.triggered ? "bg-ok/10 text-ok" : "bg-soft text-muted"}`}
                    data-testid="watcher-outcome"
                  >
                    {result.reason}
                    {result.triggered && result.transition ? ` (${result.transition})` : ""}
                  </p>
                )}
                {state?.last_error && <p className="text-[11px] text-danger">{state.last_error}</p>}
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="btn btn-secondary min-h-8 px-2 text-[11px]"
                    disabled={busy === `check-${watcher.id}`}
                    data-testid={`watcher-check-${watcher.id}`}
                    onClick={() => void check(watcher)}
                  >
                    {busy === `check-${watcher.id}` ? <Spinner size={12} /> : <ArrowClockwise size={12} aria-hidden />}
                    Revisar ahora
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost min-h-8 px-2 text-[11px]"
                    disabled={busy === `status-${watcher.id}`}
                    onClick={() => void toggleStatus(watcher)}
                  >
                    {watcher.status === "paused" ? "Reanudar" : "Pausar"}
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost min-h-8 px-2 text-[11px] text-danger"
                    disabled={busy === `del-${watcher.id}`}
                    aria-label={`Eliminar ${watcher.name}`}
                    onClick={() => void remove(watcher)}
                  >
                    <Trash size={12} aria-hidden />
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
