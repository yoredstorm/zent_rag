import {
  ArrowClockwise,
  CaretRight,
  CheckCircle,
  CurrencyDollar,
  Lightning,
  MagicWand,
  Plugs,
  Robot,
  Sparkle,
  WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Badge,
  Button,
  ButtonLink,
  Drawer,
  EmptyState,
  ErrorInline,
  Field,
  KeyValue,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  SectionHeader,
  Skeleton,
  Textarea,
  cn,
  type Tone,
} from "../components/ui";
import { fmtCurrency, fmtDateTime, fmtNum } from "../lib/format";

type Result = {
  id: string;
  title: string;
  summary?: string | null;
  section: string;
  importance: string;
  metrics: Record<string, unknown>;
  insights: string[];
  evidence: { provider?: string; action_id?: string }[];
  entities: { entity_type?: string; entity_id?: string }[];
  recommendations: string[];
  generated_at: string;
  workflow_id?: string | null;
  workflow_run_id?: string | null;
  acknowledged_at?: string | null;
};

type Stats = {
  active_automations: number;
  needs_attention: number;
  runs_today: number;
  external_calls_24h: number;
  marketplace_spend_24h: number;
  success_rate_24h: number;
};

const IMPORTANCE_TONE: Record<string, Tone> = {
  INFO: "neutral",
  LOW: "neutral",
  MEDIUM: "info",
  HIGH: "warn",
  CRITICAL: "danger",
};

const SECTION_LABEL: Record<string, string> = {
  needs_attention: "Necesitan atención",
  opportunities: "Oportunidades",
  reports: "Reportes",
  completed: "Automatizaciones completadas",
  verification: "Verificación externa",
  other: "Otros",
};

