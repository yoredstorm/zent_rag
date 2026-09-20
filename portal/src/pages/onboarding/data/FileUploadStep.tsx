import { FileDropzone } from "../../../components/FileDropzone";

export function FileUploadStep({
  onFile,
  busy,
  filename,
}: {
  onFile: (file: File) => void;
  busy: boolean;
  filename?: string;
}) {
  return (
    <div>
      <h2 className="text-lg font-semibold text-text">Sube tus archivos</h2>
      <FileDropzone
        className="mt-5 min-h-48"
        multiple={false}
        disabled={busy}
        onFiles={(files) => {
          if (files[0]) onFile(files[0]);
        }}
        inputTestId="onboarding-file"
      />
      {busy && <p className="mt-3 text-sm text-muted">Subiendo…</p>}
      {filename && <p className="mt-3 text-sm text-ok">Archivo: {filename}</p>}
    </div>
  );
}
