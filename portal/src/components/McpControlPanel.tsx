import { ShieldCheck } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";

type ToolCfg = { enabled: boolean; min_role: string; rpm: number };
type UsageRow = { tool: string; calls: number; errors: number; error_rate_pct: number; avg_latency_ms: number; cost: number };
type AuditRow = { id: string; tool: string | null; status: string | null; latency_ms: number | null; created_at: string };

/** FASE 03 (S16): panel vivo del MCP — permisos por tool, uso y auditoría. */
export default function McpControlPanel() {
  const { session } = useAuth();
  const [config, setConfig] = useState<{ enabled: boolean; tools: Record<string, ToolCfg> } | null>(null);
  const [usage, setUsage] = useState<UsageRow[]>([]);
  const [audit, setAudit] = useState<AuditRow[]>([]);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  async function load() {
    if (!session) return;
    try {
      const [c, u, a] = await Promise.all([
        api<{ config: { enabled: boolean; tools: Record<string, ToolCfg> } }>("/api/v1/mcp/config", {
          token: session.token,
          organizationId: session.organizationId,
        }).catch(() => null),
        api<{ tools: UsageRow[] }>("/api/v1/mcp/usage", { token: session.token, organizationId: session.organizationId }).catch(() => ({ tools: [] })),
        api<{ entries: AuditRow[] }>("/api/v1/mcp/audit", { token: session.token, organizationId: session.organizationId }).catch(() => ({ entries: [] })),
      ]);
      if (c) setConfig(c.config);
      setUsage(u.tools || []);
      setAudit(a.entries || []);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error cargando MCP");
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function save() {
    if (!session || !config) return;
    setSaving(true);
    setErr("");
    setMsg("");
    try {
      await api("/api/v1/mcp/config", {
        method: "PUT",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify(config),
      });
      setMsg("Config MCP guardada.");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error guardando");
    } finally {
      setSaving(false);
    }
  }

  function patchTool(name: string, patch: Partial<ToolCfg>) {
    setConfig((c) => {
      if (!c) return c;
      const tools = { ...c.tools, [name]: { ...c.tools[name], ...patch } };
      return { ...c, tools };
    });
  }

  const tools = config?.tools || {};

  return (
    <section className="panel mt-4 p-5">
      <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
        <ShieldCheck size={15} aria-hidden /> MCP Control Plane
      </h2>
      <p className="mb-3 text-xs text-muted">
        Permisos y límites por herramienta (org). Toda ejecución queda auditada y atribuida a costo.
      </p>
      {msg && <p className="mb-2 text-xs text-ok" role="status">{msg}</p>}
      {err && <p className="mb-2 text-xs text-danger" role="alert">{err}</p>}
      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-xs font-semibold text-text">Permisos por tool</h3>
            <button type="button" className="btn btn-secondary min-h-8 text-xs" disabled={saving} onClick={() => void save()}>
              {saving ? "Guardando…" : "Guardar"}
            </button>
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>Tool</th>
                <th>Enabled</th>
                <th>Rol mínimo</th>
                <th>RPM</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(tools).map(([name, t]) => (
                <tr key={name}>
                  <td className="mono text-xs">{name}</td>
                  <td>
                    <input
                      type="checkbox"
                      checked={t.enabled}
                      onChange={(e) => patchTool(name, { enabled: e.target.checked })}
                    />
                  </td>
                  <td>
                    <select
                      className="rounded-md border border-border bg-soft px-1.5 py-1 text-xs"
                      value={t.min_role}
                      onChange={(e) => patchTool(name, { min_role: e.target.value })}
                    >
                      <option value="admin">admin</option>
                      <option value="customer">customer</option>
                    </select>
                  </td>
                  <td>
                    <input
                      type="number"
                      min={0}
                      max={1000}
                      className="w-20 rounded-md border border-border bg-soft px-2 py-1 text-xs"
                      value={t.rpm}
                      onChange={(e) => patchTool(name, { rpm: Number(e.target.value) })}
                    />
                  </td>
                </tr>
              ))}
              {Object.keys(tools).length === 0 && (
                <tr>
                  <td colSpan={4} className="p-3 text-center text-xs text-faint">Cargando configuración…</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div>
          <h3 className="mb-2 text-xs font-semibold text-text">Uso (30d)</h3>
          <table className="table">
            <thead>
              <tr>
                <th>Tool</th>
                <th>Llamadas</th>
                <th>Error %</th>
                <th>Lat media</th>
                <th>Costo</th>
              </tr>
            </thead>
            <tbody>
              {usage.map((u) => (
                <tr key={u.tool}>
                  <td className="mono text-xs">{u.tool}</td>
                  <td className="text-xs">{u.calls}</td>
                  <td className="text-xs">{u.error_rate_pct}%</td>
                  <td className="text-xs">{u.avg_latency_ms.toFixed(0)}ms</td>
                  <td className="text-xs">${u.cost.toFixed(4)}</td>
                </tr>
              ))}
              {usage.length === 0 && (
                <tr>
                  <td colSpan={5} className="p-3 text-center text-xs text-faint">Sin llamadas MCP.</td>
                </tr>
              )}
            </tbody>
          </table>
          <h3 className="mb-2 mt-4 text-xs font-semibold text-text">Auditoría reciente</h3>
          <div className="max-h-48 overflow-auto">
            {audit.map((a) => (
              <div key={a.id} className="flex items-center justify-between gap-2 rounded-md bg-soft px-2 py-1.5 text-[11px]">
                <span className="mono text-text">{a.tool ?? "tool"}</span>
                <span className={`badge ${a.status === "ok" ? "badge-ok" : "badge-danger"}`}>{a.status ?? "?"}</span>
                <span className="text-faint">{a.latency_ms != null ? `${a.latency_ms.toFixed(0)}ms` : "—"}</span>
                <span className="text-faint">{a.created_at?.slice(0, 16)}</span>
              </div>
            ))}
            {audit.length === 0 && <p className="py-2 text-center text-xs text-faint">Sin auditoría MCP.</p>}
          </div>
        </div>
      </div>
    </section>
  );
}