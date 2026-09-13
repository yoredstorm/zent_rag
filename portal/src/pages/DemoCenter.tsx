import { CheckCircle, CloudSun, Database, FlowArrow, GameController, Sparkle } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Breadcrumb } from "../components/Breadcrumb";
import { ErrorInline, PageHeader, SkeletonBlock, Spinner } from "../components/ui";
import type { WorkflowTemplate } from "../components/workflowStudio/types";

type DemoMeta = {
  icon: typeof Sparkle;
  color: string;
  tagline: string;
  cost: string;
  deterministic: boolean;
  testHint: string;
};

const DEMO_META: Record<string, DemoMeta> = {
  "pokemon-analyst": {
    icon: GameController,
    color: "text-amber-400",
    tagline: "Pokémon",
    cost: "Usa 1 agente por ejecución",
    deterministic: false,
    testHint: "Pruébalo con “pikachu”, “charmander” o “bulbasaur”.",
  },
  "pokemon-daily": {
    icon: GameController,
    color: "text-amber-400",
    tagline: "Pokémon",
    cost: "Usa 1 agente por ejecución",
    deterministic: false,
    testHint: "Se ejecuta todos los días a las 09:00; puedes probarlo antes desde el estudio.",
  },
  "weather-heat-alert": {
    icon: CloudSun,
    color: "text-info",
    tagline: "Clima",
    cost: "Casi cero IA: solo consulta y condición",
    deterministic: true,
    testHint: "Cada mañana revisa Lima y avisa solo si supera 30 °C.",
  },
  "weather-logistics-analyst": {
    icon: CloudSun,
    color: "text-info",
    tagline: "Clima",
    cost: "Usa 1 agente por ejecución",
    deterministic: false,
    testHint: "Resume riesgos logísticos del pronóstico cada mañana.",
  },
  "demo-records-brief": {
    icon: Database,
    color: "text-fuchsia-400",
    tagline: "Demo API (datos falsos)",
    cost: "Usa 1 agente por ejecución",
    deterministic: false,
    testHint: "DEMO DATA de JSONPlaceholder: nunca usar en producción.",
  },
};

export default function DemoCenterPage() {
  const { session } = useAuth();
  const navigate = useNavigate();
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!session) return;
    try {
      const data = await api<{ templates: WorkflowTemplate[] }>("/api/v1/workflows/templates", {
        token: session.token,
        organizationId: session.organizationId,
      });
      setTemplates((data.templates || []).filter((template) => template.category === "demo"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => {
    void load();
  }, [load]);

  async function tryDemo(slug: string) {
    if (!session) return;
    setBusy(slug);
    setError("");
    try {
      const out = await api<{ workflow_id: string; hook_secret?: string }>(
        `/api/v1/workflows/templates/${slug}/install`,
        { method: "POST", token: session.token, organizationId: session.organizationId },
      );
      navigate(`/workflows/${out.workflow_id}?panel=test`, {
        state: { hookSecret: out.hook_secret },
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
      setBusy("");
    }
  }

  function metaOf(slug: string): DemoMeta {
    return (
      DEMO_META[slug] ?? {
        icon: FlowArrow,
        color: "text-muted",
        tagline: "Demo",
        cost: "Revisa el flujo antes de activarlo",
        deterministic: false,
        testHint: "Pruébalo desde el estudio.",
      }
    );
  }

  return (
    <div className="space-y-5">
      <Breadcrumb items={[{ label: "Workflows", to: "/workflows" }, { label: "Demo Center" }]} />
      <PageHeader
        title="Demo Center"
        subtitle="Automatizaciones listas con APIs públicas, sin API key y sin configuración empresarial."
        actions={
          <Link to="/marketplace" className="btn btn-secondary min-h-11 text-xs">
            Ver integraciones
          </Link>
        }
      />
      <ErrorInline message={error} />

      <div className="rounded-lg border border-border bg-soft/50 p-3 text-[11px] text-muted">
        Las demos usan PokéAPI, Open-Meteo y JSONPlaceholder (datos falsos). No requieren credenciales: al
        probar se instalan solas y quedan como borrador hasta que las actives.
      </div>

      {loading ? (
        <div className="panel p-5"><SkeletonBlock rows={4} /></div>
      ) : templates.length === 0 ? (
        <div className="panel p-5 text-sm text-muted" data-testid="demo-empty">
          No hay recetas demo disponibles todavía. Reinicia la API para sembrarlas.
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {templates.map((template) => {
            const meta = metaOf(template.slug);
            const Icon = meta.icon;
            return (
              <article key={template.slug} className="panel flex flex-col gap-2 p-5" data-testid={`demo-${template.slug}`}>
                <div className="flex items-center gap-2">
                  <Icon size={20} className={meta.color} aria-hidden />
                  <span className="text-[10px] font-semibold tracking-wider text-faint uppercase">{meta.tagline}</span>
                  {meta.deterministic && (
                    <span className="badge badge-ok ml-auto" data-testid="demo-deterministic">
                      <CheckCircle size={10} className="mr-1" aria-hidden /> sin IA
                    </span>
                  )}
                </div>
                <h2 className="text-sm font-semibold text-text">{template.name}</h2>
                <p className="text-xs text-muted">{template.description}</p>
                <p className="text-[10px] text-faint">Coste: {meta.cost}</p>
                <p className="text-[10px] text-faint">{meta.testHint}</p>
                <button
                  type="button"
                  className="btn btn-primary mt-auto min-h-9 gap-1.5 px-3 text-xs"
                  disabled={!!busy}
                  data-testid={`demo-start-${template.slug}`}
                  onClick={() => void tryDemo(template.slug)}
                >
                  {busy === template.slug ? <Spinner size={13} /> : <Sparkle size={13} aria-hidden />}
                  Probar esta automatización
                </button>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
