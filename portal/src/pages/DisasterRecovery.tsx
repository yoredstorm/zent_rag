import { CloudArrowDown, CloudArrowUp, Database, ShieldCheck, Timer, Warning } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorInline, PageHeader, SkeletonBlock } from "../components/ui";

type Policy = { id: string; name: string; scope: string; target_id: string | null; rpo_minutes: number; rto_minutes: number; replication_region: string; status: string; latest_backup_version: number; last_backup_at: string | null };
type Backup = { id: string; scope: string; source_id: string | null; version: number; artifact: Record<string, unknown>; status: string; created_at: string; restored_at: string | null; restored_to_region: string | null };
type Drill = { id: string; policy_id: string; policy_name: string; region: string; status: string; failover_ok: boolean | null; recovery_validated: boolean | null; duration_ms: number | null; detail: string | null; started_at: string };
type Availability = { policies_total: number; policies_active: number; drills_30d: number; drills_success: number; drill_success_rate: number; avg_drill_duration_ms: number; rpo_coverage: number; rpo_covered_policies: number; regions: { regions: { code: string; name: string; status: string }[] } };

const ST: Record<string, string> = { success: "badge-ok", failed: "badge-danger", running: "badge-warning", paused: "badge-warning", active: "badge-ok" };

export default function DisasterRecoveryPage() {
  const { session } = useAuth();
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [backups, setBackups] = useState<Backup[]>([]);
  const [drills, setDrills] = useState<Drill[]>([]);
  const [avail, setAvail] = useState<Availability | null>(null);
  const [draft, setDraft] = useState({ name: "", scope: "agent", rpo_minutes: 60, rto_minutes: 15, replication_region: "eu-west-1" });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [p, b, d, a] = await Promise.all([
        api<{ policies: Policy[] }>("/api/v1/dr/policies", { token: session.token, organizationId: session.organizationId }),
        api<{ backups: Backup[] }>("/api/v1/dr/backups", { token: session.token, organizationId: session.organizationId }),
        api<{ drills: Drill[] }>("/api/v1/dr/drills", { token: session.token, organizationId: session.organizationId }),
        api<Availability>("/api/v1/dr/availability", { token: session.token, organizationId: session.organizationId }),
      ]);
      setPolicies(p.policies || []);
      setBackups(b.backups || []);
      setDrills(d.drills || []);
      setAvail(a);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 15000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function createPolicy() {
    if (!session || !draft.name) return;
    setBusy("create");
    setError("");
    try {
      const out = await api<{ policy_id: string }>("/api/v1/dr/policies", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify(draft),
      });
      setError(`Política creada: ${out.policy_id.slice(0, 8)}…`);
      setDraft({ name: "", scope: "agent", rpo_minutes: 60, rto_minutes: 15, replication_region: "eu-west-1" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function backup(policy: Policy) {
    if (!session) return;
    setBusy(`bk-${policy.id.slice(0, 6)}`);
    setError("");
    try {
      const out = await api<{ backup_id: string; version: number }>("/api/v1/dr/backups", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ scope: policy.scope, source_id: policy.target_id }),
      });
      setError(`Backup v${out.version} creado`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function restore(backupId: string) {
    if (!session) return;
    setBusy(`rs-${backupId.slice(0, 6)}`);
    setError("");
    try {
      const out = await api<Record<string, unknown>>(`/api/v1/dr/backups/${backupId}/restore`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ region: "us-east-1" }),
      });
      setError(`Restaurado: ${JSON.stringify(out).slice(0, 120)}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function drill(policyId: string) {
    if (!session) return;
    setBusy(`dl-${policyId.slice(0, 6)}`);
    setError("");
    try {
      const out = await api<{ status: string; failover_ok: boolean; recovery_validated: boolean; detail: string }>("/api/v1/dr/drills", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ policy_id: policyId }),
      });
      setError(`Drill ${out.status}: failover ${out.failover_ok} · recovery ${out.recovery_validated} — ${out.detail}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function act(policyId: string, action: "pause" | "resume") {
    if (!session) return;
    setBusy(`${action}-${policyId.slice(0, 6)}`);
    await api(`/api/v1/dr/policies/${policyId}/${action}`, { method: "POST", token: session.token, organizationId: session.organizationId });
    setBusy("");
    await load();
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Disaster Recovery" subtitle="Políticas RPO/RTO, backups versionados con restore y drills de failover multi-región." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-64" />
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <section className="panel p-4">
            <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><ShieldCheck size={14} /> Nueva política</h2>
            <div className="grid grid-cols-1 gap-2">
              <input className="rounded-md border border-border bg-soft px-2 py-2 text-sm" placeholder="nombre…" value={draft.name} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} />
              <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={draft.scope} onChange={(e) => setDraft((d) => ({ ...d, scope: e.target.value }))}>
                {["agent", "knowledge", "full"].map((s) => (<option key={s} value={s}>{s}</option>))}
              </select>
              <div className="flex gap-2">
                <input type="number" className="rounded-md border border-border bg-soft px-2 py-2 text-xs" placeholder="RPO min" value={draft.rpo_minutes} onChange={(e) => setDraft((d) => ({ ...d, rpo_minutes: Number(e.target.value) }))} />
                <input type="number" className="rounded-md border border-border bg-soft px-2 py-2 text-xs" placeholder="RTO min" value={draft.rto_minutes} onChange={(e) => setDraft((d) => ({ ...d, rto_minutes: Number(e.target.value) }))} />
              </div>
              <input className="rounded-md border border-border bg-soft px-2 py-2 text-xs" placeholder="región réplica…" value={draft.replication_region} onChange={(e) => setDraft((d) => ({ ...d, replication_region: e.target.value }))} />
              <button type="button" className="btn btn-primary min-h-9 text-xs" disabled={!!busy || !draft.name} onClick={() => void createPolicy()}>Crear</button>
            </div>
            <h3 className="mb-2 mt-4 text-sm font-semibold text-text">Políticas ({policies.length})</h3>
            <div className="space-y-1">
              {policies.map((p) => (
                <div key={p.id} className="rounded-md bg-soft px-3 py-2 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="flex-1 font-medium text-text">{p.name}</span>
                    <span className={`badge ${ST[p.status] ?? "badge-muted"}`}>{p.status}</span>
                  </div>
                  <p className="mt-0.5 text-[10px] text-faint">{p.scope} · RPO {p.rpo_minutes}m · RTO {p.rto_minutes}m · → {p.replication_region} · backups v{p.latest_backup_version}</p>
                  <div className="mt-1 flex gap-1">
                    <button type="button" className="btn btn-ghost min-h-6 px-2 text-[10px]" disabled={!!busy} onClick={() => void backup(p)}><CloudArrowUp size={10} /> Backup</button>
                    <button type="button" className="btn btn-ghost min-h-6 px-2 text-[10px]" disabled={!!busy} onClick={() => void drill(p.id)}><Warning size={10} /> Drill</button>
                    {p.status === "active" ? (
                      <button type="button" className="btn btn-ghost min-h-6 px-2 text-[10px]" disabled={!!busy} onClick={() => void act(p.id, "pause")}>Pausar</button>
                    ) : (
                      <button type="button" className="btn btn-ghost min-h-6 px-2 text-[10px]" disabled={!!busy} onClick={() => void act(p.id, "resume")}>Reanudar</button>
                    )}
                  </div>
                </div>
              ))}
              {policies.length === 0 && <p className="text-xs text-faint">Sin políticas. Crea una para empezar.</p>}
            </div>
          </section>

          <section className="lg:col-span-2">
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <div className="panel p-4"><p className="text-2xl font-bold text-text">{avail?.drills_30d ?? 0}</p><p className="text-xs text-faint">Drills 30d · {avail?.drill_success_rate ?? 0}% éxito</p></div>
              <div className="panel p-4"><p className="text-2xl font-bold text-text">{avail?.rpo_coverage ?? 0}%</p><p className="text-xs text-faint">Cobertura RPO ({avail?.rpo_covered_policies ?? 0} políticas)</p></div>
              <div className="panel p-4"><p className="text-2xl font-bold text-text">{avail?.avg_drill_duration_ms ?? 0}ms</p><p className="text-xs text-faint">Duración media drill</p></div>
              <div className="panel p-4"><p className="text-2xl font-bold text-text">{avail?.policies_active ?? 0}/{avail?.policies_total ?? 0}</p><p className="text-xs text-faint">Políticas activas</p></div>
            </div>

            <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
              <div className="panel p-4">
                <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><Database size={14} /> Backups ({backups.length})</h3>
                <div className="space-y-1">
                  {backups.slice(0, 8).map((b) => (
                    <div key={b.id} className="rounded-md bg-soft px-3 py-1.5 text-[11px]">
                      <div className="flex items-center gap-2">
                        <span className="badge badge-muted">v{b.version}</span>
                        <span className="flex-1 text-text">{b.scope}</span>
                        <span className={`badge ${ST[b.status] ?? "badge-muted"}`}>{b.status}</span>
                        {b.restored_to_region && <span className="text-[10px] text-faint">→ {b.restored_to_region}</span>}
                        {b.status !== "restored" && (
                          <button type="button" className="btn btn-ghost min-h-6 px-2 text-[10px]" disabled={!!busy} onClick={() => void restore(b.id)}><CloudArrowDown size={10} /> Restaurar</button>
                        )}
                      </div>
                      <p className="truncate text-[10px] text-faint">{JSON.stringify(b.artifact).slice(0, 90)}</p>
                    </div>
                  ))}
                  {backups.length === 0 && <p className="text-xs text-faint">Sin backups. Crea uno desde una política.</p>}
                </div>
              </div>

              <div className="panel p-4">
                <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><Timer size={14} /> Drills recientes ({drills.length})</h3>
                <div className="space-y-1">
                  {drills.slice(0, 8).map((d) => (
                    <div key={d.id} className="rounded-md bg-soft px-3 py-1.5 text-[11px]">
                      <div className="flex items-center gap-2">
                        <span className={`badge ${ST[d.status] ?? "badge-muted"}`}>{d.status}</span>
                        <span className="flex-1 text-text">{d.policy_name}</span>
                        <span className="text-faint">{d.region} · {d.duration_ms}ms</span>
                      </div>
                      {d.detail && <p className="truncate text-[10px] text-faint">{d.detail}</p>}
                      <p className="text-[10px] text-faint">failover {String(d.failover_ok)} · recovery {String(d.recovery_validated)}</p>
                    </div>
                  ))}
                  {drills.length === 0 && <p className="text-xs text-faint">Sin drills. Ejecuta uno desde una política.</p>}
                </div>
                <h4 className="mb-1 mt-3 text-xs font-semibold text-text">Regiones</h4>
                <div className="flex flex-wrap gap-1">
                  {(avail?.regions?.regions ?? []).map((r) => (
                    <span key={r.code} className={`badge ${r.status === "healthy" || r.status === "active" ? "badge-ok" : "badge-danger"}`}>{r.code}</span>
                  ))}
                </div>
              </div>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}