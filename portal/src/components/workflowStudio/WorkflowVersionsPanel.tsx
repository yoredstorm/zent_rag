import { ArrowCounterClockwise, Camera, RocketLaunch } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { fmtDateTime } from "../../lib/format";
import { ErrorInline, SuccessInline } from "../ui";
import { STATUS_BADGE, type WorkflowVersion } from "./types";

type Props = {
  workflowId: string;
  status: string;
  /** Se dispara tras publicar o restaurar para recargar el estudio. */
  onChanged: () => void;
};

/** Siguientes estados válidos según el ciclo de vida del backend. */
const NEXT_STATUS: Record<string, { status: string; label: string }[]> = {
  draft: [
    { status: "ready", label: "Marcar lista" },
    { status: "archived", label: "Archivar" },
  ],
  ready: [
    { status: "production", label: "Poner en producción" },
    { status: "archived", label: "Archivar" },
  ],
  production: [
    { status: "ready", label: "Bajar a ready" },
    { status: "archived", label: "Archivar" },
  ],
  archived: [],
};

export function WorkflowVersionsPanel({ workflowId, status, onChanged }: Props) {
  const { session } = useAuth();
  const [versions, setVersions] = useState<WorkflowVersion[]>([]);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    if (!session) return;
    try {
      const d = await api<{ versions: WorkflowVersion[] }>(
        `/api/v1/workflows/${workflowId}/versions`,
        { token: session.token, organizationId: session.organizationId },
      );
      setVersions(d.versions || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }, [session, workflowId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function call(
    path: string,
    body: Record<string, unknown> | undefined,
    token: string,
    okMsg: string,
    reloadStudio: boolean,
  ) {
    if (!session) return;
    setBusy(token);
    setError("");
    setMsg("");
    try {
      await api(path, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: body ? JSON.stringify(body) : JSON.stringify({}),
      });
      setMsg(okMsg);
      setNotes("");
      await load();
      if (reloadStudio) onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="space-y-4" data-testid="wf-advanced-panel">
      <section className="panel space-y-3 p-4">
        <div>
          <h2 className="text-sm font-semibold text-text">Versiones y publicación</h2>
          <p className="mt-0.5 text-xs text-muted">
            Una versión congela el grafo y el trigger. Publicar guarda una versión en producción y
            activa el workflow; restaurar devuelve el grafo vivo a esa versión.
          </p>
        </div>
        <label className="block text-xs text-muted">
          Nota de la versión (opcional)
          <input
            className="mt-1 w-full rounded-md border border-border bg-soft px-2 py-2 text-sm"
            placeholder="añade el nodo de notificación…"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            maxLength={500}
          />
        </label>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="btn btn-primary min-h-11 text-xs"
            disabled={!!busy}
            onClick={() =>
              void call(
                `/api/v1/workflows/${workflowId}/publish`,
                { notes: notes.trim() || null },
                "publish",
                "Publicado: versión en producción y workflow activo.",
                true,
              )
            }
            data-testid="wf-publish"
          >
            <RocketLaunch size={15} aria-hidden /> Publicar
          </button>
          <button
            type="button"
            className="btn btn-secondary min-h-11 text-xs"
            disabled={!!busy}
            onClick={() =>
              void call(
                `/api/v1/workflows/${workflowId}/versions`,
                { notes: notes.trim() || null },
                "snapshot",
                "Snapshot creado (draft).",
                false,
              )
            }
            data-testid="wf-snapshot"
          >
            <Camera size={15} aria-hidden /> Crear snapshot
          </button>
        </div>
        <p className="text-[11px] text-muted">
          Estado actual del workflow: <span className="font-medium text-text">{status}</span>
        </p>
        <ErrorInline message={error} />
        <SuccessInline message={msg} />
      </section>

      <section className="panel p-4">
        <h3 className="mb-2 text-sm font-semibold text-text">Historial ({versions.length})</h3>
        <div className="space-y-2">
          {versions.map((v) => (
            <div key={v.id} className="rounded-md border border-border bg-soft/50 p-3" data-testid="wf-version-row">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium text-text">v{v.version_number}</span>
                <span className={`badge ${STATUS_BADGE[v.status] ?? "badge-muted"}`}>{v.status}</span>
                <span className="flex-1" />
                <span className="text-[10px] text-faint">{fmtDateTime(v.created_at)}</span>
              </div>
              {v.notes && <p className="mt-1 text-xs text-muted">{v.notes}</p>}
              <div className="mt-2 flex flex-wrap gap-2">
                {(NEXT_STATUS[v.status] ?? []).map((next) => (
                  <button
                    key={next.status}
                    type="button"
                    className="btn btn-ghost min-h-8 px-2 text-[10px]"
                    disabled={!!busy}
                    onClick={() =>
                      void call(
                        `/api/v1/workflows/${workflowId}/versions/${v.id}/promote`,
                        { status: next.status },
                        `promote-${v.id}`,
                        `v${v.version_number} → ${next.status}.`,
                        false,
                      )
                    }
                  >
                    {next.label}
                  </button>
                ))}
                <button
                  type="button"
                  className="btn btn-ghost min-h-8 px-2 text-[10px]"
                  disabled={!!busy}
                  onClick={() => {
                    if (
                      !window.confirm(
                        `Restaurar v${v.version_number} sobrescribe el grafo y el trigger actuales. ¿Continuar?`,
                      )
                    ) {
                      return;
                    }
                    void call(
                      `/api/v1/workflows/${workflowId}/versions/${v.id}/restore`,
                      undefined,
                      `restore-${v.id}`,
                      `v${v.version_number} restaurada en el workflow vivo.`,
                      true,
                    );
                  }}
                  data-testid={`wf-restore-${v.version_number}`}
                >
                  <ArrowCounterClockwise size={12} aria-hidden /> Restaurar
                </button>
              </div>
            </div>
          ))}
          {versions.length === 0 && (
            <p className="text-xs text-faint">
              Sin versiones. Publica o crea un snapshot para tener a dónde volver.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
