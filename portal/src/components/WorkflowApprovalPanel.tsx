import { Check, X } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { DataView } from "./workflowStudio/DataView";

export type WorkflowApprovalContext = {
  decisions?: Record<string, unknown>[];
  evidence_refs?: { evidence_id?: string; label?: string }[];
  claim_refs?: { claim_id?: string; text?: string; status?: string }[];
  citations?: {
    document_name?: string;
    page?: number | null;
    section_path?: string[];
    excerpt?: string;
  }[];
  artifacts?: { id?: string; title?: string }[];
  data_summary?: Record<string, { keys?: string[]; answer?: string | null }>;
};

export type WorkflowApproval = {
  id: string;
  run_id: string;
  node_id?: string | null;
  action?: string | null;
  summary?: string | null;
  status: string;
  requested_at?: string;
  decided_at?: string | null;
  context?: WorkflowApprovalContext | null;
};

/**
 * Panel de aprobación humana con evidencia (Fase 6): el revisor ve la
 * recomendación del agente, evidencia/claims del ledger, citas y datos del run.
 */
export function WorkflowApprovalPanel({
  runId,
  onDecided,
}: {
  runId: string;
  onDecided?: (decision: "approved" | "rejected") => void;
}) {
  const { session } = useAuth();
  const [approvals, setApprovals] = useState<WorkflowApproval[] | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session || !runId) return;
    let alive = true;
    api<{ approvals: WorkflowApproval[] }>(`/api/v1/workflows/runs/${runId}/approvals`, {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => {
        if (alive) setApprovals(data.approvals ?? []);
      })
      .catch(() => {
        if (alive) setApprovals([]);
      });
    return () => {
      alive = false;
    };
  }, [session, runId]);

  async function decide(approval: WorkflowApproval, decision: "approved" | "rejected") {
    if (!session) return;
    setBusy(approval.id);
    setError("");
    try {
      await api(`/api/v1/workflows/runs/${runId}/approvals/${approval.id}/decide`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ decision, comment: null }),
      });
      setApprovals((prev) =>
        (prev ?? []).map((item) =>
          item.id === approval.id ? { ...item, status: decision } : item
        )
      );
      onDecided?.(decision);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No pude registrar la decisión.");
    } finally {
      setBusy("");
    }
  }

  const pending = (approvals ?? []).filter((approval) => approval.status === "pending");
  if (!approvals || pending.length === 0) return null;

  return (
    <div className="space-y-2" data-testid="wf-approval-panel">
      {pending.map((approval) => {
        const context = approval.context ?? {};
        const decisions = context.decisions ?? [];
        const evidence = context.evidence_refs ?? [];
        const claims = context.claim_refs ?? [];
        const citations = context.citations ?? [];
        const dataSummary = Object.entries(context.data_summary ?? {});
        return (
          <div
            key={approval.id}
            className="rounded-md border border-warn/40 bg-warn-soft/40 px-2 py-2"
            data-testid={`wf-approval-${approval.id}`}
          >
            <p className="text-[11px] font-semibold text-text">
              Aprobación: {approval.action || "acción sensible"}
            </p>
            {approval.summary && <p className="mt-0.5 text-[10px] text-muted">{approval.summary}</p>}

            {decisions.length > 0 && (
              <div className="mt-1.5" data-testid="wf-approval-decision">
                <p className="text-[9px] font-semibold tracking-wide text-faint uppercase">Recomendación</p>
                <DataView data={decisions[0]} testId="wf-approval-decision-data" />
              </div>
            )}
            {evidence.length > 0 && (
              <p className="mt-1 text-[10px] text-muted" data-testid="wf-approval-evidence">
                Evidencia: {evidence.length} {evidence.length === 1 ? "fuente" : "fuentes"}
                {evidence[0]?.label ? ` · ${evidence[0].label}` : ""}
              </p>
            )}
            {claims.length > 0 && (
              <p className="mt-0.5 text-[10px] text-muted" data-testid="wf-approval-claims">
                Claims propuestos: {claims.length}
              </p>
            )}
            {citations.length > 0 && (
              <ul className="mt-1 space-y-0.5" data-testid="wf-approval-citations">
                {citations.slice(0, 3).map((citation, index) => (
                  <li key={index} className="truncate text-[10px] text-faint">
                    {citation.document_name || "documento"}
                    {citation.page ? ` · pág. ${citation.page}` : ""}
                    {citation.excerpt ? ` · ${citation.excerpt.slice(0, 80)}` : ""}
                  </li>
                ))}
              </ul>
            )}
            {dataSummary.length > 0 && (
              <p className="mt-1 text-[10px] text-faint" data-testid="wf-approval-data">
                Datos: {dataSummary.map(([key]) => key).join(", ")}
              </p>
            )}

            <div className="mt-2 flex gap-2">
              <button
                type="button"
                className="btn btn-primary min-h-8 flex-1 text-[11px]"
                disabled={busy === approval.id}
                data-testid={`wf-approval-approve-${approval.id}`}
                onClick={() => void decide(approval, "approved")}
              >
                <Check size={12} aria-hidden /> Aprobar
              </button>
              <button
                type="button"
                className="btn btn-secondary min-h-8 flex-1 text-[11px]"
                disabled={busy === approval.id}
                data-testid={`wf-approval-reject-${approval.id}`}
                onClick={() => void decide(approval, "rejected")}
              >
                <X size={12} aria-hidden /> Rechazar
              </button>
            </div>
            {error && <p className="mt-1 text-[10px] text-danger">{error}</p>}
          </div>
        );
      })}
    </div>
  );
}
