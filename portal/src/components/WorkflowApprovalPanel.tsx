import { Check, X } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Button, ErrorInline, Panel, StatusBadge } from "./ui";
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
 * Es una decisión: se queda inline, no se esconde en un drawer.
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
  const [pendingAction, setPendingAction] = useState<{
    id: string;
    decision: "approved" | "rejected";
  } | null>(null);
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
    setPendingAction({ id: approval.id, decision });
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
      setPendingAction(null);
    }
  }

  const pending = (approvals ?? []).filter((approval) => approval.status === "pending");
  if (!approvals || pending.length === 0) return null;

  return (
    <div className="flex flex-col gap-3" data-testid="wf-approval-panel">
      <p className="eyebrow">
        {pending.length === 1
          ? "1 decisión pendiente"
          : `${pending.length} decisiones pendientes`}
      </p>
      {pending.map((approval) => {
        const context = approval.context ?? {};
        const decisions = context.decisions ?? [];
        const evidence = context.evidence_refs ?? [];
        const claims = context.claim_refs ?? [];
        const citations = context.citations ?? [];
        const dataSummary = Object.entries(context.data_summary ?? {});
        const deciding = pendingAction?.id === approval.id;
        const approving = deciding && pendingAction?.decision === "approved";
        const rejecting = deciding && pendingAction?.decision === "rejected";
        return (
          <Panel
            key={approval.id}
            className="border-warn/30"
            data-testid={`wf-approval-${approval.id}`}
          >
            <div className="flex flex-wrap items-center gap-2 border-b border-border-soft px-3 py-2.5">
              <StatusBadge status="pending" />
              <h3 className="min-w-0 flex-1 truncate text-h3">
                {approval.action || "Acción sensible"}
              </h3>
            </div>

            <div className="flex flex-col gap-3 p-3">
              {approval.summary && (
                <p className="text-[13px] leading-relaxed text-muted">{approval.summary}</p>
              )}

              {decisions.length > 0 && (
                <div data-testid="wf-approval-decision">
                  <p className="eyebrow mb-1.5">Recomendación</p>
                  <DataView data={decisions[0]} testId="wf-approval-decision-data" />
                </div>
              )}

              {(evidence.length > 0 || claims.length > 0 || citations.length > 0) && (
                <div className="flex flex-col gap-1.5 rounded-md bg-raised px-2.5 py-2">
                  <p className="eyebrow">Evidencia</p>
                  {evidence.length > 0 && (
                    <p className="text-xs text-muted" data-testid="wf-approval-evidence">
                      Evidencia: {evidence.length} {evidence.length === 1 ? "fuente" : "fuentes"}
                      {evidence[0]?.label ? (
                        <span className="text-text"> · {evidence[0].label}</span>
                      ) : null}
                    </p>
                  )}
                  {claims.length > 0 && (
                    <p className="text-xs text-muted" data-testid="wf-approval-claims">
                      Claims propuestos: {claims.length}
                      {claims[0]?.text ? (
                        <span className="text-faint"> · {claims[0].text}</span>
                      ) : null}
                    </p>
                  )}
                  {citations.length > 0 && (
                    <ul className="flex flex-col gap-1" data-testid="wf-approval-citations">
                      {citations.slice(0, 3).map((citation, index) => (
                        <li key={index} className="min-w-0 text-xs text-faint">
                          <span className="text-muted">{citation.document_name || "documento"}</span>
                          {citation.page ? ` · pág. ${citation.page}` : ""}
                          {citation.excerpt ? ` · ${citation.excerpt.slice(0, 80)}` : ""}
                        </li>
                      ))}
                    </ul>
                  )}
                  {dataSummary.length > 0 && (
                    <p className="text-xs text-faint" data-testid="wf-approval-data">
                      Datos: {dataSummary.map(([key]) => key).join(", ")}
                    </p>
                  )}
                </div>
              )}

              <ErrorInline message={error} className="mb-0" />

              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="primary"
                  size="sm"
                  leadingIcon={Check}
                  loading={approving}
                  disabled={rejecting}
                  data-testid={`wf-approval-approve-${approval.id}`}
                  onClick={() => void decide(approval, "approved")}
                >
                  Aprobar
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  leadingIcon={X}
                  loading={rejecting}
                  disabled={approving}
                  data-testid={`wf-approval-reject-${approval.id}`}
                  onClick={() => void decide(approval, "rejected")}
                >
                  Rechazar
                </Button>
                <span className="text-[11px] text-faint">
                  El run queda esperando esta decisión.
                </span>
              </div>
            </div>
          </Panel>
        );
      })}
    </div>
  );
}
