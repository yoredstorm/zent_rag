import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

type Subscription = {
  plan_name: string | null;
  status: string;
  requests_used: number;
  requests_limit: number | null;
  trial_end: string | null;
};

export default function DashboardPage() {
  const { session } = useAuth();
  const [sub, setSub] = useState<Subscription | null>(null);
  const [health, setHealth] = useState<string>("…");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    (async () => {
      try {
        const h = await fetch("/health");
        setHealth(h.ok ? "OK" : `HTTP ${h.status}`);
        const data = await api<Subscription>("/api/v1/billing/subscription", {
          token: session.token,
          tenantId: session.tenantId,
        });
        setSub(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando dashboard");
      }
    })();
  }, [session]);

  const limit = sub?.requests_limit ?? "—";
  const used = sub?.requests_used ?? 0;

  return (
    <div>
      <h1>Dashboard</h1>
      <p className="muted">
        Bienvenido{session?.companyName ? `, ${session.companyName}` : ""}.
      </p>
      {error && <p className="error">{error}</p>}
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
          <div className="label">API health</div>
          <div className="value">{health}</div>
        </div>
        <div className="stat">
          <div className="label">Trial hasta</div>
          <div className="value" style={{ fontSize: "1rem" }}>
            {sub?.trial_end ? new Date(sub.trial_end).toLocaleDateString() : "—"}
          </div>
        </div>
      </div>
      <div className="panel">
        <h2>Siguiente paso</h2>
        <div className="row">
          <Link className="btn" to="/ingestion">
            Sincronizar datos
          </Link>
          <Link className="btn secondary" to="/chat">
            Probar chat
          </Link>
          <Link className="btn secondary" to="/keys">
            Ver API key
          </Link>
        </div>
      </div>
    </div>
  );
}
