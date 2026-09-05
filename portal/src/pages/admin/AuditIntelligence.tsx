import { Fingerprint, ShieldWarning, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Summary = {
  organization_id: string;
  total_events: number;
  top_actions: { action: string; count: number }[];
  top_users: { user_id: string; count: number }[];
  timeline_30d: { date: string; count: number }[];
};

type Anomaly = {
  id: string;
  organization_id: string | null;
  anomaly_type: string;
  severity: string;
  message: string;
  metadata: Record<string, unknown>;
  status: string;
  created_at: string;
};

export default function AdminAuditIntelligencePage() {
  const { session } = usePlatformAuth();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [piiResult, setPiiResult] = useState<string>("");
  const [piiInput, setPiiInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [orgId] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [s, a] = await Promise.all([
        platformApi<Summary>(`/api/v1/platform/audit-intelligence/summary?organization_id=${orgId}`, {
          token: session.token,
        }),
        platformApi<{ anomalies: Anomaly[] }>(
          `/api/v1/platform/audit-intelligence/anomalies?organization_id=${orgId}`,
          { token: session.token }
        ),
      ]);
      setSummary(s);
      setAnomalies(a.anomalies || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, orgId]);

  async function runChecks() {
    if (!session) return;
    setBusy("check");
    setError("");
    try {
      const out = await platformApi<{ count: number }>(
        `/api/v1/platform/audit-intelligence/check?organization_id=${orgId}`,
        { method: "POST", token: session.token, body: "{}" }
      );
      setError(`${out.count} anomalías detectadas`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function resolve(anomalyId: string) {
    if (!session) return;
    try {
      await platformApi(`/api/v1/platform/audit-intelligence/anomalies/${anomalyId}/resolve`, {
        method: "POST",
        token: session.token,
        body: "{}",
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function scanPii() {
    if (!session) return;
    setError("");
    try {
      const out = await platformApi<{ masked: string; detected: Record<string, number> }>(
        "/api/v1/platform/ai-governance/pii/mask",
        { method: "POST", token: session.token, body: JSON.stringify({ text: piiInput }) }
      );
      setPiiResult(`${JSON.stringify(out.detected)} → ${out.masked}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  const maxTimeline = Math.max(1, ...(summary?.timeline_30d ?? []).map((t) => t.count));

  return (
    <div className="space-y-6">
      <PageHeader
        title="Audit Intelligence"
        subtitle="Resumen de auditoría, detección de anomalías y gobernanza de IA."
        actions={
          <button type="button" className="btn btn-primary min-h-11" disabled={!!busy} onClick={() => void runChecks()}>
            <ShieldWarning size={15} aria-hidden /> Detectar anomalías
          </button>
        }
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="panel p-4">
              <p className="stat-label">Eventos de auditoría</p>
              <p className="stat-value">{summary?.total_events ?? 0}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Anomalías abiertas</p>
              <p className="stat-value">{anomalies.filter((a) => a.status === "open").length}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Top acción</p>
              <p className="stat-value text-base">{summary?.top_actions[0]?.action ?? "—"}</p>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <section className="panel p-4">
              <h3 className="mb-2 text-sm font-semibold text-text">Timeline 30d</h3>
              {!summary?.timeline_30d.length ? (
                <p className="text-xs text-faint">Sin eventos recientes.</p>
              ) : (
                <div className="flex h-24 items-end gap-1">
                  {summary.timeline_30d.map((t) => (
                    <div key={t.date} className="flex-1" title={`${t.date}: ${t.count}`}>
                      <div
                        className="w-full rounded-t bg-accent/60"
                        style={{ height: `${Math.max(3, (t.count / maxTimeline) * 88)}px` }}
                      />
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section className="panel p-4">
              <h3 className="mb-2 text-sm font-semibold text-text">Top acciones</h3>
              <ul className="space-y-1">
                {(summary?.top_actions ?? []).map((a) => (
                  <li key={a.action} className="flex items-center justify-between text-sm">
                    <span className="mono text-xs text-text">{a.action}</span>
                    <span className="text-xs text-faint">{a.count}</span>
                  </li>
                ))}
              </ul>
            </section>
          </div>

          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <WarningCircle size={15} aria-hidden /> Anomalías
            </h3>
            <div className="panel">
              {anomalies.length === 0 ? (
                <EmptyState icon={ShieldWarning} title="Sin anomalías" body="Ejecuta la detección para escanear logins, errores y actividad." />
              ) : (
                <ul className="space-y-2 p-3">
                  {anomalies.map((a) => (
                    <li
                      key={a.id}
                      className={`flex flex-wrap items-center justify-between gap-2 rounded-md border p-2.5 ${
                        a.status === "resolved" ? "border-border bg-soft" : "border-warn-soft bg-warn-soft/30"
                      }`}
                    >
                      <div className="min-w-0">
                        <p className="text-sm text-text">
                          {a.severity === "critical" && <WarningCircle size={13} className="mr-1 inline text-danger" aria-hidden />}
                          {a.message}
                        </p>
                        <p className="text-xs text-faint">
                          {a.anomaly_type} · {a.severity} · {new Date(a.created_at).toLocaleString("es-PE")}
                          {a.organization_id ? ` · ${a.organization_id.slice(0, 8)}` : " · platform"}
                        </p>
                      </div>
                      {a.status !== "resolved" && (
                        <button type="button" className="btn btn-ghost min-h-8 text-xs" onClick={() => void resolve(a.id)}>
                          Resolver
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>

          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <Fingerprint size={15} aria-hidden /> PII masking (test)
            </h3>
            <div className="panel flex flex-col gap-3 p-4">
              <textarea
                className="min-h-24 w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus:border-accent"
                placeholder="Pega un texto con emails, teléfonos, DNIs…"
                value={piiInput}
                onChange={(e) => setPiiInput(e.target.value)}
              />
              <div className="flex items-center gap-3">
                <button type="button" className="btn btn-secondary min-h-9 text-xs" onClick={() => void scanPii()}>
                  Enmascarar
                </button>
                {piiResult && <span className="text-xs text-faint">{piiResult}</span>}
              </div>
            </div>
          </section>
        </>
      )}
    </div>
  );
}