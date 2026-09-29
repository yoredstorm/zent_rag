// =============================================================================
// ManageDatasetDialog — gestionar un dataset: renombrar, borrar, editar casos.
// =============================================================================
// Usa `/eval/datasets/{id}/examples` (listar/editar/eliminar) y
// `PATCH`/`DELETE /eval/datasets/{id}`. La lista principal solo corre el dataset.
// =============================================================================
import { FloppyDisk, Plus } from "@phosphor-icons/react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, type Session } from "../../api";
import { Badge, Button, ErrorInline, Field, Input, Modal, SuccessInline } from "../ui";
import { EvalCaseDialog, type EvalCaseInitial } from "./EvalCaseDialog";

type DatasetInfo = { id: string; name: string; case_count?: number };

type Example = {
  id: string;
  question: string;
  expected_answer: string | null;
  expected_behavior: string | null;
  expected_sources: string[];
};

function behaviorLabel(behavior: string | null): string {
  const norm = (behavior || "").toLowerCase();
  if (norm.includes("abst") || norm.includes("human")) return "Debe abstenerse";
  return "Debe responder";
}

export function ManageDatasetDialog({
  open,
  onOpenChange,
  session,
  dataset,
  onChanged,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  session?: Session | null;
  dataset: DatasetInfo | null;
  onChanged?: () => void;
}) {
  const [name, setName] = useState(dataset?.name || "");
  const [examples, setExamples] = useState<Example[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [editCase, setEditCase] = useState<Example | null>(null);

  const datasetId = dataset?.id;
  const datasetName = dataset?.name || "";

  const reload = useCallback(async () => {
    if (!session || !datasetId) return;
    setLoading(true);
    try {
      const out = await api<{ examples: Example[] }>(
        `/api/v1/eval/datasets/${datasetId}/examples`,
        { token: session.token, organizationId: session.organizationId },
      );
      setExamples(out.examples || []);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudieron cargar los casos");
    } finally {
      setLoading(false);
    }
  }, [session, datasetId]);

  useEffect(() => {
    if (!open || !datasetId) return;
    setName(datasetName);
    setConfirmDelete(false);
    setMsg("");
    setError("");
    void reload();
  }, [open, datasetId, datasetName, reload]);

  async function onRename(e: FormEvent) {
    e.preventDefault();
    if (!session || !datasetId || !name.trim()) return;
    setBusy(true);
    setError("");
    setMsg("");
    try {
      await api(`/api/v1/eval/datasets/${datasetId}`, {
        method: "PATCH",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ name: name.trim() }),
      });
      setMsg("Nombre actualizado.");
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo renombrar");
    } finally {
      setBusy(false);
    }
  }

  async function onDeleteDataset() {
    if (!session || !datasetId) return;
    setBusy(true);
    setError("");
    try {
      await api(`/api/v1/eval/datasets/${datasetId}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      onChanged?.();
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo eliminar");
      setConfirmDelete(false);
    } finally {
      setBusy(false);
    }
  }

  async function onDeleteExample(example: Example) {
    if (!session || !datasetId) return;
    setBusy(true);
    setError("");
    setMsg("");
    try {
      await api(`/api/v1/eval/datasets/${datasetId}/examples/${example.id}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg("Caso eliminado.");
      await reload();
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo eliminar el caso");
    } finally {
      setBusy(false);
    }
  }

  const editInitial: EvalCaseInitial | undefined = editCase
    ? {
        question: editCase.question,
        expected_answer: editCase.expected_answer,
        expected_behavior: editCase.expected_behavior,
        expected_sources: editCase.expected_sources,
      }
    : undefined;

  return (
    <>
      <Modal
        open={open}
        onOpenChange={(next) => {
          if (!next && busy) return;
          if (!next) onOpenChange(false);
        }}
        title={dataset ? `Gestionar ${dataset.name}` : "Gestionar dataset"}
        description="Edita el nombre, los casos de prueba o elimina el dataset completo."
        size="lg"
        footer={
          <>
            <Button
              variant={confirmDelete ? "danger" : "ghost"}
              onClick={() =>
                confirmDelete ? void onDeleteDataset() : setConfirmDelete(true)
              }
              disabled={busy}
            >
              {confirmDelete ? "Confirmar eliminación" : "Eliminar dataset"}
            </Button>
            <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
              Cerrar
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-5">
          <ErrorInline message={error} className="mb-0" />
          <SuccessInline message={msg} className="mb-0" />

          <form className="flex flex-wrap items-end gap-3" onSubmit={onRename}>
            <Field label="Nombre del dataset" className="min-w-0 flex-1">
              <Input
                value={name}
                onChange={(ev) => setName(ev.target.value)}
                required
                autoComplete="off"
              />
            </Field>
            <Button
              type="submit"
              variant="secondary"
              loading={busy}
              leadingIcon={FloppyDisk}
              disabled={!name.trim()}
            >
              Guardar nombre
            </Button>
          </form>

          <div className="flex items-center justify-between gap-3 border-t border-border-soft pt-4">
            <div>
              <p className="text-[13px] font-medium text-text">Casos de prueba</p>
              <p className="text-xs text-faint">
                {examples.length} caso{examples.length === 1 ? "" : "s"} en este dataset
              </p>
            </div>
            <Button
              size="sm"
              variant="primary"
              leadingIcon={Plus}
              onClick={() => setAddOpen(true)}
            >
              Agregar caso
            </Button>
          </div>

          {loading ? (
            <p className="text-[13px] text-faint">Cargando casos…</p>
          ) : examples.length === 0 ? (
            <p className="panel-quiet p-3 text-[13px] text-muted">
              Este dataset todavía no tiene casos. Agrega el primero con el botón de
              arriba.
            </p>
          ) : (
            <ul className="flex flex-col">
              {examples.map((example) => (
                <li
                  key={example.id}
                  className="flex items-start justify-between gap-3 border-b border-border-soft py-3 last:border-b-0"
                >
                  <div className="min-w-0">
                    <p className="text-[13px] leading-relaxed text-text">
                      {example.question}
                    </p>
                    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                      <Badge tone="neutral">{behaviorLabel(example.expected_behavior)}</Badge>
                      {example.expected_answer ? (
                        <span className="text-[11px] text-faint">
                          con respuesta esperada
                        </span>
                      ) : null}
                      {example.expected_sources.map((source) => (
                        <span key={source} className="chip mono max-w-[16rem] truncate" title={source}>
                          {source}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setEditCase(example)}
                      disabled={busy}
                    >
                      Editar
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => void onDeleteExample(example)}
                      disabled={busy}
                    >
                      Eliminar
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Modal>

      <EvalCaseDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        session={session}
        dataset={dataset}
        onSaved={() => {
          void reload();
          onChanged?.();
        }}
      />

      <EvalCaseDialog
        open={editCase !== null}
        onOpenChange={(next) => {
          if (!next) setEditCase(null);
        }}
        session={session}
        dataset={dataset}
        caseId={editCase?.id}
        initial={editInitial}
        onSaved={() => {
          setEditCase(null);
          void reload();
          onChanged?.();
        }}
      />
    </>
  );
}
