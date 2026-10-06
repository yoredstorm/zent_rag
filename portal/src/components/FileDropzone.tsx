import { UploadSimple } from "@phosphor-icons/react";
import { useState } from "react";
import type { ReactNode } from "react";
import { cn } from "./ui";

/** Copy único de carga de documentos (Fuentes y asistente de Agregar datos). */
export const FILE_DROPZONE_HINT =
  "o elige desde tu equipo. PDF, CSV, Excel, TXT, MD o DOCX. Se suben de a uno; máximo 25 MB por archivo.";

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
      data-drag={dragOver}
      className={cn(
        "zd-shell",
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
      <span className="zd-core">
        <span className="zd-orb">
          <UploadSimple size={18} aria-hidden />
        </span>
        <p className="mt-3 text-sm font-medium text-text">{title}</p>
        <p className="mt-1 max-w-sm text-xs leading-relaxed text-muted">{hint}</p>
      </span>
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
