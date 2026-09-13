/**
 * Schedule Builder — representación amigable del schedule que ya entiende el
 * scheduler v2 (`daily`/`weekly`/`monthly`/`cron`/`every_minutes`).
 * No crea otro scheduler: solo edita la config del nodo trigger_schedule y la
 * convierte a `trigger_config` al guardar.
 */

export type ScheduleMode = "interval" | "daily" | "weekly" | "monthly" | "cron";

export type FriendlySchedule = {
  mode: ScheduleMode;
  every_minutes?: number;
  time?: string;
  days?: number[];
  day_of_month?: number;
  timezone: string;
  cron?: string;
};

export const TIMEZONES: { value: string; label: string }[] = [
  { value: "America/Lima", label: "Lima (GMT-5)" },
  { value: "America/Bogota", label: "Bogotá (GMT-5)" },
  { value: "America/Mexico_City", label: "Ciudad de México (GMT-6)" },
  { value: "America/Argentina/Buenos_Aires", label: "Buenos Aires (GMT-3)" },
  { value: "America/Santiago", label: "Santiago (GMT-3/-4)" },
  { value: "America/Sao_Paulo", label: "São Paulo (GMT-3)" },
  { value: "UTC", label: "UTC" },
];

export const DAY_NAMES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];

export const SCHEDULE_MODES: { value: ScheduleMode; label: string }[] = [
  { value: "interval", label: "Cada cierto tiempo" },
  { value: "daily", label: "Todos los días" },
  { value: "weekly", label: "Algunos días de la semana" },
  { value: "monthly", label: "Cada mes" },
  { value: "cron", label: "Configuración avanzada" },
];

function friendlyTime(raw: string | undefined): string {
  const value = String(raw ?? "00:00");
  const [hhRaw, mm = "00"] = value.split(":");
  const hh = Number(hhRaw);
  if (!Number.isFinite(hh)) return value;
  const suffix = hh < 12 ? "a. m." : "p. m.";
  return `${hh % 12 || 12}:${mm} ${suffix}`;
}

export function scheduleFromNodeConfig(config: Record<string, unknown>): FriendlySchedule {
  const stored = config.schedule as FriendlySchedule | undefined;
  if (stored && typeof stored === "object" && stored.mode) {
    return { ...stored, timezone: stored.timezone || "UTC" };
  }
  const timezone = String(config.timezone ?? "UTC");
  const every = Number(config.every_minutes);
  if (Number.isFinite(every) && every > 0) {
    return { mode: "interval", every_minutes: every, timezone };
  }
  const daily = String(config.daily ?? "");
  if (daily.includes(":")) return { mode: "daily", time: daily.trim(), timezone };
  const weekly = String(config.weekly ?? "");
  if (weekly.includes(":")) {
    const [daysRaw, time] = weekly.trim().split(/\s+/, 2);
    return {
      mode: "weekly",
      days: daysRaw.split(",").map((d) => parseInt(d, 10)).filter((v) => !Number.isNaN(v)),
      time,
      timezone,
    };
  }
  return { mode: "daily", time: "08:00", timezone };
}

/** Forma que el scheduler v2 (`engine.next_trigger_at`) ya interpreta. */
export function triggerConfigFromSchedule(schedule: FriendlySchedule): Record<string, unknown> {
  switch (schedule.mode) {
    case "interval":
      return { every_minutes: Math.max(1, Math.min(Number(schedule.every_minutes ?? 5), 1440)), timezone: schedule.timezone };
    case "weekly":
      return {
        weekly: { days: [...new Set(schedule.days ?? [])].sort((a, b) => a - b), time: schedule.time ?? "09:00" },
        timezone: schedule.timezone,
      };
    case "monthly":
      return { monthly: { day: schedule.day_of_month ?? 1, time: schedule.time ?? "09:00" }, timezone: schedule.timezone };
    case "cron":
      return { cron: { expr: schedule.cron ?? "0 9 * * *", timezone: schedule.timezone } };
    case "daily":
    default:
      return { daily: { time: schedule.time ?? "08:00" }, timezone: schedule.timezone };
  }
}

export function describeSchedule(schedule: FriendlySchedule): string {
  const tz = schedule.timezone && schedule.timezone !== "UTC" ? ` (${schedule.timezone})` : "";
  switch (schedule.mode) {
    case "interval": {
      const minutes = Number(schedule.every_minutes ?? 0);
      if (minutes % 60 === 0) {
        const hours = minutes / 60;
        return hours === 1 ? `Cada hora${tz}` : `Cada ${hours} horas${tz}`;
      }
      return minutes === 1 ? "Cada minuto" : `Cada ${minutes} minutos${tz}`;
    }
    case "weekly": {
      const days = [...(schedule.days ?? [])].sort((a, b) => a - b);
      if (days.length === 0) return `Algunos días a las ${friendlyTime(schedule.time)}${tz}`;
      if (days.length === 5 && days.every((d, i) => d === i)) {
        return `Solo de lunes a viernes a las ${friendlyTime(schedule.time)}${tz}`;
      }
      const names = days.map((d) => (DAY_NAMES[d] ?? String(d)).toLowerCase());
      const list = names.length === 1 ? names[0] : `${names.slice(0, -1).join(", ")} y ${names[names.length - 1]}`;
      return `Los ${list} a las ${friendlyTime(schedule.time)}${tz}`;
    }
    case "monthly":
      return `El día ${schedule.day_of_month ?? 1} de cada mes a las ${friendlyTime(schedule.time)}${tz}`;
    case "cron":
      return `Según cron: ${schedule.cron} (avanzado)`;
    case "daily":
    default:
      return `Todos los días a las ${friendlyTime(schedule.time)}${tz}`;
  }
}
