import { useState } from "react";

export function ApiStep({
  onSubmit,
  busy,
  result,
}: {
  onSubmit: (body: Record<string, unknown>) => void;
  busy: boolean;
  result?: { ok?: boolean; latency_ms?: number; message?: string };
}) {
  const [name, setName] = useState("API");
  const [baseUrl, setBaseUrl] = useState("");
  const [auth, setAuth] = useState("none");
  const [token, setToken] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [itemsPath, setItemsPath] = useState("data");

  return (
    <form
      className="max-w-xl space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({
          name,
          base_url: baseUrl,
          auth,
          token: token || undefined,
          username: username || undefined,
          password: password || undefined,
          items_path: itemsPath.split(".").filter(Boolean),
        });
      }}
    >
      <h2 className="text-lg font-semibold text-text">Conecta una API</h2>
      <label className="block text-sm">
        Nombre
        <input className="input mt-1 w-full" value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="block text-sm">
        URL base
        <input className="input mt-1 w-full" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} required />
      </label>
      <label className="block text-sm">
        Autenticación
        <select className="input mt-1 w-full" value={auth} onChange={(e) => setAuth(e.target.value)}>
          <option value="none">Ninguna</option>
          <option value="bearer">Bearer Token</option>
          <option value="api_key">API Key</option>
          <option value="basic">Basic Auth</option>
        </select>
      </label>
      {(auth === "bearer" || auth === "api_key") && (
        <label className="block text-sm">
          Token
          <input className="input mt-1 w-full" type="password" value={token} onChange={(e) => setToken(e.target.value)} />
        </label>
      )}
      {auth === "basic" && (
        <>
          <label className="block text-sm">
            Usuario
            <input className="input mt-1 w-full" value={username} onChange={(e) => setUsername(e.target.value)} />
          </label>
          <label className="block text-sm">
            Contraseña
            <input className="input mt-1 w-full" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
        </>
      )}
      <button type="button" className="text-xs text-accent" onClick={() => setAdvanced((v) => !v)}>
        Advanced Settings
      </button>
      {advanced && (
        <label className="block text-sm">
          Ruta de ítems
          <input className="input mt-1 w-full" value={itemsPath} onChange={(e) => setItemsPath(e.target.value)} />
        </label>
      )}
      <button type="submit" className="btn btn-primary" disabled={busy}>
        {busy ? "Probando…" : "Probar conexión"}
      </button>
      {result && (
        <p className="text-sm">
          {result.ok ? "Conexión correcta" : result.message || "Error"}
          {result.latency_ms != null ? ` · ${Math.round(result.latency_ms)} ms` : ""}
        </p>
      )}
    </form>
  );
}
