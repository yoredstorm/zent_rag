import { useReducedMotion } from "motion/react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fmtDate, fmtNum } from "../lib/format";
import { LOCALE } from "../lib/locale";

export type DailyPoint = {
  day: string;
  requests: number;
  tokens: number;
  avg_latency_ms: number;
};

/** "2026-09-12" → "12 sep" para ticks; valores raros se muestran crudos. */
function tickDay(value: string): string {
  if (typeof value !== "string" || value.length < 10) return value;
  const date = new Date(`${value.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value.slice(5);
  return date.toLocaleDateString(LOCALE, { day: "2-digit", month: "short" });
}

/** Duración alineada con `--dur-5` (340ms): entrada progresiva corta. */
const CHART_ANIMATION_MS = 340;

/** Tooltip del sistema: misma superficie y tokens que el resto de los charts. */
function UsageTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: DailyPoint }[];
}) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="rounded-sm border border-border bg-overlay px-2.5 py-1.5 text-xs shadow-pop">
      <p className="text-muted">{fmtDate(point.day)}</p>
      <p className="mt-0.5 text-text">
        <span className="font-medium tabular-nums">{fmtNum(point.requests)}</span> consultas
      </p>
    </div>
  );
}

/**
 * Volumen diario de consultas del workspace.
 * Un solo accent (`--color-accent`), grilla hairline y tooltip del sistema.
 */
export default function UsageChart({ daily }: { daily: DailyPoint[] }) {
  const reduce = useReducedMotion();
  const total = daily.reduce((sum, point) => sum + point.requests, 0);

  return (
    <div
      role="img"
      aria-label={`Consultas por día en los últimos ${daily.length} días: ${fmtNum(total)} en total.`}
    >
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={daily} margin={{ top: 4, right: 8, bottom: 0, left: 0 }} accessibilityLayer>
          <CartesianGrid stroke="var(--color-border-soft)" vertical={false} />
          <XAxis
            dataKey="day"
            tick={{ fill: "var(--color-muted)", fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: "var(--color-border)" }}
            minTickGap={24}
            tickFormatter={tickDay}
          />
          <YAxis
            allowDecimals={false}
            tick={{ fill: "var(--color-muted)", fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            width={44}
            tickFormatter={(value: number) => fmtNum(value)}
          />
          <Tooltip
            cursor={{ fill: "var(--color-soft)", fillOpacity: 0.55 }}
            content={<UsageTooltip />}
          />
          <Bar
            dataKey="requests"
            name="Consultas"
            fill="var(--color-accent)"
            radius={[4, 4, 0, 0]}
            maxBarSize={26}
            isAnimationActive={!reduce}
            animationDuration={CHART_ANIMATION_MS}
            animationEasing="ease-out"
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
