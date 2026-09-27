import { X } from "@phosphor-icons/react";
import { Button, ButtonLink, IconButton, cn } from "./ui";
import { UPLOAD_STATUS_LABEL, type UploadItem } from "../lib/uploadQueue";

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
          className="flex flex-wrap items-center gap-2 rounded-sm bg-soft px-2.5 py-1.5 text-[12.5px] text-text"
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
          className="flex flex-wrap items-center gap-2 rounded-sm border border-border-soft px-2.5 py-2 text-[12.5px]"
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
