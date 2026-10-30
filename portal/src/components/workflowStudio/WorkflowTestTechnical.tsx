import type { ReactNode } from "react";
import type { RunDetail } from "../WorkflowRunInspector";
import type { TestReportOut } from "./workflowTestTypes";

function Mono({ children }: { children: ReactNode }) {
  return <span className="font-mono text-[10.5px] break-all text-muted">{children}</span>;
}

export function WorkflowTestTechnical({
  report,
  run,
}: {
  report: TestReportOut | null;
  run: RunDetail | null;
}) {
  if (!report && !run) return null;
  return (
    <div className="space-y-2">
      {report && (
        <details className="rounded-md border border-border bg-raised/40 px-3 py-2" data-testid="wf-test-report">
          <summary className="cursor-pointer text-[11.5px] font-medium text-muted select-none">
            Detalles técnicos del reporte
          </summary>
          <div className="mt-2 space-y-1 text-[11px] leading-relaxed text-muted">
            <p>
              Report ID: <Mono>{report.test_report_id ?? report.report_id ?? "no disponible"}</Mono>
            </p>
            <p>
              Solicitado: <Mono>{report.requested_level}</Mono> · Ejecutado:{" "}
              <Mono>{report.effective_level}</Mono> · Resultado: <Mono>{report.result}</Mono>
            </p>
            <p>
              Provider verificado: <Mono>{String(Boolean(report.provider_verified))}</Mono>
              {report.state ? (
                <>
                  {" "}
                  · Estado: <Mono>{report.state}</Mono>
                </>
              ) : null}
            </p>
            {report.capped_reason && (
              <p>
                Motivo del ajuste: <Mono>{report.capped_reason}</Mono>
              </p>
            )}
            {report.why && <p>{report.why}</p>}
            <p>
              Nodos ejecutados: <Mono>{report.executed_nodes?.length ?? 0}</Mono> · Timeline:{" "}
              <Mono>{report.timeline?.length ?? 0}</Mono>
            </p>
            {report.hashes && (
              <div className="space-y-0.5">
                <p>
                  graph_hash: <Mono>{report.hashes.graph_hash ?? "no disponible"}</Mono>
                </p>
                <p>
                  plan_hash: <Mono>{report.hashes.plan_hash ?? "no disponible"}</Mono>
                </p>
                <p>
                  role_hash: <Mono>{report.hashes.role_hash ?? "no disponible"}</Mono>
                </p>
                <p>
                  binding_hash: <Mono>{report.hashes.binding_hash ?? "no disponible"}</Mono>
                </p>
              </div>
            )}
            {report.readiness?.reasons && report.readiness.reasons.length > 0 && (
              <div>
                <p className="font-medium text-text">Readiness del reporte</p>
                <ul className="mt-0.5 list-disc space-y-0.5 pl-4">
                  {report.readiness.reasons.slice(0, 8).map((reason) => (
                    <li key={reason}>
                      <Mono>{reason}</Mono>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </details>
      )}

      {run && (
        <details className="rounded-md border border-border bg-raised/40 px-3 py-2" data-testid="wf-run-technical">
          <summary className="cursor-pointer text-[11.5px] font-medium text-muted select-none">
            Detalles técnicos de la corrida
          </summary>
          <div className="mt-2 space-y-1 text-[11px] leading-relaxed text-muted">
            <p>
              Run ID: <Mono>{run.id}</Mono>
            </p>
            <p>
              Estado: <Mono>{run.status}</Mono>
              {run.duration_ms != null ? (
                <>
                  {" "}
                  · Duración reportada: <Mono>{run.duration_ms} ms</Mono>
                </>
              ) : (
                <>
                  {" "}
                  · Duración: <Mono>no disponible</Mono>
                </>
              )}
            </p>
            {run.correlation_id && (
              <p>
                correlation_id: <Mono>{run.correlation_id}</Mono>
              </p>
            )}
            <p>
              Pasos registrados: <Mono>{run.steps?.length ?? 0}</Mono>
            </p>
            {run.error && <p className="text-danger">{run.error}</p>}
            <p className="text-faint">
              La salida cruda de cada nodo se inspecciona en su paso. No se vuelcan secretos aquí.
            </p>
          </div>
        </details>
      )}
    </div>
  );
}
