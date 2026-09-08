import { CaretDown } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "../auth";
import { api, saveSession, type Session } from "../api";

type WorkspaceRow = {
  id: string;
  name: string;
  slug: string;
  kind: string;
  status: string;
};

export function WorkspaceSelector() {
  const { session, applySession } = useAuth();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<WorkspaceRow[]>([]);
  const company = session?.companyName?.trim() || "Mi workspace";
  const active = items.find((w) => w.id === session?.workspaceId);
  const label = active?.name || company;
  const kind = active?.kind || session?.workspaceKind || "business";
  const initial = label.charAt(0).toUpperCase();

  const load = useCallback(() => {
    if (!session) return;
    api<{ workspaces: WorkspaceRow[]; active_workspace_id?: string }>(
      "/api/v1/workspaces",
      { token: session.token, organizationId: session.organizationId }
    )
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
      .catch(() => undefined);
  }, [session, applySession]);

  useEffect(() => {
    load();
  }, [load]);

  async function switchTo(ws: WorkspaceRow) {
    if (!session) return;
    await api(`/api/v1/workspaces/active`, {
      method: "PUT",
      token: session.token,
      organizationId: session.organizationId,
      body: JSON.stringify({ workspace_id: ws.id }),
    });
    const next: Session = {
      ...session,
      workspaceId: ws.id,
      workspaceKind: ws.kind,
    };
    saveSession(next);
    applySession(next);
    setOpen(false);
  }

  return (
    <div className="relative">
      <button
        type="button"
        className="group flex w-full items-center gap-2.5 rounded-md border border-border bg-soft px-2.5 py-2 text-left transition-colors duration-150 hover:border-border-strong hover:bg-raised"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-sm bg-accent-soft text-xs font-semibold text-accent"
          aria-hidden
        >
          {initial}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-medium text-text">{label}</span>
          <span className="flex items-center gap-1 text-[11px] text-muted">
            {kind === "demo" ? "Demo" : "Mi negocio"}
          </span>
        </span>
        <CaretDown
          size={14}
          className="shrink-0 text-faint transition-transform duration-150 group-hover:text-muted"
          aria-hidden
        />
      </button>
      {open && (
        <ul className="absolute z-30 mt-1 w-full rounded-md border border-border bg-surface py-1 shadow-lg">
          {items.map((ws) => (
            <li key={ws.id}>
              <button
                type="button"
                className={`flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-soft ${
                  ws.id === session?.workspaceId ? "text-accent" : "text-text"
                }`}
                onClick={() => void switchTo(ws)}
              >
                <span>{ws.name}</span>
                <span className="text-[11px] text-muted">
                  {ws.kind === "demo" ? "Demo" : "Negocio"}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
