import type { Icon } from "@phosphor-icons/react";
import { ArrowsClockwise, FileText, Key, Scroll, UsersThree, Warning } from "@phosphor-icons/react";
import { fmtDateTime } from "../lib/format";

export type TimelineItem = {
  id: string;
  at: string;
  title: string;
  detail?: string;
  kind?: "audit" | "deployment" | "job" | "billing" | "key" | "user" | "notification";
  tone?: "ok" | "warn" | "danger" | "default";
};

const KIND_ICONS: Record<NonNullable<TimelineItem["kind"]>, Icon> = {
  audit: Scroll,
  deployment: ArrowsClockwise,
  job: ArrowsClockwise,
  billing: FileText,
  key: Key,
  user: UsersThree,
  notification: Warning,
};

function dayLabel(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  const same = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  if (same(d, today)) return "Hoy";
  if (same(d, yesterday)) return "Ayer";
  return d.toLocaleDateString("es-PE", { day: "2-digit", month: "short", year: "numeric" });
}

/**
 * Timeline de actividad por día. Consume eventos reales del tenant
 * (audit, deployments, jobs, billing, keys, usuarios, notificaciones).
 */
export function Timeline({ items }: { items: TimelineItem[] }) {
  const sorted = [...items].sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime());
  if (sorted.length === 0) {
    return <p className="px-4 py-6 text-sm text-muted">Sin actividad registrada.</p>;
  }

  const groups: { label: string; items: TimelineItem[] }[] = [];
  for (const item of sorted) {
    const label = dayLabel(item.at);
    const last = groups[groups.length - 1];
    if (last && last.label === label) last.items.push(item);
    else groups.push({ label, items: [item] });
  }

  return (
    <div className="px-4 py-3">
      {groups.map((group) => (
        <div key={group.label} className="mb-4">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-faint">
            {group.label}
          </p>
          <ol className="relative ml-3 border-l border-border">
            {group.items.map((item) => {
              const IconEl = item.kind ? KIND_ICONS[item.kind] : Warning;
              const dotTone =
                item.tone === "ok"
                  ? "bg-ok"
                  : item.tone === "danger"
                    ? "bg-danger"
                    : item.tone === "warn"
                      ? "bg-warn"
                      : "bg-border-strong";
              return (
                <li key={item.id} className="relative ml-3 pb-4 pl-4 last:pb-1">
                  <span
                    className={`absolute -left-[7px] top-1 flex h-3.5 w-3.5 items-center justify-center rounded-full border-2 border-surface ${dotTone}`}
                    aria-hidden
                  >
                    <IconEl size={8} className="text-bg" aria-hidden />
                  </span>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-medium text-text">{item.title}</p>
                    <span className="shrink-0 text-xs text-faint">{fmtDateTime(item.at)}</span>
                  </div>
                  {item.detail && <p className="mt-0.5 text-[13px] text-muted">{item.detail}</p>}
                </li>
              );
            })}
          </ol>
        </div>
      ))}
    </div>
  );
}