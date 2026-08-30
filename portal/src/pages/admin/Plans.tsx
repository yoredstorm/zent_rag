import { Cards } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { platformApi } from "../../api";
import { EmptyState, ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
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
};

const BOOL_LABELS: Record<string, string> = {
  api_access: "Acceso API",
  custom_models: "Modelos personalizados",
  embed_widget: "Widget embebido",
  eval_ui: "Evaluación RAG",
  sso: "SSO",
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
      {loading && <SkeletonBlock />}
      {!loading && plans.length === 0 && (
        <EmptyState icon={Cards} title="Sin planes" body="No hay planes cargados." />
      )}
      {plans.length > 0 && (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,280px)_1fr]">
          <div className="panel overflow-x-auto">
            <table className="w-full min-w-[240px] text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-faint">
                <tr>
                  <th className="px-4 py-3">Plan</th>
                </tr>
              </thead>
              <tbody>
                {plans.map((p) => (
                  <tr key={p.id} className="border-t border-border">
                    <td className="px-4 py-2">
                      <button
                        type="button"
                        className={`min-h-11 w-full rounded-md px-3 text-left text-sm ${
                          p.id === selectedId
                            ? "bg-accent-soft text-text"
                            : "text-muted hover:bg-soft hover:text-text"
                        }`}
                        onClick={() => selectPlan(p)}
                      >
                        {p.display_name || p.name}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {selected && (
            <form
              className="panel px-5 py-4"
              onSubmit={(e) => {
                e.preventDefault();
                void save();
              }}
            >
              <h2 className="text-sm font-semibold text-text">
                Entitlements — {selected.display_name}
              </h2>
              <p className="mt-1 text-xs text-faint">
                Vacío en un número significa ilimitado.
              </p>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                {Object.entries(INT_LABELS).map(([key, label]) => (
                  <label key={key} className="block text-sm">
                    <span className="mb-1 block text-muted">{label}</span>
                    <input
                      className="min-h-11 w-full rounded-md border border-border bg-bg px-3 text-sm"
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
                      }}
                    />
                  </label>
                ))}
              </div>
              <fieldset className="mt-4">
                <legend className="mb-2 text-sm text-muted">Funciones</legend>
                <div className="grid gap-2 sm:grid-cols-2">
                  {Object.entries(BOOL_LABELS).map(([key, label]) => (
                    <label key={key} className="flex min-h-11 items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        className="h-4 w-4"
                        checked={Boolean(draft[key])}
                        onChange={(e) =>
                          setDraft((prev) => ({ ...prev, [key]: e.target.checked }))
                        }
                      />
                      {label}
                    </label>
                  ))}
                </div>
              </fieldset>
              <div className="mt-4 flex flex-wrap items-center gap-3">
                <button type="submit" className="btn btn-primary min-h-11" disabled={saving}>
                  {saving ? "Guardando…" : "Guardar"}
                </button>
                {saved && (
                  <p className="text-sm text-muted" role="status">
                    Cambios guardados.
                  </p>
                )}
              </div>
            </form>
          )}
        </div>
      )}
    </div>
  );
}
