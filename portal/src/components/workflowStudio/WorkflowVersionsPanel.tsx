import { ArrowCounterClockwise, Camera, RocketLaunch } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { fmtDateTime } from "../../lib/format";
import { Button, ConfirmDialog, ErrorInline, Field, Input, StatusBadge, SuccessInline } from "../ui";
import { type WorkflowVersion } from "./types";

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
  const [restoreTarget, setRestoreTarget] = useState<WorkflowVersion | null>(null);

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
          <h2 className="text-h3">Versiones y publicación</h2>
          <p className="mt-0.5 text-[12px] leading-relaxed text-muted">
            Una versión congela el grafo y el trigger. Publicar guarda una versión en producción y
            activa el workflow; restaurar devuelve el grafo vivo a esa versión.
          </p>
        </div>
        <Field label="Nota de la versión (opcional)" hint="Ayuda a reconocerla en el historial.">
          <Input
            placeholder="añade el nodo de notificación…"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            maxLength={500}
          />
        </Field>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="primary"
            leadingIcon={RocketLaunch}
            loading={busy === "publish"}
            disabled={!!busy}
            data-testid="wf-publish"
            onClick={() =>
              void call(
                `/api/v1/workflows/${workflowId}/publish`,
                { notes: notes.trim() || null },
                "publish",
                "Publicado: versión en producción y workflow activo.",
                true,
              )
            }
          >
            Publicar
          </Button>
          <Button
            variant="secondary"
            leadingIcon={Camera}
            loading={busy === "snapshot"}
            disabled={!!busy}
            data-testid="wf-snapshot"
            onClick={() =>
              void call(
                `/api/v1/workflows/${workflowId}/versions`,
                { notes: notes.trim() || null },
                "snapshot",
                "Snapshot creado (draft).",
                false,
              )
            }
          >
            Crear snapshot
          </Button>
        </div>
        <p className="flex items-center gap-2 text-[12px] text-muted">
          Estado actual del workflow: <StatusBadge status={status} />
        </p>
        <ErrorInline message={error} className="mb-0" />
        <SuccessInline message={msg} className="mb-0" />
      </section>

      <section className="panel p-4">
        <h3 className="text-h3 mb-3">Historial ({versions.length})</h3>
        <div className="space-y-2.5">
          {versions.map((v) => (
            <div
              key={v.id}
              className="rounded-md border border-border bg-soft/50 p-3"
              data-testid="wf-version-row"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-[13px] font-semibold text-text tabular-nums">
                  v{v.version_number}
                </span>
                <StatusBadge status={v.status} />
                <span className="flex-1" />
                <span className="font-mono text-[11px] text-faint">{fmtDateTime(v.created_at)}</span>
              </div>
              {v.notes && <p className="mt-1.5 text-[12px] leading-relaxed text-muted">{v.notes}</p>}
              <div className="mt-2.5 flex flex-wrap gap-1.5">
                {(NEXT_STATUS[v.status] ?? []).map((next) => (
                  <Button
                    key={next.status}
                    variant="ghost"
                    size="sm"
                    className="text-[11px]"
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
                  </Button>
                ))}
                <Button
                  variant="ghost"
                  size="sm"
                  leadingIcon={ArrowCounterClockwise}
                  className="text-[11px]"
                  disabled={!!busy}
                  data-testid={`wf-restore-${v.version_number}`}
                  onClick={() => setRestoreTarget(v)}
                >
                  Restaurar
                </Button>
              </div>
            </div>
          ))}
          {versions.length === 0 && (
            <p className="text-[12px] leading-relaxed text-faint">
              Sin versiones. Publica o crea un snapshot para tener a dónde volver.
            </p>
          )}
        </div>
      </section>

      <ConfirmDialog
        open={Boolean(restoreTarget)}
        onOpenChange={(open) => {
          if (!open) setRestoreTarget(null);
        }}
        title={`Restaurar v${restoreTarget?.version_number ?? ""}`}
        body="Sobrescribe el grafo y el trigger actuales del workflow vivo. ¿Continuar?"
        confirmLabel="Restaurar"
        tone="danger"
        loading={busy === `restore-${restoreTarget?.id}`}
        onConfirm={() => {
          const target = restoreTarget;
          if (!target) return;
          setRestoreTarget(null);
          void call(
            `/api/v1/workflows/${workflowId}/versions/${target.id}/restore`,
            undefined,
            `restore-${target.id}`,
            `v${target.version_number} restaurada en el workflow vivo.`,
            true,
          );
        }}
      />
    </div>
  );
}
