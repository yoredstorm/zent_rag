import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api";
import { useAuth } from "../auth";

type Subscription = {
  plan_name: string | null;
  status: string;
  requests_used: number;
  requests_limit: number | null;
  trial_end: string | null;
};

type Usage = {
  totals: { requests: number; tokens: number; avg_latency_ms: number };
  daily: { day: string; requests: number; tokens: number; avg_latency_ms: number }[];
};

type LazyEvent = {
  tables: string[];
  rows_indexed: number;
  query_preview: string;
  at: string;
};

type LazyActivity = {
  trigger_count: number;
  recent: LazyEvent[];
};

export default function DashboardPage() {
  const { session } = useAuth();
  const [sub, setSub] = useState<Subscription | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [health, setHealth] = useState<string | null>(null);
  const [lazyActivity, setLazyActivity] = useState<LazyActivity | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const h = await fetch("/health");
        setHealth(h.ok ? "OK" : `HTTP ${h.status}`);
        const [subData, usageData, lazyData] = await Promise.all([
          api<Subscription>("/api/v1/billing/subscription", {
            token: session.token,
            tenantId: session.tenantId,
          }),
          api<Usage>("/api/v1/billing/usage?days=30", {
            token: session.token,
            tenantId: session.tenantId,
          }),
          api<LazyActivity>("/api/v1/ingestion/lazy-activity?days=30", {
            token: session.token,
            tenantId: session.tenantId,
          }).catch(() => ({ trigger_count: 0, recent: [] as LazyEvent[] })),
        ]);
        setSub(subData);
        setUsage(usageData);
        setLazyActivity(lazyData);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando dashboard");
      } finally {
        setLoading(false);
      }
    })();
  }, [session]);

  const limit = sub?.requests_limit ?? "—";
  const used = sub?.requests_used ?? 0;
  const daily = usage?.daily ?? [];

  return (
    <div>
      <h1>Dashboard</h1>
      <p className="muted">
        Bienvenido{session?.companyName ? `, ${session.companyName}` : ""}.
      </p>
      {error && <p className="error">{error}</p>}
      {loading && (
        <p className="muted">
          <span className="loading" aria-label="Cargando" /> Cargando…
        </p>
      )}
      {!loading && (
        <>
          <div className="grid" style={{ marginTop: "1.25rem" }}>
            <div className="stat">
              <div className="label">Plan</div>
              <div className="value">{sub?.plan_name || sub?.status || "—"}</div>
            </div>
            <div className="stat">
              <div className="label">Cuota del mes</div>
              <div className="value">
                {used}/{limit}
              </div>
            </div>
            <div className="stat">
              <div className="label">Estado del servicio</div>
              <div className="value">{health ?? "—"}</div>
            </div>
            <div className="stat">
              <div className="label">Trial hasta</div>
              <div className="value" style={{ fontSize: "1rem" }}>
                {sub?.trial_end ? new Date(sub.trial_end).toLocaleDateString() : "—"}
              </div>
            </div>
            <div className="stat">
              <div className="label">Indexados al vuelo (30d)</div>
              <div className="value">{lazyActivity?.trigger_count ?? 0}</div>
            </div>
          </div>

          <div className="panel">
            <h2>Consultas por día</h2>
            {daily.length === 0 ? (
              <p className="muted">Aún no hay consultas en los últimos 30 días.</p>
            ) : (
              <div className="chart-wrap">
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={daily}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                    <XAxis
                      dataKey="day"
                      tick={{ fill: "var(--text-muted)", fontSize: 11 }}
                      tickFormatter={(v: string) =>
                        typeof v === "string" && v.length >= 10 ? v.slice(5) : v
                      }
                    />
                    <YAxis
                      allowDecimals={false}
                      tick={{ fill: "var(--text-muted)", fontSize: 11 }}
                    />
                    <Tooltip
                      contentStyle={{
                        background: "var(--bg-elevated)",
                        border: "1px solid var(--border)",
                        borderRadius: 8,
                      }}
                    />
                    <Bar dataKey="requests" name="Consultas" fill="var(--accent)" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          <div className="panel">
            <h2>Siguiente paso</h2>
            <div className="row">
              <Link className="btn" to="/ingestion">
                Sincronizar datos
              </Link>
              <Link className="btn secondary" to="/chat">
                Hacer una pregunta
              </Link>
              <Link className="btn secondary" to="/keys">
                Ver clave de integración
              </Link>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
