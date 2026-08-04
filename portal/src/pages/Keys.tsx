import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";

type TokenInfo = {
  prefix: string;
  name: string;
  last_used_at: string | null;
  created_at: string;
};

export default function KeysPage() {
  const { session } = useAuth();
  const [info, setInfo] = useState<TokenInfo | null>(null);
  const [newToken, setNewToken] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (!session) return;
    setLoading(true);
    api<TokenInfo>("/api/v1/billing/token", {
      token: session.token,
      tenantId: session.tenantId,
    })
      .then(setInfo)
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoading(false));
  }, [session]);

  async function rotate() {
    if (!session) return;
    setError("");
    setMsg("");
    try {
      const data = await api<{ token: string }>("/api/v1/billing/token/rotate", {
        method: "POST",
        token: session.token,
        tenantId: session.tenantId,
      });
      setNewToken(data.token);
      setMsg(
        "Clave rotada. Guárdala ahora — no se vuelve a mostrar. Tu sesión del portal no cambia."
      );
      const refreshed = await api<TokenInfo>("/api/v1/billing/token", {
        token: session.token,
        tenantId: session.tenantId,
      });
      setInfo(refreshed);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al rotar");
    }
  }

  return (
    <div>
      <h1>Claves de integración</h1>
      <p className="muted">
        Usa esta clave en tus sistemas externos. El portal ya te autentica con tu
        cuenta — no hace falta pegarla aquí.
      </p>
      {error && <p className="error">{error}</p>}
      {msg && <p className="success">{msg}</p>}
      <div className="panel">
        <h2>Clave actual</h2>
        {loading && (
          <p className="muted">
            <span className="loading" aria-label="Cargando" /> Cargando…
          </p>
        )}
        {!loading && info && (
          <table className="table">
            <tbody>
              <tr>
                <th>Prefijo</th>
                <td className="mono">{info.prefix}</td>
              </tr>
              <tr>
                <th>Nombre</th>
                <td>{info.name}</td>
              </tr>
              <tr>
                <th>Creado</th>
                <td>{new Date(info.created_at).toLocaleString()}</td>
              </tr>
              <tr>
                <th>Último uso</th>
                <td>
                  {info.last_used_at
                    ? new Date(info.last_used_at).toLocaleString()
                    : "—"}
                </td>
              </tr>
              <tr>
                <th>Organización</th>
                <td className="mono">{session?.tenantId}</td>
              </tr>
            </tbody>
          </table>
        )}
        {!loading && !info && !error && (
          <p className="muted">No hay clave disponible.</p>
        )}
        <div className="row" style={{ marginTop: "1rem" }}>
          <button className="btn danger" type="button" onClick={rotate} disabled={loading}>
            Rotar clave
          </button>
        </div>
        {newToken && (
          <div className="field" style={{ marginTop: "1rem" }}>
            <label>Nueva clave (cópiala ahora)</label>
            <input className="mono" readOnly value={newToken} />
          </div>
        )}
      </div>
    </div>
  );
}
