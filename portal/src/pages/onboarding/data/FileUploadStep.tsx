import { Plus } from "@phosphor-icons/react";
import { FileDropzone } from "../../../components/FileDropzone";
import {
  SelectedFilesList,
  UploadResultsList,
} from "../../../components/UploadQueueList";
import { Button } from "../../../components/ui";
import type { UploadItem } from "../../../lib/uploadQueue";

export function FileUploadStep({
  onFiles,
  files,
  items,
  onRemove,
  onRetry,
  onClear,
  onSubmit,
  busy,
  retrying,
}: {
  onFiles: (files: File[]) => void;
  files: File[];
  items: UploadItem[];
  onRemove: (file: File) => void;
  onRetry: (item: UploadItem) => void;
  onClear: () => void;
  onSubmit: () => void;
  busy: boolean;
  retrying?: string;
}) {
  return (
    <div>
      <h2 className="text-lg font-semibold text-text">Sube tus archivos</h2>
      <FileDropzone
        className="mt-5 min-h-48"
        disabled={busy}
        onFiles={onFiles}
        inputTestId="onboarding-file"
        dropzoneTestId="onboarding-dropzone"
      />
      <SelectedFilesList files={files} onRemove={onRemove} className="mt-4" />
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          leadingIcon={Plus}
          loading={busy}
          disabled={busy || files.length === 0}
          onClick={onSubmit}
          data-testid="onboarding-upload"
        >
          {files.length > 1 ? `Subir ${files.length} archivos` : "Subir e indexar"}
        </Button>
        {files.length > 0 && (
          <Button variant="ghost" onClick={onClear} disabled={busy}>
            Limpiar
          </Button>
        )}
      </div>
      {busy && <p className="mt-3 text-sm text-muted">Subiendo…</p>}
      <UploadResultsList
        items={items}
        retrying={retrying}
        onRetry={onRetry}
        testId="onboarding-upload-results"
        className="mt-4"
      />
    </div>
  );
}
