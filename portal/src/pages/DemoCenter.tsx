import { CheckCircle, CloudSun, Database, FlowArrow, GameController, Sparkle } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import type { WorkflowTemplate } from "../components/workflowStudio/types";
import {
  Badge,
  Breadcrumbs,
  Button,
  ButtonLink,
  EmptyState,
  ErrorInline,
  InfoInline,
  PageHeader,
  Panel,
  SkeletonCards,
} from "../components/ui";

type DemoMeta = {
  icon: typeof Sparkle;
  tagline: string;
  cost: string;
  deterministic: boolean;
  testHint: string;
};

const DEMO_META: Record<string, DemoMeta> = {
  "pokemon-analyst": {
    icon: GameController,
    tagline: "Pokémon",
    cost: "Usa 1 agente por ejecución",
    deterministic: false,
    testHint: "Pruébalo con “pikachu”, “charmander” o “bulbasaur”.",
  },
  "pokemon-daily": {
    icon: GameController,
    tagline: "Pokémon",
    cost: "Usa 1 agente por ejecución",
    deterministic: false,
    testHint: "Se ejecuta todos los días a las 09:00; puedes probarlo antes desde el estudio.",
  },
  "weather-heat-alert": {
    icon: CloudSun,
    tagline: "Clima",
    cost: "Casi cero IA: solo consulta y condición",
    deterministic: true,
    testHint: "Cada mañana revisa Lima y avisa solo si supera 30 °C.",
  },
  "weather-logistics-analyst": {
    icon: CloudSun,
    tagline: "Clima",
    cost: "Usa 1 agente por ejecución",
    deterministic: false,
    testHint: "Resume riesgos logísticos del pronóstico cada mañana.",
  },
  "demo-records-brief": {
    icon: Database,
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
        tagline: "Demo",
        cost: "Revisa el flujo antes de activarlo",
        deterministic: false,
        testHint: "Pruébalo desde el estudio.",
      }
    );
  }

  return (
    <div className="space-y-5">
      <Breadcrumbs items={[{ label: "Workflows", to: "/workflows" }, { label: "Demo Center" }]} />
      <PageHeader
        title="Demo Center"
        subtitle="Automatizaciones listas con APIs públicas, sin API key y sin configuración empresarial."
        actions={
          <ButtonLink to="/marketplace" variant="secondary">
            Ver integraciones
          </ButtonLink>
        }
      />
      <ErrorInline message={error} className="mb-0" />
      <InfoInline className="mb-0">
        Las demos usan PokéAPI, Open-Meteo y JSONPlaceholder (datos falsos). No requieren
        credenciales: al probar se instalan solas y quedan como borrador hasta que las actives.
      </InfoInline>

      {loading ? (
        <SkeletonCards count={3} height={180} />
      ) : templates.length === 0 ? (
        <Panel>
          <div data-testid="demo-empty">
            <EmptyState
              icon={FlowArrow}
              title="Sin recetas demo"
              body="No hay recetas demo disponibles todavía. Reiniciá la API para sembrarlas."
            />
          </div>
        </Panel>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {templates.map((template) => {
            const meta = metaOf(template.slug);
            const Icon = meta.icon;
            return (
              <Panel
                key={template.slug}
                data-testid={`demo-${template.slug}`}
                className="flex flex-col gap-2 p-4"
              >
                <div className="flex items-center gap-2">
                  <Icon size={18} className="text-faint" aria-hidden />
                  <Badge tone="neutral">{meta.tagline}</Badge>
                  {meta.deterministic && (
                    <span className="ml-auto" data-testid="demo-deterministic">
                      <Badge tone="ok" icon={CheckCircle}>
                        sin IA
                      </Badge>
                    </span>
                  )}
                </div>
                <h2 className="text-h3">{template.name}</h2>
                <p className="text-[13px] leading-relaxed text-muted">{template.description}</p>
                <dl className="mt-1 space-y-1 text-[11px] text-faint">
                  <div className="flex gap-1.5">
                    <dt className="shrink-0 font-medium">Coste:</dt>
                    <dd>{meta.cost}</dd>
                  </div>
                  <div className="flex gap-1.5">
                    <dt className="shrink-0 font-medium">Prueba:</dt>
                    <dd>{meta.testHint}</dd>
                  </div>
                </dl>
                <Button
                  variant="primary"
                  className="mt-auto"
                  leadingIcon={Sparkle}
                  loading={busy === template.slug}
                  disabled={!!busy}
                  data-testid={`demo-start-${template.slug}`}
                  onClick={() => void tryDemo(template.slug)}
                >
                  Probar esta automatización
                </Button>
              </Panel>
            );
          })}
        </div>
      )}
      <p className="text-xs text-faint">
        ¿Necesitás algo más? Mirá las{" "}
        <Link to="/workflows" className="text-accent underline underline-offset-2">
          automatizaciones
        </Link>{" "}
        de tu organización.
      </p>
    </div>
  );
}
