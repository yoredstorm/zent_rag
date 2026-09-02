import { ShieldCheck, ShieldWarning, Trash } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Posture = {
  organization_id: string;
  score: number;
  components: { name: string; ok: boolean; weight: number; detail: string }[];
};

type Finding = {
  id: string;
  organization_id: string | null;
  finding_type: string;
  severity: string;
  target_type: string;
  target_id: string | null;
  detail: string;
  status: string;
  created_at: string;
};

export default function AdminSecurityCenterPage() {
  const { session } = usePlatformAuth();
  const [posture, setPosture] = useState<Posture[]>([]);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [scanText, setScanText] = useState("");
  const [scanResult, setScanResult] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [orgId, setOrgId] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [p, f] = await Promise.all([
        platformApi<{ organizations: Posture[] }>(
          `/api/v1/platform/security/posture?organization_id=${orgId}`,
          { token: session.token }
        ),
        platformApi<{ findings: Finding[] }>(
          `/api/v1/platform/security/findings?organization_id=${orgId}`,
          { token: session.token }
        ),
      ]);
      setPosture(p.organizations || []);
      setFindings(f.findings || []);
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

  async function scan() {
    if (!session) return;
    setBusy("scan");
    setError("");
    try {
      const out = await platformApi<{ count: number }>(
        `/api/v1/platform/security/scan?organization_id=${orgId}`,
        { method: "POST", token: session.token, body: "{}" }
      );
      setError(`${out.count} findings creados`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function resolve(findingId: string) {
    if (!session) return;
    try {
      await platformApi(`/api/v1/platform/security/findings/${findingId}/resolve`, {
        method: "POST",
        token: session.token,
        body: "{}",
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function revokeKey(keyId: string) {
    if (!session) return;
    setBusy(keyId);
    setError("");
    try {
      const out = await platformApi<{ status: string }>(
        `/api/v1/platform/security/keys/${keyId}/revoke`,
        { method: "POST", token: session.token, body: "{}" }
      );
      setError(`Key revocada: ${out.status}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function scanTextNow() {
    if (!session) return;
    setError("");
    try {
      const out = await platformApi<{ detected: Record<string, number> }>(
        "/api/v1/platform/security/scan-secrets",
        { method: "POST", token: session.token, body: JSON.stringify({ text: scanText }) }
      );
      setScanResult(JSON.stringify(out.detected));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Security Center"
        subtitle="Posture score por tenant, detección de secretos y leaks de API keys."
        actions={
          <button type="button" className="btn btn-primary min-h-11" disabled={!!busy} onClick={() => void scan()}>
            <ShieldWarning size={15} aria-hidden /> Escanear
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
              <ShieldCheck size={15} aria-hidden /> Posture por tenant
            </h3>
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              {posture.map((p) => (
                <div key={p.organization_id} className="panel p-3">
                  <div className="flex items-center justify-between">
                    <p className="mono text-xs text-faint">{p.organization_id.slice(0, 13)}…</p>
                    <span className={`badge ${p.score >= 70 ? "badge-ok" : p.score >= 40 ? "badge-pending" : "badge-danger"}`}>
                      {p.score}/100
                    </span>
                  </div>
                  <ul className="mt-2 grid grid-cols-1 gap-1 sm:grid-cols-2">
                    {p.components.map((c) => (
                      <li key={c.name} className="flex items-center justify-between text-xs">
                        <span className="text-muted">{c.name}</span>
                        <span className="flex items-center gap-1 text-faint">
                          {c.detail}
                          <ShieldCheck size={11} className={c.ok ? "text-success" : "text-danger"} aria-hidden />
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h3 className="mb-2 text-sm font-semibold text-text">Findings ({findings.length})</h3>
            <div className="panel">
              {findings.length === 0 ? (
                <EmptyState icon={ShieldWarning} title="Sin findings" body="Ejecuta el escaneo para buscar secretos y leaks." />
              ) : (
                <ul className="space-y-2 p-3">
                  {findings.map((f) => (
                    <li
                      key={f.id}
                      className={`flex flex-wrap items-center justify-between gap-2 rounded-md border p-2.5 ${
                        f.status === "resolved" ? "border-border bg-soft" : "border-danger/30 bg-danger/10"
                      }`}
                    >
                      <div className="min-w-0">
                        <p className="text-sm text-text">{f.detail}</p>
                        <p className="text-xs text-faint">
                          {f.finding_type} · {f.severity} · {new Date(f.created_at).toLocaleString("es-PE")}
                          {f.organization_id ? ` · ${f.organization_id.slice(0, 8)}` : ""}
                        </p>
                      </div>
                      {f.status !== "resolved" && (
                        <button type="button" className="btn btn-ghost min-h-8 text-xs" onClick={() => void resolve(f.id)}>
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
            <h3 className="mb-2 text-sm font-semibold text-text">Detección de secretos (test)</h3>
            <div className="panel flex flex-col gap-3 p-4">
              <textarea
                className="min-h-24 w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text"
                placeholder="Pega texto con sk-…, zent_sk_…, claves privadas…"
                value={scanText}
                onChange={(e) => setScanText(e.target.value)}
              />
              <div className="flex items-center gap-3">
                <button type="button" className="btn btn-secondary min-h-9 text-xs" onClick={() => void scanTextNow()}>
                  Escanear
                </button>
                {scanResult && <span className="text-xs text-faint">{scanResult}</span>}
              </div>
            </div>
          </section>
        </>
      )}
    </div>
  );
}