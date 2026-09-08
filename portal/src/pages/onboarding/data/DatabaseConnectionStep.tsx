import { useState } from "react";

const ENGINES = [
  { id: "postgres", label: "PostgreSQL", port: 5432 },
  { id: "mysql", label: "MySQL", port: 3306 },
  { id: "mssql", label: "SQL Server", port: 1433 },
  { id: "oracle", label: "Oracle", port: 1521 },
  { id: "db2", label: "DB2", port: 50000 },
];

export function DatabaseConnectionStep({
  onSubmit,
  busy,
  result,
}: {
  onSubmit: (body: Record<string, unknown>) => void;
  busy: boolean;
  result?: {
    ok?: boolean;
    latency_ms?: number;
    server_version?: string | null;
    tables?: number;
    columns?: number;
    message?: string;
  };
}) {
  const [engine, setEngine] = useState("postgres");
  const [name, setName] = useState("Base empresarial");
  const [host, setHost] = useState("");
  const [port, setPort] = useState(5432);
  const [database, setDatabase] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [ssl, setSsl] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [allowlist, setAllowlist] = useState("");
  const [schemas, setSchemas] = useState("");
  const [timeoutSec, setTimeoutSec] = useState("");

  return (
    <form
      className="max-w-xl space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({
          name,
          engine,
          host,
          port,
          database,
          username,
          password,
          ssl,
          advanced: {
            ssrf_allowlist: allowlist
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean),
            allowed_schemas: schemas
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean),
            timeout: timeoutSec ? Number(timeoutSec) : undefined,
          },
        });
      }}
    >
      <h2 className="text-lg font-semibold text-text">Conecta tu base de datos</h2>
      <p className="text-sm text-muted">
        La contraseña se guarda en el Vault. Nunca aparece en la configuración.
      </p>
      <div className="flex flex-wrap gap-2">
        {ENGINES.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`btn ${engine === item.id ? "btn-primary" : "btn-secondary"}`}
            onClick={() => {
              setEngine(item.id);
              setPort(item.port);
            }}
          >
            {item.label}
          </button>
        ))}
      </div>
      <label className="block text-sm">
        Nombre
        <input className="input mt-1 w-full" value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="block text-sm">
        Host
        <input className="input mt-1 w-full" value={host} onChange={(e) => setHost(e.target.value)} required />
      </label>
      <label className="block text-sm">
        Puerto
        <input
          className="input mt-1 w-full"
          type="number"
          value={port}
          onChange={(e) => setPort(Number(e.target.value))}
        />
      </label>
      <label className="block text-sm">
        Base
        <input className="input mt-1 w-full" value={database} onChange={(e) => setDatabase(e.target.value)} required />
      </label>
      <label className="block text-sm">
        Usuario
        <input className="input mt-1 w-full" value={username} onChange={(e) => setUsername(e.target.value)} required />
      </label>
      <label className="block text-sm">
        Contraseña
        <input
          className="input mt-1 w-full"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          autoComplete="off"
        />
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={ssl} onChange={(e) => setSsl(e.target.checked)} />
        SSL
      </label>
      <button type="button" className="text-xs text-accent" onClick={() => setAdvanced((v) => !v)}>
        {advanced ? "Ocultar avanzado" : "Advanced Settings"}
      </button>
      {advanced && (
        <>
          <label className="block text-sm">
            Hosts permitidos (SSRF)
            <input
              className="input mt-1 w-full"
              placeholder="localhost, 10.0.0.4"
              value={allowlist}
              onChange={(e) => setAllowlist(e.target.value)}
            />
          </label>
          <label className="block text-sm">
            Esquemas permitidos
            <input
              className="input mt-1 w-full"
              placeholder="public, ventas"
              value={schemas}
              onChange={(e) => setSchemas(e.target.value)}
            />
          </label>
          <label className="block text-sm">
            Timeout (segundos)
            <input
              className="input mt-1 w-full"
              type="number"
              value={timeoutSec}
              onChange={(e) => setTimeoutSec(e.target.value)}
            />
          </label>
        </>
      )}
      <button type="submit" className="btn btn-primary" disabled={busy}>
        {busy ? "Probando…" : "Probar conexión"}
      </button>
      {result && (
        <div className="panel p-4 text-sm">
          <p className="font-medium">{result.ok ? "Conexión correcta" : "No se pudo conectar"}</p>
          {result.server_version && <p className="mt-1 text-muted">Base: {result.server_version}</p>}
          {result.latency_ms != null && <p className="text-muted">Latencia: {Math.round(result.latency_ms)} ms</p>}
          {result.tables != null && (
            <p className="text-muted">
              Detectado: {result.tables} tablas, {result.columns} columnas
            </p>
          )}
          {result.message && !result.ok && <p className="text-danger">{result.message}</p>}
        </div>
      )}
    </form>
  );
}
