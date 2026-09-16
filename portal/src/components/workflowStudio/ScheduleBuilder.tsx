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
import { Input, Select } from "../ui";

type Props = {
  config: Record<string, unknown>;
  onChange: (patch: Record<string, unknown>) => void;
};

export function ScheduleBuilder({ config, onChange }: Props) {
  const schedule = scheduleFromNodeConfig(config);
  const update = (patch: Partial<FriendlySchedule>) => onChange({ schedule: { ...schedule, ...patch } });

  return (
    <div className="space-y-3" data-testid="wf-schedule-builder">
      <div className="space-y-1.5">
        <label htmlFor="wf-schedule-mode" className="text-[13px] font-medium text-text">
          ¿Cuándo debe ejecutarse?
        </label>
        <Select
          id="wf-schedule-mode"
          value={schedule.mode}
          data-testid="wf-schedule-mode"
          onChange={(e) => update({ mode: e.target.value as ScheduleMode })}
        >
          {SCHEDULE_MODES.map((mode) => (
            <option key={mode.value} value={mode.value}>{mode.label}</option>
          ))}
        </Select>
      </div>

      {schedule.mode === "interval" && (
        <div className="space-y-1.5">
          <span className="text-[13px] font-medium text-text">Cada</span>
          <div className="flex items-center gap-2">
            <Input
              className="w-20"
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
            <Select
              className="w-auto"
              value={intervalUnit(schedule)}
              aria-label="Unidad"
              onChange={(e) => {
                const base = intervalValue(schedule);
                update({ every_minutes: e.target.value === "hours" ? base * 60 : base });
              }}
            >
              <option value="minutes">minutos</option>
              <option value="hours">horas</option>
            </Select>
          </div>
        </div>
      )}

      {(schedule.mode === "daily" || schedule.mode === "weekly" || schedule.mode === "monthly") && (
        <div className="space-y-1.5">
          <label htmlFor="wf-schedule-time" className="text-[13px] font-medium text-text">
            Hora
          </label>
          <Input
            id="wf-schedule-time"
            className="w-32"
            type="time"
            value={schedule.time ?? "08:00"}
            data-testid="wf-schedule-time"
            onChange={(e) => update({ time: e.target.value })}
          />
        </div>
      )}

      {schedule.mode === "weekly" && (
        <div className="space-y-1.5">
          <span className="text-[13px] font-medium text-text">Días</span>
          <div className="flex flex-wrap gap-1" data-testid="wf-schedule-days">
            {DAY_NAMES.map((name, index) => {
              const active = (schedule.days ?? []).includes(index);
              return (
                <button
                  key={name}
                  type="button"
                  className={`min-h-7 cursor-pointer rounded-sm border px-2 text-[12px] transition-colors duration-150 ${
                    active
                      ? "border-accent-line bg-accent-soft text-accent"
                      : "border-border text-muted hover:border-border-strong hover:text-text"
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
        <div className="space-y-1.5">
          <label htmlFor="wf-schedule-day-of-month" className="text-[13px] font-medium text-text">
            Día del mes
          </label>
          <Input
            id="wf-schedule-day-of-month"
            className="w-20"
            type="number"
            min={1}
            max={31}
            value={schedule.day_of_month ?? 1}
            data-testid="wf-schedule-day-of-month"
            onChange={(e) => update({ day_of_month: Math.max(1, Math.min(31, Number(e.target.value || 1))) })}
          />
        </div>
      )}

      {schedule.mode === "cron" && (
        <div className="space-y-1.5">
          <label htmlFor="wf-schedule-cron" className="text-[13px] font-medium text-text">
            Expresión cron (min hora día mes día-semana)
          </label>
          <Input
            id="wf-schedule-cron"
            className="font-mono text-[12px]"
            value={schedule.cron ?? "0 9 * * *"}
            data-testid="wf-schedule-cron"
            onChange={(e) => update({ cron: e.target.value })}
          />
        </div>
      )}

      <div className="space-y-1.5">
        <label htmlFor="wf-schedule-timezone" className="text-[13px] font-medium text-text">
          Zona horaria
        </label>
        <Select
          id="wf-schedule-timezone"
          value={schedule.timezone}
          data-testid="wf-schedule-timezone"
          onChange={(e) => update({ timezone: e.target.value })}
        >
          {TIMEZONES.map((tz) => (
            <option key={tz.value} value={tz.value}>{tz.label}</option>
          ))}
        </Select>
      </div>

      <p
        className="flex items-start gap-1.5 rounded-md border border-accent-line bg-accent-soft/60 px-2.5 py-2 text-[12px] leading-relaxed text-muted"
        data-testid="wf-schedule-preview"
      >
        <Clock size={13} className="mt-0.5 shrink-0 text-accent" aria-hidden />
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
