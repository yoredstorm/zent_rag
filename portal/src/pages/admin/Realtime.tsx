import { Broadcast, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { platformApi } from "../../api";
import {
  ErrorInline,
  PageHeader,
  SkeletonBlock,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Summary = {
  window_minutes: number;
  requests: number;
  errors: number;
  error_rate_pct: number;
  tokens: number;
  cost: number;
  active_organizations: number;
  by_model: { model: string; requests: number }[];
};

type LiveEvent = {
  event: string;
  ts: string;
  organization_id: string;
  deployment_id?: string | null;
  model?: string | null;
  tokens?: number;
  cost?: number;
  latency_ms?: number;
  status?: string | number;
};

export default function AdminRealtimePage() {
  const { session } = usePlatformAuth();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [autoCorrection, setAutoCorrection] = useState(false);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  async function loadSummary() {
    if (!session) return;
    try {
      const [s, ac] = await Promise.all([
        platformApi<Summary>("/api/v1/platform/realtime/summary?minutes=15", { token: session.token }),
        platformApi<{ enabled: boolean }>("/api/v1/platform/realtime/auto-correction", { token: session.token }),
      ]);
      setSummary(s);
      setAutoCorrection(ac.enabled);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!session) return;
    void loadSummary();
    // SSE con fetch (EventSource no soporta headers de auth).
    const controller = new AbortController();
    abortRef.current = controller;
    let buffer = "";
    const connect = async () => {
      try {
        const resp = await fetch("/api/v1/platform/realtime/stream", {
          headers: { Authorization: `Bearer ${session.token}` },
          signal: controller.signal,
        });
        if (!resp.ok || !resp.body) throw new Error(`SSE ${resp.status}`);
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        setConnected(true);
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split("\n\n");
          buffer = frames.pop() ?? "";
          for (const frame of frames) {
            const dataLine = frame.split("\n").find((l) => l.startsWith("data: "));
            if (!dataLine) continue;
            try {
              const payload = JSON.parse(dataLine.slice(6));
              setEvents((prev) => [payload, ...prev].slice(0, 60));
            } catch {
              /* heartbeat u otro */
            }
          }
        }
      } catch {
        // abort/desconexión
      } finally {
        setConnected(false);
      }
    };
    void connect();
    return () => controller.abort();
  }, [session]);

  async function toggleAutoCorrection() {
    if (!session) return;
    setError("");
    try {
      const out = await platformApi<{ enabled: boolean }>("/api/v1/platform/realtime/auto-correction", {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ enabled: !autoCorrection }),
      });
      setAutoCorrection(out.enabled);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  const isError = (s: unknown) =>
    typeof s === "string" ? ["error", "failed", "5xx"].includes(s) : (s as number) >= 500;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Real-Time"
        subtitle="Eventos en vivo (SSE), resumen de la ventana y corrección automática."
        actions={
          <button
            type="button"
            className={`btn min-h-11 ${autoCorrection ? "btn-danger" : "btn-secondary"}`}
            onClick={() => void toggleAutoCorrection()}
          >
            <WarningCircle size={15} aria-hidden />
            Auto-corrección: {autoCorrection ? "ON" : "OFF"}
          </button>
        }
      />
      <span className={`badge ${connected ? "badge-ok" : "badge-muted"}`}>
        <Broadcast size={12} className="mr-1 inline" aria-hidden />
        {connected ? "streaming" : "desconectado"}
      </span>
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <div className="panel p-4">
              <p className="stat-label">Requests (15m)</p>
              <p className="stat-value">{summary?.requests ?? 0}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Error rate</p>
              <p className="stat-value">{summary?.error_rate_pct ?? 0}%</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Costo</p>
              <p className="stat-value">${(summary?.cost ?? 0).toFixed(3)}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Tokens</p>
              <p className="stat-value">{(summary?.tokens ?? 0).toLocaleString()}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Orgs activas</p>
              <p className="stat-value">{summary?.active_organizations ?? 0}</p>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <section className="panel p-4 lg:col-span-1">
              <h3 className="mb-2 text-sm font-semibold text-text">Por modelo (15m)</h3>
              <ul className="space-y-1">
                {(summary?.by_model ?? []).map((m) => (
                  <li key={m.model} className="flex items-center justify-between text-sm">
                    <span className="mono text-xs text-text">{m.model}</span>
                    <span className="text-xs text-faint">{m.requests}</span>
                  </li>
                ))}
              </ul>
            </section>

            <section className="panel overflow-hidden lg:col-span-2">
              <div className="border-b border-border px-4 py-2">
                <h3 className="text-sm font-semibold text-text">Eventos en vivo</h3>
              </div>
              <div className="max-h-96 overflow-y-auto p-2">
                {events.length === 0 ? (
                  <p className="p-4 text-center text-xs text-faint">Esperando eventos… (ejecuta consultas)</p>
                ) : (
                  <ul className="space-y-1">
                    {events.map((e, i) => (
                      <li
                        key={i}
                        className={`rounded border px-2 py-1.5 font-mono text-[11px] ${
                          isError(e.status) ? "border-danger/40 bg-danger/10 text-danger" : "border-border text-text"
                        }`}
                      >
                        <span className="text-faint">{new Date(e.ts).toLocaleTimeString("es-PE")}</span>{" "}
                        {e.event} · org {e.organization_id.slice(0, 8)}
                        {e.deployment_id ? ` · dep ${e.deployment_id.slice(0, 8)}` : ""}
                        {e.model ? ` · ${e.model}` : ""} · {e.status} · {e.latency_ms != null ? `${e.latency_ms}ms` : ""} ·{" "}
                        ${e.cost ?? 0}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}