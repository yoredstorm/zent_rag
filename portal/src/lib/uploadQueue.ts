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