export default function IntelligencePage() {
  const { session } = useAuth();
  const [stats, setStats] = useState<Stats | null>(null);
  const [results, setResults] = useState<Result[]>([]);
  const [sections, setSections] = useState<Record<string, { count: number }>>({});
  const [activeSection, setActiveSection] = useState<string | undefined>();
  const [prompt, setPrompt] = useState("");
  const [draft, setDraft] = useState<{
    name: string; trigger_type: string; trigger_config: Record<string, unknown>;
    steps: unknown[]; questions: string[]; integration_hint?: string | null; draft: boolean;
    marketplace?: { missing: { action_id: string; install_slug: string | null }[]; wired: { action_id: string; install_id: string }[] } | null;
  } | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [detail, setDetail] = useState<Result | null>(null);

  async function resolveResult(resultId: string) {
    if (!session) return;
    try {
      await api(`/api/v1/intelligence/results/${resultId}/acknowledge`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      setResults((current) => current.filter((item) => item.id !== resultId));
      setDetail((current) => (current?.id === resultId ? null : current));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pude marcar el resultado como resuelto");
    }
  }

  async function load(section?: string) {
    if (!session) return;
    setError("");
    try {
      const [s, r] = await Promise.all([
        api<Stats>("/api/v1/intelligence/automations/stats", { token: session.token, organizationId: session.organizationId }),
        api<{ results: Result[]; sections: Record<string, { count: number }> }>(
          `/api/v1/intelligence/results${section ? `?section=${section}` : ""}`,
          { token: session.token, organizationId: session.organizationId }
        ),
      ]);
      setStats(s);
      setResults(r.results || []);
      setSections(r.sections || {});
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  useEffect(() => {
    void load(activeSection);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, activeSection]);

  async function generateDraft() {
    if (!session || prompt.trim().length < 8) return;
    setBusy("draft");
    setError("");
    try {
      const d = await api<typeof draft>("/api/v1/intelligence/workflow/draft", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ prompt }),
      });
      setDraft(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function installMissing(slug: string) {
    if (!session) return;
    setBusy("missing");
    setError("");
    try {
      await api(`/api/v1/workflows/marketplace/install`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ integration_slug: slug }),
      });
      await generateDraft();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  const attention = stats?.needs_attention ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Intelligence"
        subtitle="Resultados proactivos: Zent mira, verifica y razona cuando importa."
      />
      {stats ? <ErrorInline message={error} /> : null}

      {/* Foco: lo que realmente necesita atención */}
      {stats ? (
        <div className="flex flex-col gap-4" data-testid="intelligence-stats">
          <Panel className="p-4 sm:p-5">
            <p className="eyebrow">Requieren atención</p>
            <div className="mt-2 flex items-baseline gap-3">
              <p className={cn("text-display tabular-nums", attention > 0 ? "text-warn" : "text-ok")}>
                {fmtNum(attention)}
              </p>
              <span className="mb-1 flex items-center gap-1.5 text-[13px] text-muted">
                <WarningCircle
                  size={15}
                  weight="fill"
                  className={attention > 0 ? "text-warn" : "text-ok"}
                  aria-hidden
                />
                {attention > 0 ? "resultados con acción pendiente" : "sin pendientes"}
              </span>
            </div>
            <p className="mt-1.5 max-w-[52ch] text-[13px] leading-relaxed text-muted">
              {attention > 0
                ? "Revisá los resultados y marcalos como resueltos: Zent vuelve a avisar solo si la señal continúa."
                : "Zent no encontró señales que requieran tu intervención en este momento."}
            </p>
          </Panel>

          {/* Demotadas: acompañan al foco */}
          <MetricGrid cols={3}>
            <Metric
              size="md"
              label="Automatizaciones activas"
              value={fmtNum(stats.active_automations)}
              hint="corriendo en el workspace"
              icon={Robot}
            />
            <Metric
              size="md"
              label="Runs hoy"
              value={fmtNum(stats.runs_today)}
              hint="ejecuciones de automatizaciones"
              icon={Lightning}
            />
            <Metric
              size="md"
              label="Éxito 24h"
              value={`${stats.success_rate_24h}%`}
              hint="runs sin error"
              icon={CheckCircle}
            />
            <Metric
              size="md"
              label="Llamadas externas 24h"
              value={fmtNum(stats.external_calls_24h)}
              hint="verificaciones y servicios"
              icon={Plugs}
            />
            <Metric
              size="md"
              label="Gasto marketplace 24h"
              value={fmtCurrency(stats.marketplace_spend_24h)}
              hint="compras y uso de acciones"
              icon={CurrencyDollar}
            />
          </MetricGrid>
        </div>
      ) : error ? (
        <Panel>
          <EmptyState
            icon={WarningCircle}
            title="No pudimos cargar Intelligence"
            body={error}
            hint="Revisá la conexión y volvé a intentar."
            action={
              <Button
                variant="secondary"
                leadingIcon={ArrowClockwise}
                onClick={() => void load(activeSection)}
              >
                Reintentar
              </Button>
            }
          />
        </Panel>
      ) : (
        <Skeleton className="h-[280px] rounded-lg" />
      )}

      {/* Copilot: describe what you want */}
      <Panel data-testid="intelligence-copilot">
        <PanelHeader
          title="Describe lo que quieres automatizar"
          description="Zent arma un borrador con trigger, pasos y dependencias antes de activar nada."
        />
        <div className="flex flex-col gap-3 p-4">
          <Field
            label="¿Qué querés automatizar?"
            hint="Mencioná cuándo corre y qué datos debe revisar. Mínimo 8 caracteres."
          >
            <Textarea
              rows={2}
              placeholder="Cada día a las 6pm dime cómo fueron las ventas y verifica clientes nuevos con RUC…"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
            />
          </Field>
          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="primary"
              leadingIcon={Sparkle}
              loading={busy === "draft"}
              disabled={prompt.trim().length < 8}
              onClick={() => void generateDraft()}
            >
              Generar borrador
            </Button>
            {prompt.trim().length > 0 && prompt.trim().length < 8 && (
              <span className="text-xs text-faint">
                Escribí un poco más para que el borrador tenga contexto.
              </span>
            )}
          </div>

          {draft && (
            <div className="mt-2 rounded-md border border-accent-line bg-accent-soft/40 p-4">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm font-semibold text-text">{draft.name}</p>
                <Badge tone="accent" icon={MagicWand}>
                  Borrador
                </Badge>
              </div>
              <p className="mt-1.5 text-[13px] text-muted">
                Trigger: <code className="mono">{draft.trigger_type}</code>{" "}
                {!!draft.trigger_config?.daily && (
                  <>
                    ·{" "}
                    {String((draft.trigger_config.daily as { time?: string }).time ?? "")}{" "}
                    {String((draft.trigger_config.daily as { timezone?: string }).timezone ?? "")}
                  </>
                )}
              </p>
              <p className="mt-1 text-xs text-faint">
                Pasos: {(draft.steps ?? []).map((s) => String((s as { type: string }).type)).join(" → ")}
              </p>
              {draft.questions?.length > 0 && (
                <ul className="mt-2 list-disc pl-4 text-[13px] leading-relaxed text-muted">
                  {draft.questions.map((q) => (
                    <li key={q}>{q}</li>
                  ))}
                </ul>
              )}
              <p className="mt-2 text-xs text-info">
                Borrador — revisá costos y permisos antes de activar.
              </p>

              {(draft.marketplace?.missing?.length ?? 0) > 0 && (
                <div
                  className="mt-3 rounded-md border border-warn/25 bg-warn-soft p-3"
                  data-testid="draft-missing"
                >
                  <p className="flex items-start gap-2 text-xs font-medium text-warn">
                    <WarningCircle size={14} className="mt-px shrink-0" aria-hidden />
                    Dependencias faltantes — el borrador se creó igual, pero estos nodos necesitan
                    instalación:
                  </p>
                  <ul className="mt-2 space-y-1.5">
                    {draft.marketplace!.missing!.map((m) => (
                      <li key={m.action_id} className="flex flex-wrap items-center gap-2 text-xs text-text">
                        <code className="mono">{m.action_id}</code>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-accent"
                          data-testid={`draft-install-${m.action_id}`}
                          loading={busy === "missing"}
                          onClick={() => void installMissing(m.install_slug ?? m.action_id.split(".")[0])}
                        >
                          Instalar {m.install_slug ?? "integración"}
                        </Button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <ButtonLink to="/workflows" size="sm" variant="secondary" className="mt-3">
                Abrir Workflows para revisarlo
              </ButtonLink>
            </div>
          )}
        </div>
      </Panel>

      {/* Zent Insights */}
      <section>
        <SectionHeader
          title="Zent Insights"
          description="Resultados verificados por sección. Abrí uno para ver métricas, evidencia y recomendación."
          className="mb-3"
        />
        <div className="mb-4 flex flex-wrap gap-1.5">
          <button
            type="button"
            aria-pressed={!activeSection}
            className={cn(
              "btn btn-sm border",
              !activeSection
                ? "border-accent-line bg-accent-soft text-text"
                : "border-border text-muted hover:bg-soft hover:text-text"
            )}
            onClick={() => setActiveSection(undefined)}
          >
            Todo
          </button>
          {Object.entries(SECTION_LABEL).map(([key, label]) => (
            <button
              key={key}
              type="button"
              aria-pressed={activeSection === key}
              className={cn(
                "btn btn-sm border",
                activeSection === key
                  ? "border-accent-line bg-accent-soft text-text"
                  : "border-border text-muted hover:bg-soft hover:text-text"
              )}
              onClick={() => setActiveSection(key)}
            >
              {label} {sections[key] ? `(${sections[key].count})` : ""}
            </button>
          ))}
        </div>

        {results.length > 0 ? (
          <ul className="flex flex-col gap-2">
            {results.map((r) => (
              <li key={r.id}>
                <article className="panel" data-testid="intelligence-result">
                  <button
                    type="button"
                    className="flex w-full items-start gap-3 px-4 py-3.5 text-left transition-colors duration-150 hover:bg-soft/55"
                    onClick={() => setDetail(r)}
                  >
                    <Badge tone={IMPORTANCE_TONE[r.importance] ?? "neutral"}>{r.importance}</Badge>
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13.5px] font-medium text-text">{r.title}</span>
                      {r.summary && (
                        <span className="mt-0.5 line-clamp-2 block text-xs leading-relaxed text-muted">
                          {r.summary}
                        </span>
                      )}
                    </span>
                    <span className="hidden shrink-0 text-xs text-faint tabular-nums sm:block">
                      {fmtDateTime(r.generated_at)}
                    </span>
                    <CaretRight size={14} className="mt-0.5 shrink-0 text-ghost" aria-hidden />
                  </button>
                </article>
              </li>
            ))}
          </ul>
        ) : !stats ? null : (
          <Panel>
            {activeSection ? (
              <EmptyState
                icon={Sparkle}
                title={`Sin resultados en ${SECTION_LABEL[activeSection] ?? activeSection}`}
                body="Ningún resultado verificado quedó en esta sección por ahora."
                action={
                  <Button variant="secondary" size="sm" onClick={() => setActiveSection(undefined)}>
                    Ver todas las secciones
                  </Button>
                }
              />
            ) : (
              <EmptyState
                icon={Sparkle}
                title="Sin resultados todavía"
                body="Activá un workflow de inteligencia (ej. Daily Executive Sales Brief) y los resultados verificados van a aparecer acá."
              />
            )}
          </Panel>
        )}
      </section>

      {/* Insight en detalle: no pierde la lista de fondo */}
      <Drawer
        open={detail !== null}
        onOpenChange={(open) => {
          if (!open) setDetail(null);
        }}
        title={detail?.title ?? "Resultado"}
        description={
          detail
            ? `${SECTION_LABEL[detail.section] ?? detail.section} · ${fmtDateTime(detail.generated_at)}`
            : undefined
        }
        width={520}
        footer={
          detail ? (
            <>
              {detail.workflow_id && (
                <ButtonLink to={`/workflows/${detail.workflow_id}`} variant="secondary" size="sm">
                  Abrir workflow
                </ButtonLink>
              )}
              <Button
                variant="primary"
                size="sm"
                data-testid={`intelligence-resolve-${detail.id}`}
                onClick={() => void resolveResult(detail.id)}
              >
                Marcar resuelto
              </Button>
            </>
          ) : undefined
        }
      >
        {detail && (
          <div className="flex flex-col gap-5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={IMPORTANCE_TONE[detail.importance] ?? "neutral"}>
                {detail.importance}
              </Badge>
              <Badge>{SECTION_LABEL[detail.section] ?? detail.section}</Badge>
            </div>

            {detail.summary && (
              <p className="text-[13px] leading-relaxed text-muted">{detail.summary}</p>
            )}

            {Object.keys(detail.metrics ?? {}).length > 0 && (
              <div>
                <p className="eyebrow mb-2">Métricas</p>
                <KeyValue
                  columns={2}
                  items={Object.entries(detail.metrics).map(([key, value]) => ({
                    key,
                    value: String(value),
                    mono: true,
                  }))}
                />
              </div>
            )}

            {(detail.insights ?? []).length > 0 && (
              <div>
                <p className="eyebrow mb-2">Insights</p>
                <ul className="flex flex-col gap-1.5">
                  {(detail.insights ?? []).slice(0, 6).map((insight, idx) => (
                    <li key={idx} className="flex items-start gap-2 text-[13px] leading-relaxed text-text">
                      <Lightning size={13} weight="fill" className="mt-0.5 shrink-0 text-accent" aria-hidden />
                      <span>{insight}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {(detail.evidence ?? []).length > 0 && (
              <div className="rounded-md border border-info/25 bg-info-soft/50 p-3">
                <p className="eyebrow text-info">Fuentes de verificación</p>
                <ul className="mt-2 flex flex-col gap-1">
                  {(detail.evidence ?? []).map((e, idx) => (
                    <li key={idx} className="flex items-center gap-2 text-xs text-muted">
                      <CheckCircle size={13} weight="fill" className="shrink-0 text-info" aria-hidden />
                      <span className="min-w-0 truncate">
                        {e.provider ?? e.action_id ?? "external"}
                      </span>
                      <span className="ml-auto shrink-0 text-faint">
                        verificado {fmtDateTime(detail.generated_at)}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {(detail.recommendations ?? []).length > 0 && (
              <div className="rounded-md border border-border bg-raised p-3">
                <p className="eyebrow">Recomendación</p>
                <ul className="mt-2 flex flex-col gap-1.5">
                  {(detail.recommendations ?? []).slice(0, 4).map((recommendation, idx) => (
                    <li key={idx} className="text-[13px] leading-relaxed text-text">
                      · {recommendation}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {detail.workflow_id && (
              <p className="text-xs text-faint">
                Workflow:{" "}
                <Link
                  to={`/workflows/${detail.workflow_id}`}
                  className="mono text-accent hover:underline"
                >
                  {detail.workflow_id.slice(0, 8)}…
                </Link>
              </p>
            )}
          </div>
        )}
      </Drawer>
    </div>
  );
}
