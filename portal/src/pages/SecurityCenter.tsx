import { Crosshair, ShieldCheck, ShieldWarning, TrendUp } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorInline, PageHeader, SkeletonBlock } from "../components/ui";

type Ev = { id: string; event_type: string; severity: string; score: number; status: string; evidence: Record<string, unknown>; responses: number; detected_at: string; resolved_at: string | null; timeline?: { step: string; detail: string; at: string }[] };
type Detail = Ev & { responses: { id: string; action_type: string; target: string; status: string; detail: string; created_at: string }[] };
type Posture = { threat_score: number; open_events: number; by_type: { event_type: string; count: number; avg_score: number }[] };
type Trend = { trend: { date: string; threat_score: number; open_events: number }[] };

const SEV: Record<string, string> = { low: "badge-muted", medium: "badge-warning", high: "badge-danger", critical: "badge-danger" };
const ST: Record<string, string> = { detected: "badge-danger", contained: "badge-warning", resolved: "badge-ok", false_positive: "badge-muted" };
const ACTIONS = ["revoke_key", "block_deployment", "throttle", "alert"];

export default function SecurityCenterPage() {
  const { session } = useAuth();
  const [events, setEvents] = useState<Ev[]>([]);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [posture, setPosture] = useState<Posture | null>(null);
  const [trend, setTrend] = useState<Trend | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [e, p, t] = await Promise.all([
        api<{ events: Ev[] }>("/api/v1/soc/events", { token: session.token, organizationId: session.organizationId }),
        api<Posture>("/api/v1/soc/posture", { token: session.token, organizationId: session.organizationId }),
        api<Trend>("/api/v1/soc/posture/trend", { token: session.token, organizationId: session.organizationId }),
      ]);
      setEvents(e.events || []);
      setPosture(p);
      setTrend(t);
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

  async function scan() {
    if (!session) return;
    setBusy("scan");
    setError("");
    try {
      const out = await api<{ detected: { event_type: string; severity: string }[] }>("/api/v1/soc/scan", { method: "POST", token: session.token, organizationId: session.organizationId });
      setError(out.detected.length ? `Detectados: ${out.detected.map((d) => `${d.event_type} (${d.severity})`).join(", ")}` : "Sin amenazas nuevas");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function act(eventId: string, action: string) {
    if (!session) return;
    setBusy(`${action}-${eventId.slice(0, 6)}`);
    setError("");
    try {
      const body = action === "resolve" ? JSON.stringify({ verdict: "resolved" }) : JSON.stringify({ action_type: action });
      const url = action === "resolve" ? `/api/v1/soc/events/${eventId}/resolve` : `/api/v1/soc/events/${eventId}/respond`;
      await api(url, { method: "POST", token: session.token, organizationId: session.organizationId, body });
      await load();
      if (detail?.id === eventId) await showDetail(eventId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function showDetail(eventId: string) {
    if (!session) return;
    const d = await api<Detail>(`/api/v1/soc/events/${eventId}`, { token: session.token, organizationId: session.organizationId });
    setDetail(d);
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Security Operations Center" subtitle="Detección de amenazas en tiempo real, respuestas automáticas y postura de seguridad." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-64" />
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <section className="lg:col-span-2">
            <div className="mb-2 flex items-center gap-2">
              <h2 className="text-sm font-semibold text-text">Eventos ({events.length})</h2>
              <button type="button" className="btn btn-secondary ml-auto min-h-8 text-xs" disabled={!!busy} onClick={() => void scan()}><Crosshair size={13} /> Escanear</button>
            </div>
            <div className="space-y-2">
              {events.map((e) => (
                <div key={e.id} className="panel p-3">
                  <div className="flex items-center gap-2">
                    <span className={`badge ${SEV[e.severity] ?? "badge-muted"}`}>{e.severity}</span>
                    <span className={`badge ${ST[e.status] ?? "badge-muted"}`}>{e.status}</span>
                    <button type="button" className="text-sm font-medium text-text" onClick={() => void showDetail(e.id)}>{e.event_type}</button>
                    <span className="ml-auto text-xs font-bold text-text">{e.score}</span>
                  </div>
                  <p className="mt-1 text-[10px] text-faint">{JSON.stringify(e.evidence).slice(0, 140)}</p>
                  <div className="mt-1 flex gap-1">
                    {ACTIONS.map((a) => (
                      <button key={a} type="button" className="btn btn-ghost min-h-6 px-2 text-[10px]" disabled={!!busy} onClick={() => void act(e.id, a)}>{a}</button>
                    ))}
                    <button type="button" className="btn btn-ghost min-h-6 px-2 text-[10px]" disabled={!!busy} onClick={() => void act(e.id, "resolve")}><ShieldCheck size={10} /> Resolver</button>
                  </div>
                </div>
              ))}
              {events.length === 0 && <p className="panel p-4 text-xs text-faint">Sin eventos. Corre un escaneo.</p>}
            </div>

            {detail && (
              <div className="panel mt-2 p-4">
                <h3 className="text-sm font-semibold text-text">{detail.event_type} · {detail.score}</h3>
                <div className="mt-2 space-y-1">
                  {(detail.timeline ?? []).map((tl, i) => (
                    <p key={i} className="rounded bg-soft px-2 py-1 text-[11px] text-faint"><span className="text-accent">{tl.step}</span> · {tl.detail} · {new Date(tl.at).toLocaleTimeString()}</p>
                  ))}
                </div>
                <h4 className="mb-1 mt-3 text-xs font-semibold text-text">Respuestas</h4>
                <div className="space-y-1">
                  {detail.responses.map((r) => (
                    <p key={r.id} className="rounded bg-soft px-2 py-1 text-[11px] text-faint">{r.action_type} → {r.target}: {r.detail}</p>
                  ))}
                  {detail.responses.length === 0 && <p className="text-xs text-faint">Sin respuestas.</p>}
                </div>
              </div>
            )}
          </section>

          <section className="space-y-4">
            <div className="panel p-4">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><ShieldWarning size={14} /> Postura</h3>
              <p className="text-3xl font-bold text-text">{posture?.threat_score ?? 0}</p>
              <p className="text-xs text-faint">Threat score · {posture?.open_events ?? 0} eventos abiertos</p>
              <div className="mt-3 space-y-1">
                {(posture?.by_type ?? []).map((t) => (
                  <div key={t.event_type} className="flex justify-between text-[11px]"><span className="text-text">{t.event_type}</span><span className="text-faint">{t.count} · {t.avg_score}</span></div>
                ))}
              </div>
              <h4 className="mb-1 mt-3 text-xs font-semibold text-text">Tendencia</h4>
              <div className="flex h-16 items-end gap-1">
                {(trend?.trend ?? []).slice(-14).map((t) => (
                  <div key={t.date} className="flex-1 rounded-t bg-red-400/70" style={{ height: `${Math.max(t.threat_score, 2)}%` }} title={`${t.date}: ${t.threat_score}`} />
                ))}
              </div>
            </div>
            <div className="panel p-4">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><TrendUp size={14} /> Cómo funciona</h3>
              <p className="text-[11px] text-faint">El escaneo revisa mensajes del copilot (injection), salidas bloqueadas (PII/exfiltración), fallos de auth (abuso de key) y picos de tráfico. Los eventos con score alto se deduplican por 24h.</p>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}