import { UploadSimple } from "@phosphor-icons/react";
import { useState } from "react";
import type { ReactNode } from "react";
import { cn } from "./ui";

/** Copy único de carga de documentos (Fuentes y asistente de Agregar datos). */
export const FILE_DROPZONE_HINT =
  "o elegí desde tu equipo. PDF, CSV, Excel, TXT, MD o DOCX. Se suben de a uno; máximo 25 MB por archivo.";

/**
 * Dropzone compartido: mismo look, copy y comportamiento en Fuentes y en el
 * asistente de Agregar datos. `multiple=false` para flujos de un archivo.
 */
export function FileDropzone({
  onFiles,
  multiple = true,
  disabled = false,
  title = "Soltá archivos acá",
  hint = FILE_DROPZONE_HINT,
  inputTestId,
  dropzoneTestId,
  className,
}: {
  onFiles: (files: File[]) => void;
  multiple?: boolean;
  disabled?: boolean;
  title?: string;
  hint?: ReactNode;
  inputTestId?: string;
  dropzoneTestId?: string;
  className?: string;
}) {
  const [dragOver, setDragOver] = useState(false);

  return (
    <label
      data-testid={dropzoneTestId}
      className={cn(
        "flex min-h-36 flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-8 text-center transition-colors duration-150",
        dragOver ? "border-accent bg-accent-soft" : "border-border",
        disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer",
        className,
      )}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        if (disabled) return;
        const files = Array.from(e.dataTransfer.files);
        if (files.length) onFiles(multiple ? files : files.slice(0, 1));
      }}
    >
      <UploadSimple size={20} className="text-faint" aria-hidden />
      <p className="mt-2 text-sm font-medium text-text">{title}</p>
      <p className="mt-1 text-xs text-muted">{hint}</p>
      <input
        type="file"
        multiple={multiple}
        disabled={disabled}
        data-testid={inputTestId}
        className="sr-only"
        accept=".pdf,.csv,.xlsx,.xls,.txt,.md,.docx"
        onChange={(e) => {
          const files = Array.from(e.target.files || []);
          e.target.value = "";
          if (files.length) onFiles(multiple ? files : files.slice(0, 1));
        }}
      />
    </label>
  );
}
