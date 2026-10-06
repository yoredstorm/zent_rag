import { X } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { Button, ButtonLink, IconButton, StatusRow, cn } from "./ui";
import {
  UPLOAD_STATUS_LABEL,
  rowLabel,
  type UploadItem,
  type UploadQueueRow,
  type UploadRowStatus,
} from "../lib/uploadQueue";

const ROW_STATE: Record<
  UploadRowStatus,
  "queued" | "running" | "ready" | "warning" | "failed" | "processing" | "indexing"
> = {
  pending: "queued",
  uploading: "running",
  created: "queued",
  indexing: "indexing",
  indexed: "ready",
  duplicate: "warning",
  rejected: "failed",
  error: "failed",
  failed: "failed",
};

const ROW_TONE: Record<UploadRowStatus, string> = {
  pending: "text-faint",
  uploading: "text-accent",
  created: "text-muted",
  indexing: "text-accent",
  indexed: "text-ok",
  duplicate: "text-warn",
  rejected: "text-danger",
  error: "text-danger",
  failed: "text-danger",
};

const RETRYABLE: UploadRowStatus[] = ["rejected", "error", "failed", "duplicate"];
const REMOVABLE: UploadRowStatus[] = ["pending", "rejected", "error", "failed", "duplicate"];

function formatKb(size: number): string {
  return `${Math.max(1, Math.round(size / 1024))} KB`;
}

/** Cola viva de subida/indexado: una fila por archivo, con barra real. */
export function UploadQueueList({
  rows,
  onRemove,
  onRetry,
  retrying,
  testId = "upload-queue",
  className,
}: {
  rows: UploadQueueRow[];
  onRemove?: (row: UploadQueueRow) => void;
  onRetry?: (row: UploadQueueRow) => void;
  retrying?: string;
  testId?: string;
  className?: string;
}) {
  if (rows.length === 0) return null;
  return (
    <div className={cn("flex flex-col", className)} data-testid={testId}>
      {rows.map((row, index) => {
        const state = ROW_STATE[row.status];
        const showBar = row.status === "uploading" || row.status === "indexing";
        let actions: ReactNode = null;
        if (onRetry && RETRYABLE.includes(row.status)) {
          actions = (
            <>
              {row.status === "duplicate" && row.existingSourceId && (
                <ButtonLink
                  to={`/knowledge/sources/${row.existingSourceId}`}
                  variant="secondary"
                  size="sm"
                >
                  Abrir existente
                </ButtonLink>
              )}
              <Button
                variant="secondary"
                size="sm"
                loading={retrying === row.id}
                onClick={() => onRetry(row)}
              >
                {row.status === "duplicate" ? "Subir igual" : "Reintentar"}
              </Button>
            </>
          );
        }
        if (onRemove && REMOVABLE.includes(row.status)) {
          actions = (
            <>
              {actions}
              <IconButton
                label={`Quitar ${row.filename}`}
                icon={X}
                onClick={() => onRemove(row)}
              />
            </>
          );
        }
        return (
          <StatusRow
            key={row.id}
            state={state}
            className="up-row border-b border-border-soft last:border-b-0"
            style={{ animationDelay: `${Math.min(index, 8) * 40}ms` }}
            title={
              <>
                <span
                  className="min-w-0 max-w-[22rem] truncate text-[13px] font-medium text-text"
                  title={row.filename}
                >
                  {row.name || row.filename}
                </span>
                <span className="mono text-[11px] text-faint">
                  {row.size > 0 ? formatKb(row.size) : null}
                </span>
                <span
                  className={cn("up-row-status text-[11px]", ROW_TONE[row.status])}
                  data-testid={`upload-row-status-${row.id}`}
                >
                  {rowLabel(row)}
                </span>
                {row.error && (
                  <span className="w-full text-[11px] leading-relaxed text-danger">
                    {row.error}
                  </span>
                )}
              </>
            }
            progress={showBar ? row.progress : undefined}
            actions={actions}
          />
        );
      })}
    </div>
  );
}

export function SelectedFilesList({
  files,
  onRemove,
  className,
}: {
  files: File[];
  onRemove: (file: File) => void;
  className?: string;
}) {
  if (files.length === 0) return null;
  return (
    <ul className={cn("flex max-h-48 flex-col gap-1 overflow-y-auto", className)}>
      {files.map((item) => (
        <li
          key={`${item.name}-${item.size}`}
          className="animate-rise flex flex-wrap items-center gap-2 rounded-sm bg-soft px-2.5 py-1.5 text-[12.5px] text-text"
        >
          <span className="min-w-0 flex-1 truncate">{item.name}</span>
          <span className="text-[11px] text-faint">
            {Math.max(1, Math.round(item.size / 1024))} KB
          </span>
          <IconButton
            label={`Quitar ${item.name}`}
            icon={X}
            onClick={() => onRemove(item)}
          />
        </li>
      ))}
    </ul>
  );
}

export function UploadResultsList({
  items,
  retrying,
  onRetry,
  testId = "upload-results",
  className,
}: {
  items: UploadItem[];
  retrying?: string;
  onRetry: (item: UploadItem) => void;
  testId?: string;
  className?: string;
}) {
  if (items.length === 0) return null;
  return (
    <ul
      className={cn("flex max-h-48 flex-col gap-1.5 overflow-y-auto", className)}
      data-testid={testId}
    >
      {items.map((item) => (
        <li
          key={item.filename}
          className="animate-rise flex flex-wrap items-center gap-2 rounded-sm border border-border-soft px-2.5 py-2 text-[12.5px]"
        >
          <span className="min-w-0 flex-1 truncate text-text">
            {item.name || item.filename}
          </span>
          <span
            className={
              item.status === "created"
                ? "text-ok"
                : item.status === "duplicate"
                  ? "text-warn"
                  : "text-danger"
            }
          >
            {UPLOAD_STATUS_LABEL[item.status]}
          </span>
          {item.status === "duplicate" && item.existing_source_id && (
            <>
              <ButtonLink
                to={`/knowledge/sources/${item.existing_source_id}`}
                variant="secondary"
              >
                Abrir existente
              </ButtonLink>
              <Button
                variant="secondary"
                size="sm"
                loading={retrying === item.filename}
                onClick={() => onRetry(item)}
              >
                Subir igual
              </Button>
            </>
          )}
          {(item.status === "rejected" || item.status === "error") && item.error && (
            <span className="text-[11px] text-danger">{item.error}</span>
          )}
        </li>
      ))}
    </ul>
  );
}
