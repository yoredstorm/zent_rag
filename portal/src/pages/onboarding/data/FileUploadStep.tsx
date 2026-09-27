import { Plus } from "@phosphor-icons/react";
import { FileDropzone } from "../../../components/FileDropzone";
import { UploadQueueList } from "../../../components/UploadQueueList";
import { Button, Progress } from "../../../components/ui";
import {
  overallIndexProgress,
  uploadSummary,
  type UploadQueueRow,
} from "../../../lib/uploadQueue";

export function FileUploadStep({
  rows,
  onFiles,
  onRemove,
  onRetry,
  onClear,
  onSubmit,
  busy,
  retrying,
}: {
  rows: UploadQueueRow[];
  onFiles: (files: File[]) => void;
  onRemove: (row: UploadQueueRow) => void;
  onRetry: (row: UploadQueueRow) => void;
  onClear: () => void;
  onSubmit: () => void;
  busy: boolean;
  retrying?: string;
}) {
  const summary = uploadSummary(rows);
  const indexingProgress = overallIndexProgress(rows);
  const uploaded = summary.pending === 0 && summary.total > 0;

  const headline = busy
    ? summary.uploading
      ? `Subiendo ${summary.uploaded + 1} de ${summary.total} · ${summary.uploading.filename}`
      : `Subiendo ${summary.total} archivo${summary.total === 1 ? "" : "s"}…`
    : !uploaded
      ? `Listo para subir: ${summary.pending} archivo${summary.pending === 1 ? "" : "s"}`
      : summary.indexing > 0
        ? `Indexando ${summary.indexed} de ${summary.total} · Zent lee el contenido`
        : summary.indexed === summary.total
          ? `${summary.total} archivo${summary.total === 1 ? "" : "s"} indexado${summary.total === 1 ? "" : "s"}`
          : `${summary.queued} en cola de indexado${summary.failed > 0 ? ` · ${summary.failed} con error` : ""}`;

  return (
    <div>
      <h2 className="text-lg font-semibold text-text">Sube tus archivos</h2>
      <FileDropzone
        className="mt-5 min-h-40"
        disabled={busy}
        onFiles={onFiles}
        inputTestId="onboarding-file"
        dropzoneTestId="onboarding-dropzone"
      />

      {rows.length > 0 && (
        <div className="mt-4" data-testid="upload-progress">
          <Progress
            value={uploaded && !busy ? indexingProgress : summary.percent}
            label={headline}
            showValue
          />
          {uploaded && !busy && summary.indexed + summary.failed < summary.total && (
            <p className="mt-1.5 text-[11px] text-faint">
              El indexado corre en segundo plano; puedes seguir y volver a esta pantalla
              cuando quieras.
            </p>
          )}
        </div>
      )}

      <UploadQueueList
        rows={rows}
        onRemove={onRemove}
        onRetry={onRetry}
        retrying={retrying}
        className="mt-2"
      />

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          leadingIcon={Plus}
          loading={busy}
          disabled={busy || summary.pending === 0}
          onClick={onSubmit}
          data-testid="onboarding-upload"
        >
          {summary.total > 1 ? `Subir ${summary.total} archivos` : "Subir e indexar"}
        </Button>
        {rows.length > 0 && (
          <Button variant="ghost" onClick={onClear} disabled={busy}>
            Limpiar
          </Button>
        )}
      </div>
    </div>
  );
}
