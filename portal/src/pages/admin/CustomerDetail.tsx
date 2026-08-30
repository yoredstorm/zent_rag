import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { platformApi, saveSession } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock, StatCard } from "../../components/ui";
import { IMPERSONATING_KEY, usePlatformAuth } from "../../platformAuth";

type FinopsOrg = {
  revenue_cents: number;
  costs: { llm: number; embedding: number; storage: number; infra: number };
  gross_profit: number;
  gross_margin_pct: number | null;
};

type Detail = {
  id: string;
  name: string;
  company_name: string | null;
  email: string | null;
  status: string;
  plan: string | null;
  subscription_status: string | null;
  started: string | null;
  mrr_cents: number;
  users: number;
  agents: number;
  requests_30d: number;
  ai_cost_30d: number;
  margin: number | null;
  payment_provider: string | null;
};

export default function AdminCustomerDetailPage() {
  const { orgId } = useParams();
  const navigate = useNavigate();
  const { session } = usePlatformAuth();
  const [data, setData] = useState<Detail | null>(null);
  const [finops, setFinops] = useState<FinopsOrg | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [confirm, setConfirm] = useState<"" | "pause" | "suspend" | "cancel" | "reset">("");

  async function reload() {
    if (!session || !orgId) return;
    const d = await platformApi<Detail>(`/api/v1/platform/organizations/${orgId}`, {
      token: session.token,
    });
    setData(d);
    const f = await platformApi<FinopsOrg>(
      `/api/v1/platform/finops/organizations/${orgId}`,
      { token: session.token }
    );
    setFinops(f);
  }

  useEffect(() => {
    if (!session || !orgId) return;
    (async () => {
      try {
        await reload();
        setError("");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando ficha");
      }
    })();
  }, [session, orgId]);

  async function run(path: string, action: string) {
    if (!session || !orgId) return;
    setBusy(action);
    setError("");
    try {
      await platformApi(`/api/v1/platform/organizations/${orgId}/${path}`, {
        method: "POST",
        token: session.token,
        body: path === "plan" ? undefined : "{}",
      });
      await reload();
      setConfirm("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "La acción falló");
    } finally {
      setBusy("");
    }
  }

  async function impersonate() {
    if (!session || !orgId || !data) return;
    setBusy("impersonate");
    setError("");
    try {
      const out = await platformApi<{ access_token: string }>(
        `/api/v1/platform/organizations/${orgId}/impersonate`,
        {
          method: "POST",
          token: session.token,
          body: JSON.stringify({ expires_seconds: 3600 }),
        }
      );
      saveSession({
        token: out.access_token,
        organizationId: orgId,
        companyName: data.company_name || data.name,
        email: data.email || undefined,
      });
      localStorage.setItem(IMPERSONATING_KEY, data.company_name || data.name);
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo impersonar");
    } finally {
      setBusy("");
    }
  }

  if (!data && !error) return <SkeletonBlock />;

  return (
    <div>
      <PageHeader
        title={data?.company_name || data?.name || "Cliente"}
        subtitle={data?.email || undefined}
        actions={
          <Link to="/admin/customers" className="btn btn-secondary min-h-11">
            Volver
          </Link>
        }
      />
      <ErrorInline message={error} />
      {data && (
        <>
          <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Plan" value={data.plan || "—"} hint={data.subscription_status || ""} />
            <StatCard label="Pago" value={data.payment_provider || "manual"} />
            <StatCard label="MRR" value={`$${(data.mrr_cents / 100).toFixed(0)}`} />
            <StatCard label="Usuarios" value={data.users} />
            <StatCard label="Agentes" value={data.agents} />
            <StatCard label="Requests 30d" value={data.requests_30d} />
            <StatCard
              label="LLM"
              value={`$${(finops?.costs.llm ?? data.ai_cost_30d).toFixed(2)}`}
            />
            <StatCard
              label="Embeddings"
              value={`$${(finops?.costs.embedding ?? 0).toFixed(2)}`}
            />
            <StatCard
              label="Storage"
              value={`$${(finops?.costs.storage ?? 0).toFixed(2)}`}
            />
            <StatCard
              label="Infra"
              value={`$${(finops?.costs.infra ?? 0).toFixed(2)}`}
            />
            <StatCard
              label="Revenue (cash)"
              value={
                finops
                  ? `$${(finops.revenue_cents / 100).toFixed(0)}`
                  : "—"
              }
            />
            <StatCard
              label="Gross profit"
              value={finops ? `$${finops.gross_profit.toFixed(2)}` : "—"}
            />
            <StatCard
              label="Margen"
              value={
                finops?.gross_margin_pct == null
                  ? data.margin == null
                    ? "—"
                    : `${data.margin}%`
                  : `${finops.gross_margin_pct}%`
              }
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn btn-primary min-h-11"
              disabled={!!busy}
              onClick={() => void impersonate()}
            >
              Impersonar
            </button>
            <button type="button" className="btn btn-secondary min-h-11" disabled={!!busy} onClick={() => setConfirm("pause")}>
              Pausar
            </button>
            <button type="button" className="btn btn-secondary min-h-11" disabled={!!busy} onClick={() => setConfirm("suspend")}>
              Suspender
            </button>
            <button type="button" className="btn btn-secondary min-h-11" disabled={!!busy} onClick={() => setConfirm("reset")}>
              Reset usage
            </button>
            <button type="button" className="btn btn-danger min-h-11" disabled={!!busy} onClick={() => setConfirm("cancel")}>
              Cancelar
            </button>
          </div>
          {confirm && (
            <div className="panel mt-4 p-4" role="dialog" aria-labelledby="confirm-title">
              <p id="confirm-title" className="text-sm text-text">
                ¿Confirmas {confirm} para esta organización?
              </p>
              <div className="mt-3 flex gap-2">
                <button
                  type="button"
                  className="btn btn-primary min-h-11"
                  disabled={!!busy}
                  onClick={() => void run(confirm === "reset" ? "usage/reset" : confirm, confirm)}
                >
                  Confirmar
                </button>
                <button type="button" className="btn btn-secondary min-h-11" onClick={() => setConfirm("")}>
                  Volver
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
