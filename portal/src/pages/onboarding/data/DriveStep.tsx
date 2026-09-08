import { useState } from "react";

type Folder = { id: string; name: string; mimeType?: string };

export function DriveStep({
  onStart,
  onSelectFolder,
  onManualId,
  authorizationUrl,
  folders,
  busy,
}: {
  onStart: () => void;
  onSelectFolder: (id: string) => void;
  onManualId: (id: string) => void;
  authorizationUrl?: string;
  folders: Folder[];
  busy: boolean;
}) {
  const [advanced, setAdvanced] = useState(false);
  const [manual, setManual] = useState("");

  return (
    <div className="max-w-xl space-y-4">
      <h2 className="text-lg font-semibold text-text">Conecta Google Drive</h2>
      <p className="text-sm text-muted">Autoriza Zent y elige una carpeta. No hace falta copiar IDs.</p>
      {!authorizationUrl && (
        <button type="button" className="btn btn-primary" onClick={onStart} disabled={busy}>
          Conectar Google Drive
        </button>
      )}
      {authorizationUrl && folders.length === 0 && (
        <p className="text-sm text-muted">Autorización lista. Elige una carpeta cuando aparezca el listado.</p>
      )}
      {folders.length > 0 && (
        <ul className="panel divide-y divide-border">
          {folders.map((folder) => (
            <li key={folder.id}>
              <button
                type="button"
                className="w-full px-4 py-3 text-left text-sm hover:bg-soft"
                onClick={() => onSelectFolder(folder.id)}
              >
                {folder.name}
              </button>
            </li>
          ))}
        </ul>
      )}
      <button type="button" className="text-xs text-accent" onClick={() => setAdvanced((v) => !v)}>
        Advanced Settings
      </button>
      {advanced && (
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (manual.trim()) onManualId(manual.trim());
          }}
        >
          <input
            className="input flex-1"
            placeholder="ID de carpeta"
            value={manual}
            onChange={(e) => setManual(e.target.value)}
          />
          <button type="submit" className="btn btn-secondary">
            Usar ID
          </button>
        </form>
      )}
    </div>
  );
}
