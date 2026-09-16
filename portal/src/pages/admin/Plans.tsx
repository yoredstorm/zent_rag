import { Cards } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  Button,
  EmptyState,
  ErrorInline,
  Field,
  FormActions,
  Input,
  PageHeader,
  Panel,
  PanelHeader,
  SaveStatus,
  Skeleton,
  Switch,
  cn,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Entitlements = Record<string, boolean | number | null>;

type Plan = {
  id: string;
  name: string;
  display_name: string;
  is_trial: boolean;
  price_monthly_cents: number;
  entitlements: Entitlements;
};

const INT_LABELS: Record<string, string> = {
  monthly_requests: "Consultas mensuales",
  max_users: "Usuarios",
  max_agents: "Agentes",
  max_knowledge_bases: "Colecciones",
  max_connectors: "Conectores",
  managed_db_max_mb: "Managed DB MB",
};

const BOOL_LABELS: Record<string, string> = {
  api_access: "Acceso API",
  custom_models: "Modelos personalizados",
  embed_widget: "Widget embebido",
  eval_ui: "Evaluación RAG",
  sso: "SSO",
  managed_db: "Managed DB",
  managed_db_backups: "Managed DB backups",
};

function draftFrom(plan: Plan): Entitlements {
  return { ...plan.entitlements };
}

export default function AdminPlansPage() {
  const { session } = usePlatformAuth();
  const [plans, setPlans] = useState<Plan[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [draft, setDraft] = useState<Entitlements>({});
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const selected = useMemo(
    () => plans.find((p) => p.id === selectedId) || null,
    [plans, selectedId]
  );

  useEffect(() => {
    if (!session) return;
    (async () => {
      setLoading(true);
      try {
        const data = await platformApi<{ plans: Plan[] }>("/api/v1/platform/plans", {
          token: session.token,
        });
        const list = data.plans || [];
        setPlans(list);
        const first = list[0];
        if (first) {
          setSelectedId(first.id);
          setDraft(draftFrom(first));
        }
        setError("");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando planes");
      } finally {
        setLoading(false);
      }
    })();
  }, [session]);

  function selectPlan(plan: Plan) {
    setSelectedId(plan.id);
    setDraft(draftFrom(plan));
    setSaved(false);
  }

  async function save() {
    if (!session || !selected) return;
    setSaving(true);
    setError("");
    setSaved(false);
    const items: Array<{
      key: string;
      value_type: "bool" | "int";
      value_bool?: boolean | null;
      value_int?: number | null;
    }> = [];
    for (const key of Object.keys(INT_LABELS)) {
      const raw = draft[key];
      items.push({
        key,
        value_type: "int",
        value_int: typeof raw === "number" ? raw : null,
      });
    }
    for (const key of Object.keys(BOOL_LABELS)) {
      items.push({
        key,
        value_type: "bool",
        value_bool: Boolean(draft[key]),
      });
    }
    try {
      const out = await platformApi<{ entitlements: Entitlements }>(
        `/api/v1/platform/plans/${selected.id}/entitlements`,
        {
          method: "PUT",
          token: session.token,
          body: JSON.stringify({ entitlements: items }),
        }
      );
      const next = plans.map((p) =>
        p.id === selected.id ? { ...p, entitlements: out.entitlements } : p
      );
      setPlans(next);
      setDraft(out.entitlements);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Planes"
        subtitle="Límites y funciones. Los cambios aplican sin alterar el esquema."
      />
      <ErrorInline message={error} />
      {loading && (
        <div className="grid gap-3 lg:grid-cols-[minmax(0,280px)_1fr]" aria-hidden>
          <Skeleton className="h-[220px] rounded-lg" />
          <Skeleton className="h-[320px] rounded-lg" />
        </div>
      )}
      {!loading && plans.length === 0 && (
        <Panel>
          <EmptyState
            icon={Cards}
            title="Sin planes"
            body="La plataforma no devolvió planes configurados."
          />
        </Panel>
      )}
      {plans.length > 0 && (
        <div className="grid gap-3 lg:grid-cols-[minmax(0,280px)_1fr]">
          <Panel className="self-start overflow-hidden">
            <PanelHeader title="Planes" description="Elegí un plan para editar sus entitlements." />
            <nav aria-label="Planes" className="flex flex-col gap-0.5 p-2">
              {plans.map((p) => {
                const active = p.id === selectedId;
                return (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => selectPlan(p)}
                    aria-current={active ? "true" : undefined}
                    className={cn(
                      "group relative flex min-h-9 w-full cursor-pointer items-center gap-2 rounded-sm px-2.5 text-left text-[13px]",
                      active
                        ? "bg-soft/70 font-medium text-text"
                        : "text-muted hover:bg-soft/45 hover:text-text"
                    )}
                  >
                    {active && (
                      <span
                        className="absolute top-1 bottom-1 -left-0.5 w-[2px] rounded-full bg-accent"
                        aria-hidden
                      />
                    )}
                    <span className="min-w-0 flex-1 truncate">{p.display_name || p.name}</span>
                    {p.is_trial && <Badge tone="warn">trial</Badge>}
                  </button>
                );
              })}
            </nav>
          </Panel>

          {selected && (
            <Panel>
              <form
                className="p-4"
                onSubmit={(e) => {
                  e.preventDefault();
                  void save();
                }}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="text-h3">Entitlements — {selected.display_name}</h2>
                    <p className="mt-0.5 text-xs leading-relaxed text-faint">
                      Vacío en un número significa ilimitado.
                    </p>
                  </div>
                  <SaveStatus
                    state={saving ? "saving" : saved ? "saved" : "idle"}
                    savedLabel="Cambios guardados."
                  />
                </div>

                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  {Object.entries(INT_LABELS).map(([key, label]) => (
                    <Field key={key} label={label}>
                      <Input
                        type="number"
                        inputMode="numeric"
                        min={0}
                        value={draft[key] == null ? "" : String(draft[key])}
                        onChange={(e) => {
                          const v = e.target.value;
                          setDraft((prev) => ({
                            ...prev,
                            [key]: v === "" ? null : Number(v),
                          }));
                          setSaved(false);
                        }}
                      />
                    </Field>
                  ))}
                </div>

                <fieldset className="mt-4">
                  <legend className="eyebrow mb-2">Funciones</legend>
                  <div className="grid gap-2.5 sm:grid-cols-2">
                    {Object.entries(BOOL_LABELS).map(([key, label]) => (
                      <Switch
                        key={key}
                        label={label}
                        checked={Boolean(draft[key])}
                        onCheckedChange={(checked) => {
                          setDraft((prev) => ({ ...prev, [key]: checked }));
                          setSaved(false);
                        }}
                      />
                    ))}
                  </div>
                </fieldset>

                <FormActions className="mt-5">
                  <Button type="submit" variant="primary" loading={saving}>
                    Guardar
                  </Button>
                </FormActions>
              </form>
            </Panel>
          )}
        </div>
      )}
    </div>
  );
}
