import { CaretDown, CaretUp, MagicWand, Sparkle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorInline, PageHeader, SkeletonBlock } from "../components/ui";

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
};

type Stats = {
  active_automations: number;
  needs_attention: number;
  runs_today: number;
  external_calls_24h: number;
  marketplace_spend_24h: number;
  success_rate_24h: number;
};

const IMPORTANCE_CLS: Record<string, string> = {
  INFO: "badge-muted",
  LOW: "badge-muted",
  MEDIUM: "badge-info",
  HIGH: "badge-warning",
  CRITICAL: "badge-danger",
};

const SECTION_LABEL: Record<string, string> = {
  needs_attention: "Needs Attention",
  opportunities: "Opportunities",
  reports: "Reports",
  completed: "Completed Automations",
  verification: "External Verification",
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
  const [openDetails, setOpenDetails] = useState<Record<string, boolean>>({});

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

  return (
    <div className="space-y-6">
      <PageHeader
        title="Intelligence"
        subtitle="Resultados proactivos: Zent mira, verifica y razona cuando importa."
      />
      {error && <ErrorInline>{error}</ErrorInline>}

      {/* Automations Home */}
      {stats ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6" data-testid="intelligence-stats">
          {[
            { label: "Automatizaciones activas", value: stats.active_automations },
            { label: "Necesitan atención", value: stats.needs_attention, warn: stats.needs_attention > 0 },
            { label: "Runs hoy", value: stats.runs_today },
            { label: "Éxito 24h", value: `${stats.success_rate_24h}%` },
            { label: "Llamadas externas", value: stats.external_calls_24h },
            { label: "Gasto marketplace", value: `S/ ${stats.marketplace_spend_24h.toFixed(2)}` },
          ].map((c) => (
            <div key={c.label} className={`panel p-3 ${c.warn ? "border-danger/40" : ""}`}>
              <p className="text-lg font-semibold text-text">{c.value}</p>
              <p className="text-[10px] text-faint">{c.label}</p>
            </div>
          ))}
        </div>
      ) : (
        <SkeletonBlock className="h-20" />
      )}

      {/* Copilot: describe what you want */}
      <section className="panel space-y-2 p-4" data-testid="intelligence-copilot">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-text">
          <MagicWand size={15} className="text-accent" /> Describe lo que quieres automatizar
        </h2>
        <div className="flex gap-2">
          <input
            className="flex-1 rounded-md border border-border bg-soft px-3 py-2 text-sm"
            placeholder="Cada día a las 6pm dime cómo fueron las ventas y verifica clientes nuevos con RUC…"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
          />
          <button
            type="button"
            className="btn btn-primary min-h-9 px-3 text-xs"
            disabled={!!busy || prompt.trim().length < 8}
            onClick={() => void generateDraft()}
          >
            <Sparkle size={13} /> Generar borrador
          </button>
        </div>
        {draft && (
          <div className="rounded-md border border-accent/30 bg-accent-soft/30 p-3 text-xs">
            <p className="text-sm font-semibold text-text">{draft.name}</p>
            <p className="mt-1 text-muted">
              Trigger: <code className="font-mono">{draft.trigger_type}</code>{" "}
              {!!draft.trigger_config?.daily && (
                <>· {String((draft.trigger_config.daily as { time?: string }).time ?? "")} {String((draft.trigger_config.daily as { timezone?: string }).timezone ?? "")}</>
              )}
            </p>
            <p className="mt-1 text-faint">Pasos: {(draft.steps ?? []).map((s) => String((s as { type: string }).type)).join(" → ")}</p>
            {draft.questions?.length > 0 && (
              <ul className="mt-2 list-disc pl-4 text-muted">
                {draft.questions.map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
            )}
            <p className="mt-2 text-[10px] text-info">Borrador — revisa costos y permisos antes de activar.</p>
            {(draft.marketplace?.missing?.length ?? 0) > 0 && (
              <div className="mt-2 rounded-md border border-warning/40 bg-warning/10 p-2" data-testid="draft-missing">
                <p className="text-[11px] font-medium text-warning">
                  Dependencias faltantes — el borrador se creó igual, pero estos nodos necesitan instalación:
                </p>
                <ul className="mt-1 space-y-1">
                  {draft.marketplace!.missing!.map((m) => (
                    <li key={m.action_id} className="flex flex-wrap items-center gap-2 text-[11px] text-text">
                      <code className="font-mono">{m.action_id}</code>
                      <button
                        type="button"
                        className="btn btn-ghost min-h-6 px-2 text-[10px] text-accent"
                        data-testid={`draft-install-${m.action_id}`}
                        onClick={() => void installMissing(m.install_slug ?? m.action_id.split(".")[0])}
                      >
                        Instalar {m.install_slug ?? "integración"}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <Link to="/workflows" className="btn btn-secondary mt-2 inline-flex min-h-7 px-2 text-[10px]">
              Abrir Workflows para revisarlo
            </Link>
          </div>
        )}
      </section>

      {/* Zent Insights */}
      <section>
        <h2 className="mb-2 text-sm font-semibold text-text">Zent Insights</h2>
        <div className="mb-3 flex flex-wrap gap-1.5">
          <button
            type="button"
            className={`min-h-7 rounded-md border px-2.5 text-[11px] ${!activeSection ? "border-accent bg-accent/10 text-text" : "border-border text-muted hover:text-text"}`}
            onClick={() => setActiveSection(undefined)}
          >
            Todo
          </button>
          {Object.entries(SECTION_LABEL).map(([key, label]) => (
            <button
              key={key}
              type="button"
              className={`min-h-7 rounded-md border px-2.5 text-[11px] ${activeSection === key ? "border-accent bg-accent/10 text-text" : "border-border text-muted hover:text-text"}`}
              onClick={() => setActiveSection(key)}
            >
              {label} {sections[key] ? `(${sections[key].count})` : ""}
            </button>
          ))}
        </div>

        <div className="space-y-2">
          {results.map((r) => (
            <div key={r.id} className="panel p-3" data-testid="intelligence-result">
              <button
                type="button"
                className="flex w-full items-center gap-2 text-left"
                onClick={() => setOpenDetails((d) => ({ ...d, [r.id]: !d[r.id] }))}
              >
                <span className={`badge ${IMPORTANCE_CLS[r.importance] ?? "badge-muted"}`}>{r.importance}</span>
                <span className="flex-1 truncate text-sm font-medium text-text">{r.title}</span>
                <span className="text-[10px] text-faint">{new Date(r.generated_at).toLocaleString()}</span>
                {openDetails[r.id] ? <CaretUp size={13} /> : <CaretDown size={13} />}
              </button>
              {r.summary && <p className="mt-1 text-xs text-muted">{r.summary}</p>}
              {openDetails[r.id] && (
                <div className="mt-2 space-y-2 border-t border-border pt-2 text-[11px]">
                  {Object.keys(r.metrics ?? {}).length > 0 && (
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(r.metrics).map(([k, v]) => (
                        <span key={k} className="rounded bg-soft px-2 py-0.5 text-faint">
                          {k}: <b className="text-text">{String(v)}</b>
                        </span>
                      ))}
                    </div>
                  )}
                  {(r.insights ?? []).length > 0 && (
                    <ul className="list-disc pl-4 text-muted">
                      {(r.insights ?? []).slice(0, 4).map((i, idx) => (
                        <li key={idx}>{i}</li>
                      ))}
                    </ul>
                  )}
                  {(r.evidence ?? []).length > 0 && (
                    <div className="rounded-md border border-info/30 bg-info/5 p-2">
                      <p className="text-[9px] font-semibold tracking-wide text-info uppercase">Verification Sources</p>
                      {(r.evidence ?? []).map((e, idx) => (
                        <p key={idx} className="mt-1 text-faint">
                          ✓ {e.provider ?? e.action_id ?? "external"} — Verified {new Date(r.generated_at).toLocaleTimeString()}
                        </p>
                      ))}
                    </div>
                  )}
                  {r.workflow_id && (
                    <p className="text-faint">
                      workflow: <code className="font-mono">{r.workflow_id.slice(0, 8)}…</code>
                    </p>
                  )}
                </div>
              )}
            </div>
          ))}
          {results.length === 0 && (
            <p className="rounded-md border border-dashed border-border p-6 text-center text-xs text-faint">
              Sin resultados todavía. Activa un workflow de inteligencia (ej. Daily Executive Sales Brief) y aparecerán aquí.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}