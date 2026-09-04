import { Anchor, Fingerprint, Scales, ShieldCheck, UserCheck } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorInline, PageHeader, SkeletonBlock } from "../components/ui";

type Policy = { id: string; policy_type: string; name: string; content: string; version: number; status: string; updated_at: string };
type Decision = { id: string; decision_type: string; target_id: string | null; title: string; rationale: string | null; status: string; approvers: { user_id: string; name: string; approved: boolean; approved_at: string; signature: string }[]; required_approvals: number; decided_at: string | null; created_at: string };
type AuditEntry = { id: string; actor_name: string; action: string; entity_type: string; detail: string; prev_hash: string; hash: string; created_at: string };
type Cert = { id: string; member_name: string; certification: string; issued_at: string; expires_at: string; status: string };
type Report = { total_score: number; pillars: Record<string, { score: number; detail: string }> };

const ST: Record<string, string> = { pending: "badge-warning", approved: "badge-ok", rejected: "badge-danger" };

export default function GovernancePage() {
  const { session } = useAuth();
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [auditOk, setAuditOk] = useState<boolean | null>(null);
  const [certs, setCerts] = useState<Cert[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [draftDecision, setDraftDecision] = useState({ decision_type: "deploy_approval", title: "", rationale: "" });
  const [certDraft, setCertDraft] = useState({ member_name: "", certification: "AI Ethics" });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [p, d, a, c, r] = await Promise.all([
        api<{ policies: Policy[] }>("/api/v1/governance/policies", { token: session.token, organizationId: session.organizationId }),
        api<{ decisions: Decision[] }>("/api/v1/governance/decisions", { token: session.token, organizationId: session.organizationId }),
        api<{ entries: AuditEntry[] }>("/api/v1/governance/audit", { token: session.token, organizationId: session.organizationId }),
        api<{ certifications: Cert[] }>("/api/v1/governance/certifications", { token: session.token, organizationId: session.organizationId }),
        api<Report>("/api/v1/governance/report", { token: session.token, organizationId: session.organizationId }),
      ]);
      setPolicies(p.policies || []);
      setDecisions(d.decisions || []);
      setAudit(a.entries || []);
      setCerts(c.certifications || []);
      setReport(r);
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

  async function decide(decisionId: string, approve: boolean) {
    if (!session) return;
    setBusy(`${approve ? "ok" : "no"}-${decisionId.slice(0, 6)}`);
    setError("");
    try {
      const out = await api<{ status: string; approvals: number }>(`/api/v1/governance/decisions/${decisionId}/decide`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ approve }),
      });
      setError(`${approve ? "Aprobada" : "Rechazada"}: ${out.status} (${out.approvals} firmas)`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function createDecision() {
    if (!session || !draftDecision.title) return;
    setBusy("create");
    setError("");
    try {
      await api("/api/v1/governance/decisions", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify(draftDecision),
      });
      setDraftDecision({ decision_type: "deploy_approval", title: "", rationale: "" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function addCert() {
    if (!session || !certDraft.member_name) return;
    setBusy("cert");
    setError("");
    try {
      await api("/api/v1/governance/certifications", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify(certDraft),
      });
      setCertDraft({ member_name: "", certification: "AI Ethics" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function verifyAudit() {
    if (!session) return;
    setBusy("verify");
    setError("");
    try {
      const out = await api<{ intact: boolean; verified: number; tampered: string[] }>("/api/v1/governance/audit/verify", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      setAuditOk(out.intact);
      setError(out.intact ? `Auditoría íntegra (${out.verified} entradas verificadas)` : `¡TAMPERING! ${out.tampered.length} entradas alteradas`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Governance Board" subtitle="Políticas versionadas, decisiones con firmas, auditoría encadenada con hash y reporte ejecutivo." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-64" />
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <section className="lg:col-span-2">
            <div className="panel p-4">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><Scales size={14} /> Reporte ejecutivo · {report?.total_score ?? 0}</h3>
              <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
                {Object.entries(report?.pillars ?? {}).map(([key, p]) => (
                  <div key={key} className="rounded-md bg-soft p-3">
                    <p className="text-xs font-semibold text-text">{key}</p>
                    <p className="mt-1 text-2xl font-bold text-text">{p.score}</p>
                    <p className="mt-1 text-[10px] text-faint">{p.detail}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="panel mt-3 p-4">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><Anchor size={14} /> Decisiones de la junta</h3>
              <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
                <select className="rounded-md border border-border bg-soft px-2 py-2 text-xs" value={draftDecision.decision_type} onChange={(e) => setDraftDecision((d) => ({ ...d, decision_type: e.target.value }))}>
                  {["deploy_approval", "incident_review", "policy_change", "model_change"].map((t) => (<option key={t} value={t}>{t}</option>))}
                </select>
                <input className="rounded-md border border-border bg-soft px-2 py-2 text-xs" placeholder="título…" value={draftDecision.title} onChange={(e) => setDraftDecision((d) => ({ ...d, title: e.target.value }))} />
                <button type="button" className="btn btn-primary min-h-8 text-xs" disabled={!!busy || !draftDecision.title} onClick={() => void createDecision()}>Crear decisión</button>
              </div>
              <div className="mt-3 space-y-2">
                {decisions.map((d) => (
                  <div key={d.id} className="rounded-md bg-soft px-3 py-2 text-xs">
                    <div className="flex items-center gap-2">
                      <span className={`badge ${ST[d.status] ?? "badge-muted"}`}>{d.status}</span>
                      <span className="badge badge-muted">{d.decision_type}</span>
                      <span className="flex-1 font-medium text-text">{d.title}</span>
                      <span className="text-faint">{d.approvers.length}/{d.required_approvals} firmas</span>
                      {d.status === "pending" && (
                        <div className="flex gap-1">
                          <button type="button" className="btn btn-ghost min-h-6 px-2 text-[10px]" disabled={!!busy} onClick={() => void decide(d.id, true)}><ShieldCheck size={10} /> Aprobar</button>
                          <button type="button" className="btn btn-ghost min-h-6 px-2 text-[10px]" disabled={!!busy} onClick={() => void decide(d.id, false)}>Rechazar</button>
                        </div>
                      )}
                    </div>
                    {d.rationale && <p className="mt-0.5 text-[10px] text-faint">{d.rationale}</p>}
                    {d.approvers.length > 0 && (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {d.approvers.map((a, i) => (
                          <span key={i} className="badge badge-muted" title={a.signature}>{a.name} · {a.approved ? "sí" : "no"}</span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
                {decisions.length === 0 && <p className="text-xs text-faint">Sin decisiones.</p>}
              </div>
            </div>

            <div className="panel mt-3 p-4">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><Fingerprint size={14} /> Auditoría encadenada ({audit.length})</h3>
              <button type="button" className="btn btn-secondary mb-2 min-h-7 text-[10px]" disabled={!!busy} onClick={() => void verifyAudit()}>Verificar integridad {auditOk === true ? "· OK" : auditOk === false ? "· ¡TAMPERED!" : ""}</button>
              <div className="max-h-64 space-y-1 overflow-y-auto">
                {audit.slice(0, 15).map((a) => (
                  <div key={a.id} className="rounded bg-soft px-2 py-1 text-[10px]">
                    <p className="text-faint"><span className="font-semibold text-text">{a.actor_name}</span> · {a.action} · {a.entity_type} · <span className="text-accent">{a.hash.slice(0, 12)}…</span></p>
                    <p className="truncate text-faint">{a.detail}</p>
                  </div>
                ))}
                {audit.length === 0 && <p className="text-xs text-faint">Sin entradas de auditoría.</p>}
              </div>
            </div>
          </section>

          <section className="space-y-4">
            <div className="panel p-4">
              <h3 className="mb-2 text-sm font-semibold text-text">Políticas</h3>
              <div className="space-y-1">
                {policies.map((p) => (
                  <div key={p.id} className="rounded-md bg-soft px-3 py-2 text-xs">
                    <div className="flex items-center gap-2">
                      <span className="flex-1 font-medium text-text">{p.name}</span>
                      <span className="badge badge-muted">v{p.version}</span>
                    </div>
                    <p className="mt-0.5 line-clamp-2 text-[10px] text-faint">{p.content}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="panel p-4">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><UserCheck size={14} /> Certificaciones ({certs.length})</h3>
              <div className="grid grid-cols-1 gap-2">
                <input className="rounded-md border border-border bg-soft px-2 py-2 text-xs" placeholder="miembro…" value={certDraft.member_name} onChange={(e) => setCertDraft((d) => ({ ...d, member_name: e.target.value }))} />
                <select className="rounded-md border border-border bg-soft px-2 py-2 text-xs" value={certDraft.certification} onChange={(e) => setCertDraft((d) => ({ ...d, certification: e.target.value }))}>
                  {["AI Ethics", "Prompt Safety", "Data Privacy", "Governance"].map((c) => (<option key={c} value={c}>{c}</option>))}
                </select>
                <button type="button" className="btn btn-primary min-h-8 text-xs" disabled={!!busy || !certDraft.member_name} onClick={() => void addCert()}>Registrar</button>
              </div>
              <div className="mt-2 space-y-1">
                {certs.map((c) => (
                  <p key={c.id} className="rounded bg-soft px-2 py-1 text-[10px] text-faint">{c.member_name} · {c.certification} · vence {c.expires_at}</p>
                ))}
              </div>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}