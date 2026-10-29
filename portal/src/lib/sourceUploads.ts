import { api } from "../api";
import type { UploadItem } from "./uploadQueue";

export type UploadAuth = { token: string; organizationId: string };

export type SingleUploadOptions = {
  knowledgeBaseId?: string;
  corpusId?: string;
  force?: boolean;
  sessionId?: string;
  idempotencyKey?: string;
};

export type SingleUploadResult = {
  item: UploadItem;
  sessionId?: string;
  corpusId?: string;
};

/**
 * Un archivo por request. Reutiliza el endpoint canónico de Fuentes y devuelve
 * el resultado real por archivo, más la sesión/corpus cuando el backend los crea.
 */
export async function uploadSourceFile(
  file: File,
  auth: UploadAuth,
  opts: SingleUploadOptions = {},
): Promise<SingleUploadResult> {
  const form = new FormData();
  form.append("files", file);
  const params = new URLSearchParams();
  if (opts.knowledgeBaseId) params.set("knowledge_base_id", opts.knowledgeBaseId);
  if (opts.corpusId) params.set("corpus_id", opts.corpusId);
  if (opts.force) params.set("force", "true");
  if (opts.sessionId) params.set("session_id", opts.sessionId);
  if (opts.idempotencyKey) params.set("idempotency_key", opts.idempotencyKey);

  const out = await api<{
    items: UploadItem[];
    session_id?: string | null;
    corpus_id?: string | null;
  }>(`/api/v1/sources/files/upload-batch?${params.toString()}`, {
    method: "POST",
    token: auth.token,
    organizationId: auth.organizationId,
    body: form,
  });
  const item =
    (out.items || [])[0] ?? {
      filename: file.name,
      status: "error" as const,
      error: "El servidor no devolvió resultado para el archivo.",
    };
  return {
    item,
    sessionId: out.session_id ?? opts.sessionId,
    corpusId: out.corpus_id ?? opts.corpusId,
  };
}

/** Reprocesa una fuente ya recibida, sin volver a subir bytes. */
export async function resyncSource(
  sourceId: string,
  auth: UploadAuth,
): Promise<{ job_id: string; session_id?: string | null }> {
  return api<{ job_id: string; session_id?: string | null }>(
    `/api/v1/sources/${sourceId}/sync`,
    {
      method: "POST",
      token: auth.token,
      organizationId: auth.organizationId,
    },
  );
}
