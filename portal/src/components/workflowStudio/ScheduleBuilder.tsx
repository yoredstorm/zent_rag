/**
 * ScheduleBuilder — "¿Cuándo debe ejecutarse?" en lenguaje de negocio.
 * Escribe `config.schedule` (FriendlySchedule); el guardado lo convierte al
 * `trigger_config` que ya usa el scheduler v2. No hay cron visible hasta
 * Advanced.
 */
import { Clock } from "@phosphor-icons/react";
import {
  DAY_NAMES,
  SCHEDULE_MODES,
  TIMEZONES,
  describeSchedule,
  scheduleFromNodeConfig,
  type FriendlySchedule,
  type ScheduleMode,
} from "../../lib/scheduleBuilder";

type Props = {
  config: Record<string, unknown>;
  onChange: (patch: Record<string, unknown>) => void;
};

export function ScheduleBuilder({ config, onChange }: Props) {
  const schedule = scheduleFromNodeConfig(config);
  const update = (patch: Partial<FriendlySchedule>) => onChange({ schedule: { ...schedule, ...patch } });

  return (
    <div className="space-y-2.5" data-testid="wf-schedule-builder">
      <label className="block">
        <span className="mb-0.5 block text-[10px] font-medium text-muted">¿Cuándo debe ejecutarse?</span>
        <select
          className="w-full rounded-md border border-border bg-soft px-2 py-2 text-[11px]"
          value={schedule.mode}
          data-testid="wf-schedule-mode"
          onChange={(e) => update({ mode: e.target.value as ScheduleMode })}
        >
          {SCHEDULE_MODES.map((mode) => (
            <option key={mode.value} value={mode.value}>{mode.label}</option>
          ))}
        </select>
      </label>

      {schedule.mode === "interval" && (
        <div className="flex items-center gap-2">
          <input
            className="w-20 rounded-md border border-border bg-soft px-2 py-1.5 text-[11px]"
            type="number"
            min={1}
            value={intervalValue(schedule)}
            data-testid="wf-schedule-interval"
            aria-label="Intervalo"
            onChange={(e) => {
              const raw = Math.max(1, Number(e.target.value || 1));
              update(
                intervalUnit(schedule) === "hours"
                  ? { every_minutes: raw * 60 }
                  : { every_minutes: raw },
              );
            }}
          />
          <select
            className="rounded-md border border-border bg-soft px-2 py-1.5 text-[11px]"
            value={intervalUnit(schedule)}
            aria-label="Unidad"
            onChange={(e) => {
              const base = intervalValue(schedule);
              update({ every_minutes: e.target.value === "hours" ? base * 60 : base });
            }}
          >
            <option value="minutes">minutos</option>
            <option value="hours">horas</option>
          </select>
        </div>
      )}

      {(schedule.mode === "daily" || schedule.mode === "weekly" || schedule.mode === "monthly") && (
        <label className="block">
          <span className="mb-0.5 block text-[10px] font-medium text-muted">Hora</span>
          <input
            className="w-32 rounded-md border border-border bg-soft px-2 py-1.5 text-[11px]"
            type="time"
            value={schedule.time ?? "08:00"}
            data-testid="wf-schedule-time"
            onChange={(e) => update({ time: e.target.value })}
          />
        </label>
      )}

      {schedule.mode === "weekly" && (
        <div>
          <span className="mb-1 block text-[10px] font-medium text-muted">Días</span>
          <div className="flex flex-wrap gap-1" data-testid="wf-schedule-days">
            {DAY_NAMES.map((name, index) => {
              const active = (schedule.days ?? []).includes(index);
              return (
                <button
                  key={name}
                  type="button"
                  className={`rounded border px-1.5 py-0.5 text-[10px] ${
                    active ? "border-accent bg-accent/15 text-text" : "border-border text-muted hover:text-text"
                  }`}
                  aria-pressed={active}
                  data-testid={`wf-schedule-day-${index}`}
                  onClick={() => {
                    const current = new Set(schedule.days ?? []);
                    if (current.has(index)) current.delete(index);
                    else current.add(index);
                    update({ days: [...current].sort((a, b) => a - b) });
                  }}
                >
                  {name.slice(0, 3)}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {schedule.mode === "monthly" && (
        <label className="block">
          <span className="mb-0.5 block text-[10px] font-medium text-muted">Día del mes</span>
          <input
            className="w-20 rounded-md border border-border bg-soft px-2 py-1.5 text-[11px]"
            type="number"
            min={1}
            max={31}
            value={schedule.day_of_month ?? 1}
            data-testid="wf-schedule-day-of-month"
            onChange={(e) => update({ day_of_month: Math.max(1, Math.min(31, Number(e.target.value || 1))) })}
          />
        </label>
      )}

      {schedule.mode === "cron" && (
        <label className="block">
          <span className="mb-0.5 block text-[10px] font-medium text-muted">Expresión cron (min hora día mes día-semana)</span>
          <input
            className="w-full rounded-md border border-border bg-soft px-2 py-1.5 font-mono text-[10px]"
            value={schedule.cron ?? "0 9 * * *"}
            data-testid="wf-schedule-cron"
            onChange={(e) => update({ cron: e.target.value })}
          />
        </label>
      )}

      <label className="block">
        <span className="mb-0.5 block text-[10px] font-medium text-muted">Zona horaria</span>
        <select
          className="w-full rounded-md border border-border bg-soft px-2 py-2 text-[11px]"
          value={schedule.timezone}
          data-testid="wf-schedule-timezone"
          onChange={(e) => update({ timezone: e.target.value })}
        >
          {TIMEZONES.map((tz) => (
            <option key={tz.value} value={tz.value}>{tz.label}</option>
          ))}
        </select>
      </label>

      <p className="flex items-start gap-1 rounded-md border border-accent/30 bg-accent/5 px-2 py-1.5 text-[10px] text-muted" data-testid="wf-schedule-preview">
        <Clock size={12} className="mt-0.5 shrink-0 text-accent" aria-hidden />
        <span>
          Se ejecutará {describeSchedule(schedule)}
          {describeSchedule(schedule).endsWith(".") ? "" : "."}
        </span>
      </p>
    </div>
  );
}

function intervalUnit(schedule: FriendlySchedule): "minutes" | "hours" {
  const minutes = Number(schedule.every_minutes ?? 5);
  return minutes >= 60 && minutes % 60 === 0 ? "hours" : "minutes";
}

function intervalValue(schedule: FriendlySchedule): number {
  const minutes = Number(schedule.every_minutes ?? 5);
  return intervalUnit(schedule) === "hours" ? minutes / 60 : minutes;
}
