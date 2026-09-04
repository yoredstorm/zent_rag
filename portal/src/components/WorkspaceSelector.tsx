import { CaretDown, Building } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth";

export function WorkspaceSelector() {
  const { session } = useAuth();
  const company = session?.companyName?.trim() || "Mi workspace";
  const initial = company.charAt(0).toUpperCase();

  return (
    <Link
      to="/workspaces"
      className="group flex items-center gap-2.5 rounded-md border border-border bg-soft px-2.5 py-2 transition-colors duration-150 hover:border-border-strong hover:bg-raised"
      title="Administrar workspaces"
    >
      <span
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-sm bg-accent-soft text-xs font-semibold text-accent"
        aria-hidden
      >
        {initial}
      </span>
      <span className="min-w-0 flex-1 text-left">
        <span className="block truncate text-[13px] font-medium text-text">{company}</span>
        <span className="flex items-center gap-1 text-[11px] text-muted">
          <Building size={11} aria-hidden />
          Production Workspace
        </span>
      </span>
      <CaretDown
        size={14}
        className="shrink-0 text-faint transition-transform duration-150 group-hover:text-muted"
        aria-hidden
      />
    </Link>
  );
}