import { useState } from "react";

export function WebsiteStep({
  onPreview,
  onCommit,
  busy,
  preview,
}: {
  onPreview: (url: string) => void;
  onCommit: () => void;
  busy: boolean;
  preview?: {
    url?: string;
    host?: string;
    pages_detected?: number;
    status?: number;
    title?: string;
    content_type?: string;
    size?: string;
    robots?: boolean | null;
  };
}) {
  const [url, setUrl] = useState("");

  return (
    <div className="max-w-xl space-y-4">
      <h2 className="text-lg font-semibold text-text">Añade contenido web</h2>
      <p className="text-sm text-muted">Una URL. Sitemap y crawl completo llegan después.</p>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          onPreview(url);
        }}
      >
        <input
          className="input flex-1"
          placeholder="https://ejemplo.com/politicas"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <button type="submit" className="btn btn-secondary" disabled={busy}>
          Vista previa
        </button>
      </form>
      {preview && (
        <div className="panel p-4 text-sm">
          <p>Páginas detectadas: {preview.pages_detected ?? 1}</p>
          {preview.status != null && <p className="text-muted">HTTP {preview.status}</p>}
          {preview.title && <p className="text-muted">Título: {preview.title}</p>}
          {preview.content_type && <p className="text-muted">{preview.content_type}</p>}
          {preview.size && <p className="text-muted">Tamaño: {preview.size} bytes</p>}
          {preview.robots != null && (
            <p className="text-muted">{preview.robots ? "robots.txt encontrado" : "Sin robots.txt"}</p>
          )}
          <p className="text-muted">{preview.url}</p>
          <button type="button" className="btn btn-primary mt-3" onClick={onCommit} disabled={busy}>
            Importar
          </button>
        </div>
      )}
    </div>
  );
}
