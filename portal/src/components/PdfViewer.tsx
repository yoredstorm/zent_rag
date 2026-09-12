import { useEffect, useRef, useState } from "react";
import * as pdfjs from "pdfjs-dist";
import { Spinner } from "./ui";

pdfjs.GlobalWorkerOptions.workerSrc =
  new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();

type Bbox = { x0: number; y0: number; x1: number; y1: number };

export type PdfHighlight = { page: number; bbox: Bbox | null; excerpt: string };

/** Escala CSS para render (1.6 → 115px por unidad PDF @72dpi). */
const SCALE = 1.6;

export default function PdfViewer({
  fileUrl,
  token,
  highlight,
}: {
  fileUrl: string;
  token?: string;
  highlight: PdfHighlight | null;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const docRef = useRef<import("pdfjs-dist").PDFDocumentProxy | null>(null);
  const renderTaskRef = useRef<import("pdfjs-dist").RenderTask | null>(null);
  const [numPages, setNumPages] = useState(0);
  const [page, setPage] = useState(() => highlight?.page ?? 1);
  const [canvasSize, setCanvasSize] = useState<{ width: number; height: number } | null>(null);
  const [error, setError] = useState("");
  const [docLoaded, setDocLoaded] = useState(false);

  // Cargar documento (una vez por fileUrl)
  useEffect(() => {
    let cancelled = false;
    setError("");
    fetch(fileUrl, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.arrayBuffer();
      })
      .then((data) => pdfjs.getDocument({ data }).promise)
      .then((pdf) => {
        if (cancelled) return;
        docRef.current = pdf;
        setNumPages(pdf.numPages);
        setDocLoaded(true);
        if (highlight && highlight.page >= 1 && highlight.page <= pdf.numPages) {
          setPage(highlight.page);
        } else {
          setPage(1);
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Error al abrir el PDF"));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileUrl, token]);

  // Render de la página actual
  useEffect(() => {
    const canvas = canvasRef.current;
    const pdf = docRef.current;
    if (!canvas || !pdf) return;
    let cancelled = false;
    renderTaskRef.current?.cancel();

    pdf.getPage(page).then((pdfPage) => {
      if (cancelled) return;
      const viewport = pdfPage.getViewport({ scale: SCALE });
      setCanvasSize({ width: viewport.width, height: viewport.height });
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.floor(viewport.width * ratio);
      canvas.height = Math.floor(viewport.height * ratio);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      const task = pdfPage.render({
        canvas,
        viewport,
        transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : undefined,
      });
      renderTaskRef.current = task;
      return task.promise.catch(() => undefined);
    });
    return () => {
      cancelled = true;
      renderTaskRef.current?.cancel();
    };
  }, [page]);

  // Sincronizar página al hacer clic en una cita
  useEffect(() => {
    if (highlight && highlight.page >= 1 && numPages > 0 && highlight.page !== page) {
      setPage(Math.min(highlight.page, numPages));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [highlight?.page, numPages]);

  const bbox = highlight && highlight.page === page ? highlight.bbox : null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-2">
        {numPages > 0 && (
          <div className="flex items-center gap-2 text-xs text-zinc-600">
            <button
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="rounded border border-zinc-200 px-2 py-0.5 hover:bg-zinc-50 disabled:opacity-40"
            >
              ←
            </button>
            <span>
              Página {page} / {numPages}
            </span>
            <button
              disabled={page >= numPages}
              onClick={() => setPage((p) => Math.min(numPages, p + 1))}
              className="rounded border border-zinc-200 px-2 py-0.5 hover:bg-zinc-50 disabled:opacity-40"
            >
              →
            </button>
          </div>
        )}
        <span className="text-[11px] text-zinc-400">Source Viewer · PDF</span>
      </div>

      {highlight && highlight.page === page && highlight.excerpt && (
        <div className="border-b border-indigo-200 bg-indigo-50 px-4 py-2 text-xs text-indigo-800">
          <span className="font-semibold">Evidencia · página {page}: </span>
          {highlight.excerpt.slice(0, 200)}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-auto bg-zinc-200 p-4">
        {error && <p className="text-sm text-red-600">{error}</p>}
        {!error && (
          <div
            className="relative mx-auto w-fit bg-white shadow-lg"
            style={{
              width: canvasSize ? `${canvasSize.width}px` : undefined,
              height: canvasSize ? `${canvasSize.height}px` : undefined,
            }}
          >
            {!docLoaded && !error && (
              <div className="flex items-center gap-2 p-6 text-sm text-zinc-500">
                <Spinner size={14} /> Cargando documento…
              </div>
            )}
            <canvas ref={canvasRef} />
            {bbox && (
              <div
                className="pointer-events-none absolute z-10 rounded-sm border-2 border-indigo-500 bg-indigo-400/20"
                style={{
                  left: `${bbox.x0 * SCALE}px`,
                  top: `${bbox.y0 * SCALE}px`,
                  width: `${(bbox.x1 - bbox.x0) * SCALE}px`,
                  height: `${(bbox.y1 - bbox.y0) * SCALE}px`,
                }}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}