import { isApiError } from "./errors";

export type UploadItem = {
  filename: string;
  status: "created" | "duplicate" | "rejected" | "error";
  source_id?: string | null;
  job_id?: string | null;
  name?: string | null;
  error?: string | null;
  existing_source_id?: string | null;
  existing_name?: string | null;
};

export const UPLOAD_STATUS_LABEL: Record<UploadItem["status"], string> = {
  created: "En cola de indexado",
  duplicate: "Ya existe",
  rejected: "Rechazado",
  error: "Error",
};

export const MAX_UPLOAD_MB = 25;
export const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;

export function uploadErrorMessage(err: unknown): string {
  if (isApiError(err) && err.status === 413) {
    return `Supera el máximo por archivo (${MAX_UPLOAD_MB} MB). Prueba con uno más chico.`;
  }
  return err instanceof Error ? err.message : "Error al subir";
}

/** Suma archivos sin duplicar por nombre+tamaño. */
export function mergeSelectedFiles(prev: File[], incoming: FileList | File[]): File[] {
  const seen = new Set(prev.map((f) => `${f.name}:${f.size}`));
  return [
    ...prev,
    ...Array.from(incoming).filter((f) => !seen.has(`${f.name}:${f.size}`)),
  ];
}

export function isOversized(file: File): boolean {
  return file.size > MAX_UPLOAD_BYTES;
}

/** Estado vivo de un archivo en la cola de subida/indexado. */
export type UploadRowStatus =
  | "pending"
  | "uploading"
  | "created"
  | "indexing"
  | "indexed"
  | "duplicate"
  | "rejected"
  | "error"
  | "failed";

export type UploadQueueRow = {
  id: string;
  filename: string;
  size: number;
  status: UploadRowStatus;
  progress: number;
  name?: string | null;
  jobId?: string | null;
  sourceId?: string | null;
  existingSourceId?: string | null;
  error?: string | null;
};

export const UPLOAD_ROW_LABEL: Record<UploadRowStatus, string> = {
  pending: "En espera",
  uploading: "Subiendo",
  created: "En cola de indexado",
  indexing: "Indexando",
  indexed: "Indexado",
  duplicate: "Ya existe",
  rejected: "Rechazado",
  error: "Error",
  failed: "Error de indexado",
};

export function rowLabel(row: UploadQueueRow): string {
  const base = UPLOAD_ROW_LABEL[row.status];
  const withPercent = row.status === "uploading" || row.status === "indexing";
  return withPercent && row.progress > 0 ? `${base} ${Math.round(row.progress)}%` : base;
}

/** ¿La fila ya no va a cambiar sola? (para cortar el poll de indexado) */
export function rowSettled(row: UploadQueueRow): boolean {
  return ["indexed", "failed", "duplicate", "rejected", "error"].includes(row.status);
}

export function fileRowId(file: File): string {
  return `${file.name}:${file.size}`;
}

export function newUploadRow(file: File, status: UploadRowStatus = "pending"): UploadQueueRow {
  return {
    id: fileRowId(file),
    filename: file.name,
    size: file.size,
    status,
    progress: 0,
  };
}

/** Estado de un job de indexado → estado de la fila. */
export function jobRowStatus(
  jobStatus?: string | null,
  progress?: number | null,
): UploadRowStatus {
  if (jobStatus === "completed" || jobStatus === "succeeded") return "indexed";
  if (jobStatus === "failed" || jobStatus === "dead" || jobStatus === "error") return "failed";
  if (jobStatus === "running" || jobStatus === "processing") return "indexing";
  if (typeof progress === "number" && progress >= 100) return "indexed";
  return "created";
}

/** Barra global de subida: bytes enviados (completos + los del archivo activo). */
export function overallUploadProgress(rows: UploadQueueRow[]): number {
  const totalBytes = rows.reduce((sum, row) => sum + row.size, 0);
  if (totalBytes <= 0) return 0;
  const sentBytes = rows.reduce((sum, row) => {
    if (row.status === "pending" || row.status === "rejected") return sum;
    if (row.status === "uploading") return sum + (row.size * row.progress) / 100;
    return sum + row.size;
  }, 0);
  return Math.max(0, Math.min(100, Math.round((sentBytes / totalBytes) * 100)));
}

/** Barra global de indexado: avance de los jobs (0/50/100 del worker). */
export function overallIndexProgress(rows: UploadQueueRow[]): number {
  const relevant = rows.filter(
    (row) => !["pending", "uploading", "rejected", "error", "duplicate"].includes(row.status),
  );
  if (relevant.length === 0) return 0;
  const value = relevant.reduce((sum, row) => {
    if (row.status === "indexed") return sum + 100;
    return sum + Math.max(0, Math.min(100, row.progress));
  }, 0);
  return Math.round(value / relevant.length);
}

/** Filas de solo lectura desde el progreso por archivo del backend. */
export function rowsFromJobFiles(
  files: Array<{
    job_id?: string | null;
    filename?: string | null;
    job_status?: string | null;
    job_progress?: number | null;
  }>,
): UploadQueueRow[] {
  return files.map((file, index) => ({
    id: String(file.job_id ?? file.filename ?? index),
    filename: file.filename ?? "archivo",
    size: 0,
    status: jobRowStatus(file.job_status, file.job_progress),
    progress: typeof file.job_progress === "number" ? file.job_progress : 0,
  }));
}

export type UploadSummary = {
  total: number;
  uploaded: number;
  pending: number;
  queued: number;
  indexing: number;
  indexed: number;
  failed: number;
  uploading: UploadQueueRow | undefined;
  percent: number;
};

export function uploadSummary(rows: UploadQueueRow[]): UploadSummary {
  const uploaded = rows.filter(
    (row) => !["pending", "uploading", "rejected"].includes(row.status),
  ).length;
  return {
    total: rows.length,
    uploaded,
    pending: rows.filter((row) => row.status === "pending").length,
    queued: rows.filter((row) => row.status === "created").length,
    indexing: rows.filter((row) => row.status === "indexing").length,
    indexed: rows.filter((row) => row.status === "indexed").length,
    failed: rows.filter((row) => row.status === "failed" || row.status === "error").length,
    uploading: rows.find((row) => row.status === "uploading"),
    percent: overallUploadProgress(rows),
  };
}
