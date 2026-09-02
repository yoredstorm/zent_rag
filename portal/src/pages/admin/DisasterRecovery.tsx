import { Archive, CloudArrowDown, Gauge, Lifebuoy } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Backup = {
  id: string;
  organization_id: string;
  status: string;
  trigger: string;
  size_bytes: number | null;
  checksum_sha256: string | null;
  duration_ms: number | null;
  qdrant_snapshot: boolean;
  error: string | null;
  created_at: string;
};

type Readiness = {
  organization_id: string;
  score: number;
  rpo_minutes: number;
  backup_enabled: boolean;
  regions: string[];
  components: { name: string; ok: boolean; detail: string }[];
};

function fmtBytes(b: number | null) {
  if (b == null) return "—";
  if (b > 1024 * 1024 * 1024) return `${(b / 1024 ** 3).toFixed(2)} GB`;
  if (b > 1024 * 1024) return `${(b / 1024 ** 2).toFixed(1)} MB`;
  if (b > 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${b} B`;
}

export default function AdminDisasterRecoveryPage() {
  const { session } = usePlatformAuth();
  const [backups, setBackups] = useState<Backup[]>([]);
  const [readiness, setReadiness] = useState<Readiness[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [orgId, setOrgId] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [b, r] = await Promise.all([
        platformApi<{ backups: Backup[] }>("/api/v1/platform/dr/backups", {
          token: session.token,
        }),
        platformApi<{ organizations: Readiness[] }>(
          "/api/v1/platform/dr/readiness",
          { token: session.token }
        ),
      ]);
      setBackups(b.backups || []);
      setReadiness(r.organizations || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function backupNow(oid: string) {
    if (!session) return;
    setBusy(oid);
    setError("");
    try {
      const out = await platformApi<{ status: string; id: string }>(
        `/api/v1/platform/dr/organizations/${oid}/backup`,
        { method: "POST", token: session.token, body: "{}" }
      );
      setError(`Backup ${out.status} (${out.id.slice(0, 8)}…)`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function drill(backupId: string) {
    if (!session) return;
    setBusy(backupId);
    setError("");
    try {
      const out = await platformApi<{ status: string; tables: number; error?: string }>(
        `/api/v1/platform/dr/backups/${backupId}/drill`,
        { method: "POST", token: session.token, body: "{}" }
      );
      setError(
        out.status === "ok"
          ? `DR drill OK: standby con ${out.tables} tablas.`
          : `DR drill falló: ${out.error ?? ""}`
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Disaster Recovery"
        subtitle="Backups pg_dump + Qdrant, DR drills no destructivos y readiness por tenant."
        actions={
          <button type="button" className="btn btn-primary min-h-11" onClick={() => void load()}>
            <CloudArrowDown size={15} aria-hidden /> Refrescar
          </button>
        }
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <Lifebuoy size={15} aria-hidden /> Readiness por tenant
            </h3>
            <div className="panel grid grid-cols-1 gap-3 lg:grid-cols-2">
              {readiness.map((r) => (
                <div key={r.organization_id} className="rounded-md border border-border p-3">
                  <div className="flex items-center justify-between">
                    <p className="mono text-xs text-faint">{r.organization_id.slice(0, 13)}…</p>
                    <span
                      className={`badge ${
                        r.score >= 80 ? "badge-ok" : r.score >= 50 ? "badge-pending" : "badge-danger"
                      }`}
                    >
                      {r.score}/100
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-muted">
                    RPO {r.rpo_minutes}m · backups {r.backup_enabled ? "ON" : "OFF"} ·{" "}
                    {r.regions.length ? r.regions.join(", ") : "sin regiones"}
                  </p>
                  <ul className="mt-2 space-y-1">
                    {r.components.map((c) => (
                      <li key={c.name} className="flex items-center justify-between text-xs">
                        <span className="text-muted">{c.name}</span>
                        <span className="flex items-center gap-1 text-faint">
                          {c.detail}
                          <Gauge
                            size={12}
                            className={c.ok ? "text-success" : "text-danger"}
                            aria-hidden
                          />
                        </span>
                      </li>
                    ))}
                  </ul>
                  <button
                    type="button"
                    className="btn btn-secondary mt-3 min-h-9 w-full text-xs"
                    disabled={!!busy}
                    onClick={() => void backupNow(r.organization_id)}
                  >
                    <Archive size={13} aria-hidden />
                    {busy === r.organization_id ? "Respaldando…" : "Backup ahora"}
                  </button>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h3 className="mb-2 text-sm font-semibold text-text">Backups ({backups.length})</h3>
            <div className="panel overflow-x-auto">
              {backups.length === 0 ? (
                <EmptyState
                  icon={Archive}
                  title="Sin backups"
                  body="Ejecuta un backup manual o habilita el perfil DR del tenant."
                />
              ) : (
                <table className="table">
                  <thead>
                    <tr>
                      <th>Creado</th>
                      <th>Org</th>
                      <th>Trigger</th>
                      <th>Estado</th>
                      <th>Tamaño</th>
                      <th>Qdrant</th>
                      <th>Checksum</th>
                      <th className="text-right">Acciones</th>
                    </tr>
                  </thead>
                  <tbody>
                    {backups.map((b) => (
                      <tr key={b.id}>
                        <td className="text-xs text-muted">
                          {new Date(b.created_at).toLocaleString("es-PE")}
                        </td>
                        <td className="mono text-xs text-faint">{b.organization_id.slice(0, 8)}</td>
                        <td className="text-xs">{b.trigger}</td>
                        <td>
                          <span
                            className={`badge ${
                              b.status === "completed" ? "badge-ok" : "badge-danger"
                            }`}
                          >
                            {b.status}
                          </span>
                        </td>
                        <td className="text-xs">{fmtBytes(b.size_bytes)}</td>
                        <td className="text-xs">
                          {b.qdrant_snapshot ? (
                            <span className="badge badge-ok">snapshot</span>
                          ) : (
                            <span className="badge badge-muted">no</span>
                          )}
                        </td>
                        <td className="mono text-[10px] text-faint">
                          {b.checksum_sha256 ? b.checksum_sha256.slice(0, 12) : "—"}
                        </td>
                        <td className="text-right">
                          {b.status === "completed" && (
                            <button
                              type="button"
                              className="btn btn-ghost min-h-9 px-2 py-1.5 text-xs"
                              disabled={!!busy}
                              onClick={() => void drill(b.id)}
                              title="Restaurar a standby DB (no destructivo)"
                            >
                              <Lifebuoy size={13} aria-hidden />
                              Drill
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}