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
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (!session) return;
    api<TokenInfo>("/api/v1/billing/token", {
      token: session.token,
      tenantId: session.tenantId,
    })
      .then(setInfo)
      .catch((err) => setError(err instanceof Error ? err.message : "Error"));
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
        "API token rotado. Guárdalo ahora — no se vuelve a mostrar. Tu sesión del portal no cambia."
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
      <h1>API Keys</h1>
      <p className="muted">
        Token <code>rag_live_…</code> para integraciones. El portal usa tu sesión
        cifrada (no pegues este token en el login).
      </p>
      {error && <p className="error">{error}</p>}
      {msg && <p className="success">{msg}</p>}
      <div className="panel">
        <h2>Token actual</h2>
        {info ? (
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
                <th>Tenant</th>
                <td className="mono">{session?.tenantId}</td>
              </tr>
            </tbody>
          </table>
        ) : (
          <p className="muted">Cargando…</p>
        )}
        <div className="row" style={{ marginTop: "1rem" }}>
          <button className="btn danger" type="button" onClick={rotate}>
            Rotar token
          </button>
        </div>
        {newToken && (
          <div className="field" style={{ marginTop: "1rem" }}>
            <label>Nuevo token (cópialo)</label>
            <input className="mono" readOnly value={newToken} />
          </div>
        )}
      </div>
    </div>
  );
}
