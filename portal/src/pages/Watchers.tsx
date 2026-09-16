import {
  ArrowClockwise,
  Clock,
  Eye,
  Hourglass,
  Plus,
  Trash,
  WarningCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorInline,
  Field,
  IconButton,
  Input,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  Progress,
  Select,
  Skeleton,
  StatusBadge,
  StatusDot,
  StatusRow,
  SuccessInline,
} from "../components/ui";
import { fmtDateTime } from "../lib/format";

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
  pending_since: string | null;
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

type RailState = "queued" | "running" | "ready" | "warning" | "failed";

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

function conditionText(watcher: Watcher): string {
  const condition = watcher.condition || {};
  const field = String(condition.field || "?");
  const operator = OPERATORS.find((o) => o.value === condition.operator)?.label ?? String(condition.operator ?? "");
  return `${field} ${operator} ${condition.value ?? ""}`.trim();
}

function modeLabel(mode: string): string {
  return MODES.find((m) => m.value === mode)?.label ?? mode;
}

/** Segundos → "45 s" / "5 min" / "2 h". */
function durationLabel(seconds: number): string {
  if (seconds < 60) return `${seconds} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  return `${Math.round(seconds / 3600)} h`;
}

/**
 * El backend reporta listening | checking | paused | error. La salud se traduce
 * al vocabulario del sistema (StatusBadge + rail) sin tocar el estado guardado.
 */
function watcherHealth(watcher: Watcher, state?: WatcherState): { status: string; label: string; rail: RailState } {
  if (watcher.status === "checking") {
    return { status: "running", label: "Revisando ahora", rail: "running" };
  }
  if (watcher.status === "paused") {
    return { status: "paused", label: "Pausado", rail: "warning" };
  }
  if (watcher.status === "error" || state?.last_error || (state?.failure_count ?? 0) > 0) {
    return { status: "failed", label: "Con error", rail: "failed" };
  }
  return { status: "healthy", label: "Escuchando", rail: "ready" };
}

/** Próximo check estimado: el scheduler lo corre cuando vence el intervalo. */
function nextCheckAt(watcher: Watcher, state?: WatcherState): Date | null {
  if (watcher.status === "paused") return null;
  const last = state?.last_check_at ?? watcher.last_check_at;
  if (!last) return null;
  const base = new Date(last).getTime();
  if (Number.isNaN(base)) return null;
  return new Date(base + Math.max(watcher.interval_seconds, 60) * 1000);
}

function valueLabel(watcher: Watcher, state?: WatcherState): string {
  const field = watcher.condition?.field;
  if (!field) return "—";
  const value = state?.last_value?.[field];
  return value === undefined || value === null ? "—" : String(value);
}

function conditionResult(state?: WatcherState): string {
  if (state?.last_condition_result === null || state?.last_condition_result === undefined) return "—";
  return state.last_condition_result ? "cumple" : "no cumple";
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
  const [toDelete, setToDelete] = useState<Watcher | null>(null);
  /** Momento de la última lectura de estados: mantiene el render puro. */
  const [snapshotAt, setSnapshotAt] = useState(0);
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
      setSnapshotAt(Date.now());
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

  /** Pulso: todo lo que se ve de un vistazo, derivado de estados reales. */
  const pulse = useMemo(() => {
    let listening = 0;
    let paused = 0;
    let attention = 0;
    let triggers = 0;
    let checks = 0;
    for (const watcher of watchers) {
      const state = states[watcher.id];
      const health = watcherHealth(watcher, state);
      if (health.rail === "failed") attention += 1;
      else if (watcher.status === "paused") paused += 1;
      else listening += 1;
      triggers += state?.trigger_count ?? 0;
      checks += state?.check_count ?? 0;
    }
    return { listening, paused, attention, triggers, checks };
  }, [watchers, states]);

  const nextChecks = useMemo(
    () =>
      watchers
        .map((watcher) => ({ watcher, at: nextCheckAt(watcher, states[watcher.id]) }))
        .filter((entry): entry is { watcher: Watcher; at: Date } => entry.at !== null)
        .sort((a, b) => a.at.getTime() - b.at.getTime())
        .slice(0, 3),
    [watchers, states],
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
    const resuming = watcher.status === "paused";
    setBusy(`status-${watcher.id}`);
    setError("");
    setMsg("");
    try {
      await api(`/api/v1/workflows/watchers/${watcher.id}`, {
        method: "PATCH",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ status: resuming ? "listening" : "paused" }),
      });
      setMsg(resuming ? `"${watcher.name}" volvió a escuchar.` : `"${watcher.name}" quedó en pausa.`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function remove(watcher: Watcher) {
    if (!session) return;
    setBusy(`del-${watcher.id}`);
    setError("");
    setMsg("");
    try {
      await api(`/api/v1/workflows/watchers/${watcher.id}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg(`Vigilancia "${watcher.name}" eliminada.`);
      setToDelete(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  const pulseLabel =
    pulse.attention > 0
      ? `${pulse.attention} con error`
      : pulse.listening > 0
        ? `${pulse.listening} escuchando`
        : "En pausa";
  const pulseTone = pulse.attention > 0 ? "danger" : pulse.listening > 0 ? "ok" : "neutral";

  return (
    <div>
      <PageHeader
        breadcrumbs={[{ label: "Workflows", to: "/workflows" }, { label: "Vigilancia de datos" }]}
        title="Vigilancia de datos"
        subtitle="Zent revisa tus tablas de forma incremental y despierta la automatización solo cuando algo cambia."
        actions={
          <Button
            variant="primary"
            leadingIcon={Plus}
            data-testid="watcher-new"
            onClick={() => setShowForm((v) => !v)}
          >
            Nueva vigilancia
          </Button>
        }
      />
      <ErrorInline message={error} />
      <SuccessInline message={msg} />

      {showForm && (
        <Panel className="mb-4" data-testid="watcher-form">
          <PanelHeader
            title="¿Qué quieres vigilar?"
            description="Una tabla, un campo y la condición que despierta la automatización. El resto son opciones."
          />
          <div className="flex flex-col gap-4 p-4">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <Field label="Nombre" required hint="Cómo vas a reconocer esta vigilancia.">
                <Input
                  placeholder="Stock bajo"
                  value={form.name}
                  data-testid="watcher-name"
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </Field>
              <Field label="¿Qué representa? (etiqueta)" hint="Nombre de negocio del registro que se vigila.">
                <Input
                  placeholder="producto"
                  value={form.entity}
                  onChange={(e) => setForm({ ...form, entity: e.target.value })}
                />
              </Field>
              <Field label="Tabla" required hint="Tabla conectada donde Zent lee los cambios.">
                <Input
                  placeholder="inventory"
                  value={form.table_name}
                  data-testid="watcher-table"
                  onChange={(e) => setForm({ ...form, table_name: e.target.value })}
                />
              </Field>
              <Field label="Clave incremental (id)" hint="Por defecto, la clave primaria de la tabla.">
                <Input
                  value={form.primary_key}
                  onChange={(e) => setForm({ ...form, primary_key: e.target.value })}
                />
              </Field>
              <Field label="Campo a evaluar" required>
                <Input
                  value={form.field}
                  data-testid="watcher-field"
                  onChange={(e) => setForm({ ...form, field: e.target.value })}
                />
              </Field>
              <div className="grid grid-cols-[1fr_6rem] gap-3">
                <Field label="Condición">
                  <Select
                    value={form.operator}
                    onChange={(e) => setForm({ ...form, operator: e.target.value })}
                  >
                    {OPERATORS.map((op) => (
                      <option key={op.value} value={op.value}>{op.label}</option>
                    ))}
                  </Select>
                </Field>
                <Field label="Valor">
                  <Input
                    value={form.value}
                    data-testid="watcher-value"
                    onChange={(e) => setForm({ ...form, value: e.target.value })}
                  />
                </Field>
              </div>
              <Field label="Modo" hint="Cuándo se considera que la condición amerita avisar.">
                <Select
                  value={form.transition_mode}
                  onChange={(e) => setForm({ ...form, transition_mode: e.target.value })}
                >
                  {MODES.map((mode) => (
                    <option key={mode.value} value={mode.value}>{mode.label}</option>
                  ))}
                </Select>
              </Field>
            </div>

            <div className="border-t border-border-soft pt-4">
              <p className="eyebrow mb-3">Ritmo y aviso</p>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Field label="Cada (segundos)" hint={durationLabel(Math.max(form.interval_seconds || 0, 60))}>
                  <Input
                    type="number"
                    min={60}
                    value={form.interval_seconds}
                    onChange={(e) => setForm({ ...form, interval_seconds: Number(e.target.value) })}
                  />
                </Field>
                <Field
                label="Espera antes de avisar"
                hint={
                  form.debounce_seconds > 0
                    ? `La condición debe sostenerse ${durationLabel(form.debounce_seconds)} (segundos).`
                    : "La condición debe sostenerse este tiempo antes de avisar (segundos)."
                }
              >
                <Input
                  type="number"
                  min={0}
                  value={form.debounce_seconds}
                  onChange={(e) => setForm({ ...form, debounce_seconds: Number(e.target.value) })}
                />
              </Field>
                <Field
                  label="Enfriamiento (segundos)"
                  hint={
                    form.cooldown_seconds > 0
                      ? `Tras avisar, no vuelve a avisar por ${durationLabel(form.cooldown_seconds)}.`
                      : "Sin enfriamiento: puede avisar en cada revisión."
                  }
                >
                  <Input
                    type="number"
                    min={0}
                    value={form.cooldown_seconds}
                    onChange={(e) => setForm({ ...form, cooldown_seconds: Number(e.target.value) })}
                  />
                </Field>
                <Field
                  label="Evento que despierta"
                  hint="Opcional: nombre del evento que publica la automatización."
                >
                  <Input
                    list="watcher-events"
                    placeholder="inventory.stock.low"
                    value={form.event_type}
                    onChange={(e) => setForm({ ...form, event_type: e.target.value })}
                  />
                </Field>
              </div>
              <datalist id="watcher-events">
                {events.map((event) => (
                  <option key={event.id} value={event.id}>{event.business_name}</option>
                ))}
              </datalist>
              <div className="mt-3 max-w-md">
                <Field label="Automatización (opcional)" hint="Qué workflow despierta cuando se cumple la condición.">
                  <Select
                    value={form.workflow_id}
                    onChange={(e) => setForm({ ...form, workflow_id: e.target.value })}
                  >
                    <option value="">—</option>
                    {activeWorkflows.map((workflow) => (
                      <option key={workflow.id} value={workflow.id}>{workflow.name}</option>
                    ))}
                  </Select>
                </Field>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="primary"
                leadingIcon={Eye}
                loading={busy === "create"}
                disabled={!form.name.trim() || !form.table_name.trim()}
                data-testid="watcher-create"
                onClick={() => void create()}
              >
                Empezar a vigilar
              </Button>
              {form.table_name.trim() === "" && (
                <span className="text-xs text-faint">
                  Sin tabla conectada puedes probar con la tabla interna que uses en tus datos gestionados.
                </span>
              )}
            </div>
          </div>
        </Panel>
      )}

      {loading ? (
        <div className="flex flex-col gap-4" aria-hidden>
          <Skeleton className="h-[132px] rounded-lg" />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-[92px] rounded-lg" />
            ))}
          </div>
          <Skeleton className="h-[220px] rounded-lg" />
        </div>
      ) : watchers.length === 0 ? (
        <Panel data-testid="watchers-empty">
          <EmptyState
            icon={Eye}
            title="Todavía no vigilas nada"
            body="Crea una vigilancia y Zent revisará los cambios sin ejecutar agentes: solo consulta la tabla y despierta el workflow cuando la condición se cumple."
            hint="Necesitas una tabla conectada y el campo que quieres evaluar."
            action={
              <Button variant="primary" leadingIcon={Plus} onClick={() => setShowForm(true)}>
                Nueva vigilancia
              </Button>
            }
          />
        </Panel>
      ) : (
        <div className="flex flex-col gap-4">
          {/* Foco: pulso real de los procesos vivos */}
          <Panel className="p-4 sm:p-5">
            <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0">
                <p className="eyebrow mb-2">Pulso de la vigilancia</p>
                <div className="flex items-baseline gap-3">
                  <p
                    className={
                      pulseTone === "danger"
                        ? "text-display text-danger"
                        : pulseTone === "ok"
                          ? "text-display text-ok"
                          : "text-display text-muted"
                    }
                  >
                    {pulseLabel}
                  </p>
                  <StatusDot
                    tone={pulseTone === "danger" ? "danger" : pulseTone === "ok" ? "ok" : "neutral"}
                    className="mb-2"
                  />
                </div>
                <p className="mt-1.5 text-[13px] text-muted">
                  {pulse.attention > 0
                    ? `${pulse.listening} siguen escuchando. Revisá los errores antes de confiar en el aviso.`
                    : pulse.listening > 0
                      ? "Zent consulta cada tabla según su intervalo; no se ejecutan agentes hasta que algo cambia."
                      : "Todas las vigilancias están en pausa: no se está consultando ninguna tabla."}
                </p>
                <ul className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">
                  {watchers.slice(0, 8).map((watcher) => {
                    const health = watcherHealth(watcher, states[watcher.id]);
                    return (
                      <li key={watcher.id} className="flex items-center gap-1.5 text-[12px]">
                        <StatusDot
                          tone={
                            health.rail === "failed"
                              ? "danger"
                              : health.rail === "ready"
                                ? "ok"
                                : health.rail === "running"
                                  ? "accent"
                                  : "warn"
                          }
                        />
                        <span className="text-muted">{watcher.name}</span>
                        <span className="sr-only">{health.label}</span>
                      </li>
                    );
                  })}
                </ul>
              </div>

              <div className="min-w-0 lg:w-[320px] lg:shrink-0">
                {busy.startsWith("check-") ? (
                  <StatusRow
                    state="running"
                    title={<span className="text-[13px] text-text">Revisando una tabla</span>}
                    meta="Consultando el watermark incremental. Puede tardar unos segundos."
                  />
                ) : (
                  <>
                    <p className="eyebrow mb-2">Próximos checks</p>
                    {nextChecks.length === 0 ? (
                      <p className="text-[13px] text-muted">
                        Ninguna vigilancia tiene un próximo check programado.
                      </p>
                    ) : (
                      <ul className="flex flex-col gap-2">
                        {nextChecks.map(({ watcher, at }) => (
                          <li key={watcher.id} className="flex items-baseline justify-between gap-3 text-[13px]">
                            <span className="min-w-0 truncate text-muted">{watcher.name}</span>
                            <span className="shrink-0 text-faint tabular-nums">{fmtDateTime(at.toISOString())}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </>
                )}
              </div>
            </div>
          </Panel>

          {/* Resumen demotado: el foco es el pulso de arriba */}
          <MetricGrid cols={4}>
            <Metric
              size="md"
              label="Vigilancias"
              value={watchers.length}
              hint={`${pulse.listening} escuchando · ${pulse.paused} en pausa`}
              icon={Eye}
            />
            <Metric
              size="md"
              label="Activaciones"
              value={pulse.triggers}
              hint="veces que se cumplió la condición"
              icon={ArrowClockwise}
            />
            <Metric
              size="md"
              label="Chequeos"
              value={pulse.checks}
              hint="revisiones acumuladas"
              icon={Clock}
            />
            <Metric
              size="md"
              label="Atención"
              value={pulse.attention}
              tone={pulse.attention > 0 ? "danger" : "default"}
              hint={pulse.attention > 0 ? "vigilancias con error real" : "ninguna con error"}
              icon={WarningCircle}
            />
          </MetricGrid>

          <Panel>
            <PanelHeader
              title={`Vigilancias (${watchers.length})`}
              description="Cada fila dice qué se evalúa, cuándo se revisa y cuándo fue la última activación."
            />
            <ul className="divide-y divide-border-soft">
              {watchers.map((watcher) => {
                const state = states[watcher.id];
                const health = watcherHealth(watcher, state);
                const result = outcome[watcher.id];
                const next = nextCheckAt(watcher, state);
                const cooldownUntil = state?.cooldown_until ? new Date(state.cooldown_until) : null;
                const inCooldown = cooldownUntil !== null && cooldownUntil.getTime() > snapshotAt;
                const debouncePending =
                  state?.pending_since && watcher.debounce_seconds > 0 ? new Date(state.pending_since) : null;
                const debounceElapsed = debouncePending
                  ? Math.max(0, (snapshotAt - debouncePending.getTime()) / 1000)
                  : 0;
                const checking = busy === `check-${watcher.id}`;
                return (
                  <li key={watcher.id}>
                    <article
                      data-testid="watcher-card"
                      data-state={health.rail}
                      className="state-rail px-4 py-3.5"
                    >
                      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
                            <h3 className="text-h3">{watcher.name}</h3>
                            <StatusBadge status={health.status} label={health.label} />
                            {inCooldown && cooldownUntil && (
                              <Badge tone="warn" icon={Hourglass}>
                                En enfriamiento hasta {fmtDateTime(cooldownUntil.toISOString())}
                              </Badge>
                            )}
                            {debouncePending && (
                              <Badge tone="warn" icon={Hourglass}>
                                Esperando que la condición se sostenga
                              </Badge>
                            )}
                            {(state?.failure_count ?? 0) > 0 && (
                              <Badge tone="danger" icon={WarningCircle}>
                                {state?.failure_count} fallos consecutivos
                              </Badge>
                            )}
                            {watcher.workflow_id && (
                              <Link
                                to={`/workflows/${watcher.workflow_id}`}
                                className="text-xs text-accent hover:underline"
                              >
                                Ver automatización
                              </Link>
                            )}
                          </div>

                          <p className="mt-1 text-[13px] leading-relaxed text-muted">
                            Cuando <span className="text-text">{conditionText(watcher)}</span>
                            {` · ${modeLabel(watcher.transition_mode)} · revisa cada ${durationLabel(watcher.interval_seconds)}`}
                            {watcher.cooldown_seconds > 0 ? ` · enfriamiento ${durationLabel(watcher.cooldown_seconds)}` : ""}
                            {watcher.debounce_seconds > 0 ? ` · espera ${durationLabel(watcher.debounce_seconds)}` : ""}
                            {watcher.event_type ? ` · despierta "${watcher.event_type}"` : ""}
                          </p>

                          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-faint">
                            <span>
                              Último check:{" "}
                              {state?.last_check_at || watcher.last_check_at
                                ? fmtDateTime(state?.last_check_at ?? watcher.last_check_at)
                                : "—"}
                            </span>
                            <span>
                              Próximo check (estimado):{" "}
                              {watcher.status === "paused"
                                ? "en pausa"
                                : next
                                  ? fmtDateTime(next.toISOString())
                                  : "pendiente del primer check"}
                            </span>
                            <span>
                              Última activación:{" "}
                              {state?.last_triggered_at ? fmtDateTime(state.last_triggered_at) : "—"}
                            </span>
                            <span className="tabular-nums">Activaciones: {state?.trigger_count ?? 0}</span>
                            <span>Valor: {valueLabel(watcher, state)}</span>
                            <span>Condición: {conditionResult(state)}</span>
                          </div>

                          {debouncePending && (
                            <Progress
                              className="mt-3 max-w-sm"
                              value={Math.min(debounceElapsed, watcher.debounce_seconds)}
                              max={watcher.debounce_seconds}
                              label={`Sosteniéndose desde hace ${durationLabel(Math.round(debounceElapsed))}`}
                              showValue
                            />
                          )}

                          {checking ? (
                            <StatusRow
                              className="mt-2"
                              state="running"
                              title={<span className="text-[13px] text-text">Revisando la tabla ahora</span>}
                              meta={`Consultando ${watcher.table_name} por el campo ${watcher.condition?.field ?? "—"}.`}
                            />
                          ) : (
                            result && (
                              <p
                                className={
                                  result.triggered
                                    ? "mt-2 rounded-md bg-ok-soft px-3 py-2 text-xs leading-relaxed text-ok"
                                    : "mt-2 rounded-md bg-raised px-3 py-2 text-xs leading-relaxed text-muted"
                                }
                                data-testid="watcher-outcome"
                              >
                                {result.reason}
                                {result.triggered && result.transition ? ` (${result.transition})` : ""}
                              </p>
                            )
                          )}

                          {state?.last_error && (
                            <p className="mt-2 flex items-start gap-2 rounded-md border border-danger/25 bg-danger-soft px-3 py-2 text-xs leading-relaxed text-danger">
                              <WarningCircle size={14} className="mt-px shrink-0" aria-hidden />
                              <span>{state.last_error}</span>
                            </p>
                          )}
                        </div>

                        <div className="flex shrink-0 flex-wrap items-center gap-2">
                          <Button
                            size="sm"
                            variant="secondary"
                            leadingIcon={ArrowClockwise}
                            loading={checking}
                            data-testid={`watcher-check-${watcher.id}`}
                            onClick={() => void check(watcher)}
                          >
                            Revisar ahora
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            loading={busy === `status-${watcher.id}`}
                            onClick={() => void toggleStatus(watcher)}
                          >
                            {watcher.status === "paused" ? "Reanudar" : "Pausar"}
                          </Button>
                          <IconButton
                            label={`Eliminar ${watcher.name}`}
                            icon={Trash}
                            className="text-danger"
                            loading={busy === `del-${watcher.id}`}
                            onClick={() => setToDelete(watcher)}
                          />
                        </div>
                      </div>
                    </article>
                  </li>
                );
              })}
            </ul>
          </Panel>
        </div>
      )}

      <ConfirmDialog
        open={toDelete !== null}
        onOpenChange={(open) => {
          if (!open) setToDelete(null);
        }}
        title="Eliminar vigilancia"
        body={
          toDelete
            ? `¿Eliminar la vigilancia "${toDelete.name}"? Dejará de revisar ${toDelete.table_name}.`
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
