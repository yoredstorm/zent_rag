import type { Icon } from "@phosphor-icons/react";
import {
  ArrowsClockwise,
  CheckCircle,
  FileText,
  Key,
  Scroll,
  UsersThree,
  Warning,
  WarningCircle,
  XCircle,
} from "@phosphor-icons/react";
import { fmtDateTime } from "../lib/format";

export type TimelineItem = {
  id: string;
  at: string;
  title: string;
  detail?: string;
  kind?: "audit" | "deployment" | "job" | "billing" | "key" | "user" | "notification" | "feedback" | "spike";
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
  feedback: Warning,
  spike: Warning,
};

/** El tono no viaja solo: cada valor lleva icono + etiqueta además del color. */
const TONE_META: Partial<
  Record<NonNullable<TimelineItem["tone"]>, { label: string; chip: string; icon: Icon }>
> = {
  ok: { label: "Correcto", chip: "badge badge-ok", icon: CheckCircle },
  warn: { label: "Atención", chip: "badge badge-pending", icon: WarningCircle },
  danger: { label: "Error", chip: "badge badge-danger", icon: XCircle },
};

const MARKER_CLASS: Record<NonNullable<TimelineItem["tone"]>, string> = {
  ok: "border-ok/30 bg-ok-soft text-ok",
  warn: "border-warn/30 bg-warn-soft text-warn",
  danger: "border-danger/30 bg-danger-soft text-danger",
  default: "border-border-strong bg-raised text-muted",
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
 * Timeline de actividad agrupado por día. Consume eventos reales del tenant
 * (audit, deployments, jobs, billing, keys, usuarios, notificaciones).
 */
export function Timeline({ items }: { items: TimelineItem[] }) {
  const sorted = [...items].sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime());
  if (sorted.length === 0) {
    return (
      <div className="px-4 py-6">
        <p className="text-sm text-muted">Sin actividad registrada.</p>
        <p className="mt-1 text-xs leading-relaxed text-faint">
          Los eventos aparecen acá cuando la organización registra actividad auditable.
        </p>
      </div>
    );
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
        <section key={group.label} aria-label={group.label} className="mb-4 last:mb-0">
          <p className="eyebrow mb-2 flex items-baseline gap-2">
            {group.label}
            <span className="font-normal text-ghost tabular-nums">{group.items.length}</span>
          </p>
          <ol className="relative ml-2 border-l border-border-soft">
            {group.items.map((item) => {
              const IconEl = item.kind ? KIND_ICONS[item.kind] : Warning;
              const tone = item.tone ?? "default";
              const meta = TONE_META[tone];
              return (
                <li key={item.id} className="relative ml-4 pb-4 pl-4 last:pb-1">
                  <span
                    className={`absolute top-0.5 -left-[9px] flex h-4 w-4 items-center justify-center rounded-full border-2 border-surface ${MARKER_CLASS[tone]}`}
                    aria-hidden
                  >
                    <IconEl size={9} weight="fill" aria-hidden />
                  </span>
                  <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                    <p className="text-sm font-medium text-text">{item.title}</p>
                    <div className="flex shrink-0 items-center gap-2">
                      {meta && (
                        <span className={meta.chip}>
                          <meta.icon size={12} weight="fill" aria-hidden />
                          {meta.label}
                        </span>
                      )}
                      <time dateTime={item.at} className="text-xs text-faint tabular-nums">
                        {fmtDateTime(item.at)}
                      </time>
                    </div>
                  </div>
                  {item.detail && (
                    <p className="mt-0.5 max-w-[68ch] text-[13px] leading-relaxed text-muted">{item.detail}</p>
                  )}
                </li>
              );
            })}
          </ol>
        </section>
      ))}
    </div>
  );
}
