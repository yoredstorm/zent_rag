import { GitBranch, Play, CaretRight, ArrowCounterClockwise } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorInline, PageHeader, SkeletonBlock } from "../components/ui";

type Version = { id: string; version_number: number; status: string; notes: string | null; created_at: string };
type Release = { id: string; agent_id: string; version_id: string; version_number: number; channel: string; traffic_pct: number; status: string; health_score: number | null; created_at: string; events?: { id: string; event_type: string; detail: string; created_at: string }[] };
type Diff = { version_a: { number: number }; version_b: { number: number }; config_diff: { key: string; kind: string; a: unknown; b: unknown }[]; prompt_diff: { changed: boolean; a_chars: number; b_chars: number }; model_changed: boolean; tools_changed: boolean };

export default function ReleasesPage() {
  const { session } = useAuth();
  const [releases, setReleases] = useState<Release[]>([]);
  const [agents, setAgents] = useState<{ id: string; name: string }[]>([]);
  const [agentId, setAgentId] = useState("");
  const [versions, setVersions] = useState<Version[]>([]);
  const [startForm, setStartForm] = useState({ version_id: "", channel: "canary", traffic_pct: 50 });
  const [diff, setDiff] = useState<Diff | null>(null);
  const [diffPair, setDiffPair] = useState({ a: "", b: "" });
  const [detail, setDetail] = useState<Release | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [r, a] = await Promise.all([
        api<{ releases: Release[] }>("/api/v1/releases", { token: session.token, organizationId: session.organizationId }),
        api<{ agents: { id: string; name: string }[] }>("/api/v1/agents", { token: session.token, organizationId: session.organizationId }).catch(() => ({ agents: [] })),
      ]);
      setReleases(r.releases || []);
      setAgents(a.agents || []);
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

  async function loadVersions(aid: string) {
    if (!session) return;
    const v = await api<{ versions: Version[] }>(`/api/v1/releases/versions/${aid}`, { token: session.token, organizationId: session.organizationId });
    setVersions(v.versions || []);
  }

  async function start() {
    if (!session || !agentId) return;
    setBusy("start");
    setError("");
    try {
      const out = await api<{ release_id: string }>("/api/v1/releases/start", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ agent_id: agentId, ...startForm }),
      });
      setError(`Release ${out.release_id.slice(0, 8)}… iniciado.`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function act(releaseId: string, action: "health" | "promote" | "rollback" | "pause" | "resume") {
    if (!session) return;
    setBusy(`${action}-${releaseId.slice(0, 6)}`);
    setError("");
    try {
      const out = await api<Record<string, unknown>>(`/api/v1/releases/${releaseId}/${action}`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      setError(`${action}: ${JSON.stringify(out).slice(0, 120)}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function showDetail(releaseId: string) {
    if (!session) return;
    const d = await api<Release>(`/api/v1/releases/${releaseId}`, { token: session.token, organizationId: session.organizationId });
    setDetail(d);
  }

  async function showDiff() {
    if (!session || !agentId || !diffPair.a || !diffPair.b) return;
    setError("");
    try {
      const d = await api<Diff>(`/api/v1/releases/diff/${agentId}?a=${diffPair.a}&b=${diffPair.b}`, { token: session.token, organizationId: session.organizationId });
      setDiff(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  return (
    <div>
      <PageHeader title="Versiones & Releases" subtitle="Canales canary/stable, health-gate y diff entre versiones." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <section className="panel p-4">
            <h2 className="mb-2 text-sm font-semibold text-text">Nuevo release</h2>
            <div className="grid grid-cols-1 gap-2">
              <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={agentId} onChange={(e) => { setAgentId(e.target.value); void loadVersions(e.target.value); }}>
                <option value="">agente…</option>
                {agents.map((a) => (<option key={a.id} value={a.id}>{a.name}</option>))}
              </select>
              <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={startForm.version_id} onChange={(e) => setStartForm((f) => ({ ...f, version_id: e.target.value }))}>
                <option value="">versión…</option>
                {versions.map((v) => (<option key={v.id} value={v.id}>v{v.version_number} ({v.status})</option>))}
              </select>
              <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={startForm.channel} onChange={(e) => setStartForm((f) => ({ ...f, channel: e.target.value }))}>
                {["canary", "stable"].map((ch) => (<option key={ch} value={ch}>{ch}</option>))}
              </select>
              <input type="number" className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={startForm.traffic_pct} onChange={(e) => setStartForm((f) => ({ ...f, traffic_pct: Number(e.target.value) }))} />
              <button type="button" className="btn btn-primary min-h-9 text-xs" disabled={!!busy || !agentId || !startForm.version_id} onClick={() => void start()}>
                <Play size={13} /> Iniciar release
              </button>
            </div>

            <h3 className="mb-2 mt-4 text-sm font-semibold text-text">Diff de versiones</h3>
            <div className="grid grid-cols-2 gap-2">
              <select className="rounded-md border border-border bg-soft px-2 py-2 text-xs" value={diffPair.a} onChange={(e) => setDiffPair((p) => ({ ...p, a: e.target.value }))}>
                <option value="">A…</option>
                {versions.map((v) => (<option key={v.id} value={v.id}>v{v.version_number}</option>))}
              </select>
              <select className="rounded-md border border-border bg-soft px-2 py-2 text-xs" value={diffPair.b} onChange={(e) => setDiffPair((p) => ({ ...p, b: e.target.value }))}>
                <option value="">B…</option>
                {versions.map((v) => (<option key={v.id} value={v.id}>v{v.version_number}</option>))}
              </select>
            </div>
            <button type="button" className="btn btn-secondary mt-2 min-h-8 text-xs" disabled={!diffPair.a || !diffPair.b} onClick={() => void showDiff()}>
              <GitBranch size={12} /> Comparar
            </button>
            {diff && (
              <div className="mt-2 max-h-64 overflow-auto rounded-md bg-soft p-2 text-[10px]">
                <p className="text-text">v{diff.version_a.number} → v{diff.version_b.number} · modelo {diff.model_changed ? "CAMBIÓ" : "igual"} · tools {diff.tools_changed ? "CAMBIARON" : "iguales"}</p>
                {diff.config_diff.map((c) => (
                  <p key={c.key} className={`${c.kind === "changed" ? "text-amber-400" : c.kind === "added" ? "text-emerald-400" : "text-red-400"}`}>
                    {c.kind} {c.key}: {JSON.stringify(c.a ?? "—")} → {JSON.stringify(c.b ?? "—")}
                  </p>
                ))}
                {diff.prompt_diff.changed && (
                  <p className="mt-1 text-faint">Prompt: {diff.prompt_diff.a_chars} → {diff.prompt_diff.b_chars} chars</p>
                )}
              </div>
            )}
          </section>

          <section className="lg:col-span-2">
            <h2 className="mb-2 text-sm font-semibold text-text">Releases</h2>
            <div className="panel space-y-2 p-4">
              {releases.map((r) => (
                <div key={r.id} className="rounded-md border border-border bg-soft/50 px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className={`badge ${r.channel === "canary" ? "badge-warning" : "badge-ok"}`}>{r.channel}</span>
                    <span className="text-sm font-medium text-text">v{r.version_number}</span>
                    <span className={`badge ${r.status === "promoted" || r.status === "running" ? "badge-ok" : r.status === "rolled_back" ? "badge-danger" : "badge-warning"}`}>{r.status}</span>
                    <span className="text-xs text-faint">{r.traffic_pct}% tráfico · health {r.health_score != null ? `${r.health_score}%` : "—"}</span>
                    <span className="flex-1" />
                    <button type="button" className="btn btn-ghost min-h-7 px-2 text-[11px]" onClick={() => void showDetail(r.id)}><CaretRight size={11} /> detalle</button>
                  </div>
                  <div className="mt-2 flex gap-1">
                    <button type="button" className="btn btn-ghost min-h-7 px-2 text-[11px]" disabled={!!busy} onClick={() => void act(r.id, "health")}>Health</button>
                    <button type="button" className="btn btn-ghost min-h-7 px-2 text-[11px]" disabled={!!busy} onClick={() => void act(r.id, "promote")}>Promover</button>
                    <button type="button" className="btn btn-ghost min-h-7 px-2 text-[11px]" disabled={!!busy} onClick={() => void act(r.id, "rollback")}><ArrowCounterClockwise size={11} /> Rollback</button>
                    <button type="button" className="btn btn-ghost min-h-7 px-2 text-[11px]" disabled={!!busy} onClick={() => void act(r.id, "pause")}>Pausar</button>
                    <button type="button" className="btn btn-ghost min-h-7 px-2 text-[11px]" disabled={!!busy} onClick={() => void act(r.id, "resume")}>Reanudar</button>
                  </div>
                </div>
              ))}
              {releases.length === 0 && <p className="text-xs text-faint">Sin releases.</p>}
            </div>
            {detail && (
              <div className="panel mt-2 p-4">
                <h3 className="mb-1 text-sm font-semibold text-text">Release {detail.id.slice(0, 8)} · v{detail.version_number}</h3>
                <div className="space-y-1">
                  {(detail.events ?? []).map((e) => (
                    <div key={e.id} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1 text-[11px]">
                      <span className={`badge ${e.event_type.includes("fail") ? "badge-danger" : e.event_type === "promoted" || e.event_type === "health_ok" ? "badge-ok" : "badge-muted"}`}>{e.event_type}</span>
                      <span className="flex-1 text-text">{e.detail}</span>
                      <span className="text-faint">{new Date(e.created_at).toLocaleTimeString()}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}