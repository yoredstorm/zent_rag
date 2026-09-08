import { useState } from "react";

export function FileUploadStep({
  onFile,
  busy,
  filename,
}: {
  onFile: (file: File) => void;
  busy: boolean;
  filename?: string;
}) {
  const [hover, setHover] = useState(false);

  return (
    <div>
      <h2 className="text-lg font-semibold text-text">Sube tus archivos</h2>
      <p className="mt-1 text-sm text-muted">PDF, CSV, Excel, TXT, Markdown o DOCX. Máximo 25 MB.</p>
      <label
        className={`mt-5 flex min-h-48 cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-10 ${
          hover ? "border-accent bg-accent-soft" : "border-border"
        }`}
        onDragOver={(e) => {
          e.preventDefault();
          setHover(true);
        }}
        onDragLeave={() => setHover(false)}
        onDrop={(e) => {
          e.preventDefault();
          setHover(false);
          const file = e.dataTransfer.files[0];
          if (file) onFile(file);
        }}
      >
        <p className="text-sm font-medium text-text">Suelta archivos aquí</p>
        <p className="mt-1 text-xs text-muted">o examina tu equipo</p>
        <input
          type="file"
          className="sr-only"
          data-testid="onboarding-file"
          accept=".pdf,.csv,.xlsx,.xls,.txt,.md,.docx"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) onFile(file);
          }}
        />
      </label>
      {busy && <p className="mt-3 text-sm text-muted">Subiendo…</p>}
      {filename && <p className="mt-3 text-sm text-ok">Archivo: {filename}</p>}
    </div>
  );
}
