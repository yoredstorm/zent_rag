import { CaretDown, Check, WarningCircle } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "../auth";
import { api, saveSession, type Session } from "../api";
import { IdentityTile } from "./Brand";
import { Popover } from "./ui/overlay";
import { Skeleton } from "./ui/states";
import { cn } from "./ui/cn";

type WorkspaceRow = {
  id: string;
  name: string;
  slug: string;
  kind: string;
  status: string;
};

const KIND_LABEL: Record<string, string> = {
  demo: "Demo",
  business: "Mi negocio",
};

export function WorkspaceSelector({ compact = false }: { compact?: boolean }) {
  const { session, applySession } = useAuth();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<WorkspaceRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [switching, setSwitching] = useState<string | null>(null);

  const company = session?.companyName?.trim() || "Mi workspace";
  const active = items.find((w) => w.id === session?.workspaceId);
  const label = active?.name || company;
  const kind = active?.kind || session?.workspaceKind || "business";

  const load = useCallback(() => {
    if (!session) return;
    setLoading(true);
    setError("");
    api<{ workspaces: WorkspaceRow[]; active_workspace_id?: string }>("/api/v1/workspaces", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => {
        setItems(data.workspaces || []);
        if (data.active_workspace_id && data.active_workspace_id !== session.workspaceId) {
          const row = (data.workspaces || []).find((w) => w.id === data.active_workspace_id);
          const next: Session = {
            ...session,
            workspaceId: data.active_workspace_id,
            workspaceKind: row?.kind || session.workspaceKind,
          };
          saveSession(next);
          applySession(next);
        }
      })
      .catch((err) => {
        setError(
          err instanceof Error
            ? err.message
            : "No pudimos cargar tus workspaces. Revisá la conexión e intentá de nuevo."
        );
      })
      .finally(() => setLoading(false));
  }, [session, applySession]);

  useEffect(() => {
    load();
  }, [load]);

  async function switchTo(ws: WorkspaceRow) {
    if (!session || ws.id === session.workspaceId) {
      setOpen(false);
      return;
    }
    setSwitching(ws.id);
    try {
      await api(`/api/v1/workspaces/active`, {
        method: "PUT",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ workspace_id: ws.id }),
      });
      const next: Session = { ...session, workspaceId: ws.id, workspaceKind: ws.kind };
      saveSession(next);
      applySession(next);
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No pudimos cambiar de workspace.");
    } finally {
      setSwitching(null);
    }
  }

  const trigger = compact ? (
    <button
      type="button"
      aria-label={`Workspace: ${label}. Cambiar workspace`}
      aria-expanded={open}
      className="mx-auto flex h-9 w-9 cursor-pointer items-center justify-center rounded-sm transition-colors duration-150 hover:bg-soft"
    >
      <IdentityTile label={label} kind="workspace" size={26} />
    </button>
  ) : (
    <button
      type="button"
      aria-expanded={open}
      aria-haspopup="dialog"
      className="group flex w-full cursor-pointer items-center gap-2.5 rounded-sm border border-border bg-control px-2 py-1.5 text-left transition-colors duration-200 hover:border-border-strong"
    >
      <IdentityTile label={label} kind="workspace" size={26} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-medium text-text">{label}</span>
        <span className="block truncate text-[11px] text-faint">
          {KIND_LABEL[kind] ?? kind}
        </span>
      </span>
      <CaretDown
        size={13}
        className="shrink-0 text-ghost transition-transform duration-200 group-aria-expanded:rotate-180"
        aria-hidden
      />
    </button>
  );

  return (
    <div data-tour="workspace-selector">
      <Popover
        trigger={trigger}
        open={open}
        onOpenChange={setOpen}
        align={compact ? "start" : "start"}
        side="bottom"
        width={compact ? 260 : undefined}
        className="w-full p-1"
      >
        <p className="eyebrow px-2.5 py-1.5">Workspaces</p>
        {loading && (
          <div className="flex flex-col gap-1.5 px-2 py-1.5">
            <Skeleton className="h-8" />
            <Skeleton className="h-8" />
          </div>
        )}
        {!loading && error && (
          <p className="flex items-start gap-2 px-2.5 py-2 text-[12.5px] text-danger" role="alert">
            <WarningCircle size={15} className="mt-px shrink-0" aria-hidden />
            {error}
          </p>
        )}
        {!loading && !error && items.length === 0 && (
          <p className="px-2.5 py-2 text-[12.5px] leading-relaxed text-muted">
            Todavía no hay workspaces en esta organización.
          </p>
        )}
        {!loading && !error && items.length > 0 && (
          <ul className="flex flex-col">
            {items.map((ws) => {
              const isActive = ws.id === session?.workspaceId;
              return (
                <li key={ws.id}>
                  <button
                    type="button"
                    onClick={() => void switchTo(ws)}
                    disabled={switching !== null}
                    aria-current={isActive ? "true" : undefined}
                    className={cn(
                      "flex w-full cursor-pointer items-center gap-2.5 rounded-sm px-2.5 py-2 text-left text-[13px] transition-colors duration-150 disabled:opacity-60",
                      isActive ? "bg-soft text-text" : "text-muted hover:bg-soft/60 hover:text-text"
                    )}
                  >
                    <IdentityTile label={ws.name} kind="workspace" size={22} />
                    <span className="min-w-0 flex-1 truncate">{ws.name}</span>
                    <span className="shrink-0 text-[11px] text-faint">
                      {switching === ws.id ? "Cambiando…" : kindLabel(ws.kind)}
                    </span>
                    {isActive && switching === null && (
                      <Check size={13} weight="bold" className="shrink-0 text-accent" aria-hidden />
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </Popover>
    </div>
  );
}

function kindLabel(kind: string): string {
  return KIND_LABEL[kind] ?? (kind === "demo" ? "Demo" : "Negocio");
}
