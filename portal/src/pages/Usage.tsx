import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";

type Usage = {
  totals: { requests: number; tokens: number; avg_latency_ms: number };
  daily: { day: string; requests: number; tokens: number; avg_latency_ms: number }[];
  recent: { id: number; total_tokens: number; latency_ms: number; model: string | null; created_at: string }[];
};

export default function UsagePage() {
  const { session } = useAuth();
  const [usage, setUsage] = useState<Usage | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    api<Usage>("/api/v1/billing/usage?days=30", {
      token: session.token,
      tenantId: session.tenantId,
    })
      .then(setUsage)
      .catch((err) => setError(err instanceof Error ? err.message : "Error"));
  }, [session]);

  return (
    <div>
      <h1>Uso</h1>
      <p className="muted">Últimos 30 días desde usage_logs.</p>
      {error && <p className="error">{error}</p>}
      {usage && (
        <>
          <div className="grid" style={{ marginTop: "1rem" }}>
            <div className="stat">
              <div className="label">Requests</div>
              <div className="value">{usage.totals.requests}</div>
            </div>
            <div className="stat">
              <div className="label">Tokens</div>
              <div className="value">{usage.totals.tokens}</div>
            </div>
            <div className="stat">
              <div className="label">Latencia media</div>
              <div className="value">{Math.round(usage.totals.avg_latency_ms)} ms</div>
            </div>
          </div>
          <div className="panel">
            <h2>Por día</h2>
            <table className="table">
              <thead>
                <tr>
                  <th>Día</th>
                  <th>Requests</th>
                  <th>Tokens</th>
                  <th>Latencia</th>
                </tr>
              </thead>
              <tbody>
                {usage.daily.map((d) => (
                  <tr key={d.day}>
                    <td>{d.day}</td>
                    <td>{d.requests}</td>
                    <td>{d.tokens}</td>
                    <td>{Math.round(d.avg_latency_ms)} ms</td>
                  </tr>
                ))}
                {usage.daily.length === 0 && (
                  <tr>
                    <td colSpan={4} className="muted">
                      Sin datos aún
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="panel">
            <h2>Recientes</h2>
            <table className="table">
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th>Tokens</th>
                  <th>Latencia</th>
                  <th>Modelo</th>
                </tr>
              </thead>
              <tbody>
                {usage.recent.map((r) => (
                  <tr key={r.id}>
                    <td>{new Date(r.created_at).toLocaleString()}</td>
                    <td>{r.total_tokens}</td>
                    <td>{Math.round(r.latency_ms)} ms</td>
                    <td className="mono">{r.model || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
