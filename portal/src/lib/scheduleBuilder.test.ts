import { describe, expect, it } from "vitest";
import {
  describeSchedule,
  scheduleFromNodeConfig,
  triggerConfigFromSchedule,
} from "./scheduleBuilder";

describe("scheduleBuilder", () => {
  it("lee la config canónica del nodo", () => {
    const schedule = scheduleFromNodeConfig({
      schedule: { mode: "daily", time: "08:00", timezone: "America/Lima" },
    });
    expect(schedule.mode).toBe("daily");
    expect(schedule.timezone).toBe("America/Lima");
  });

  it("migra configs legacy (daily / weekly / every_minutes)", () => {
    expect(scheduleFromNodeConfig({ daily: "18:00", timezone: "UTC" })).toMatchObject({
      mode: "daily",
      time: "18:00",
    });
    expect(scheduleFromNodeConfig({ weekly: "0,2 09:00" })).toMatchObject({
      mode: "weekly",
      days: [0, 2],
      time: "09:00",
    });
    expect(scheduleFromNodeConfig({ every_minutes: 15 })).toMatchObject({
      mode: "interval",
      every_minutes: 15,
    });
  });

  it("produce el trigger_config que entiende el scheduler v2", () => {
    expect(
      triggerConfigFromSchedule({ mode: "daily", time: "08:00", timezone: "America/Lima" }),
    ).toEqual({ daily: { time: "08:00" }, timezone: "America/Lima" });

    expect(
      triggerConfigFromSchedule({ mode: "weekly", days: [4, 0], time: "18:30", timezone: "UTC" }),
    ).toEqual({ weekly: { days: [0, 4], time: "18:30" }, timezone: "UTC" });

    expect(
      triggerConfigFromSchedule({ mode: "monthly", day_of_month: 1, time: "09:00", timezone: "UTC" }),
    ).toEqual({ monthly: { day: 1, time: "09:00" }, timezone: "UTC" });

    expect(triggerConfigFromSchedule({ mode: "interval", every_minutes: 30, timezone: "UTC" })).toMatchObject({
      every_minutes: 30,
    });
  });

  it("describe el preview en lenguaje humano", () => {
    expect(describeSchedule({ mode: "daily", time: "08:00", timezone: "UTC" })).toBe(
      "Todos los días a las 8:00 a. m.",
    );
    expect(describeSchedule({ mode: "weekly", days: [0, 1, 2, 3, 4], time: "09:00", timezone: "UTC" })).toBe(
      "Solo de lunes a viernes a las 9:00 a. m.",
    );
    expect(describeSchedule({ mode: "monthly", day_of_month: 1, time: "00:00", timezone: "UTC" })).toBe(
      "El día 1 de cada mes a las 12:00 a. m.",
    );
    expect(describeSchedule({ mode: "interval", every_minutes: 120, timezone: "UTC" })).toBe(
      "Cada 2 horas",
    );
  });
});
