import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export type DailyPoint = {
  day: string;
  requests: number;
  tokens: number;
  avg_latency_ms: number;
};

export default function UsageChart({ daily }: { daily: DailyPoint[] }) {
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={daily}>
        <CartesianGrid
          strokeDasharray="3 3"
          stroke="var(--color-border)"
          vertical={false}
        />
        <XAxis
          dataKey="day"
          tick={{ fill: "var(--color-muted)", fontSize: 11 }}
          tickLine={false}
          axisLine={{ stroke: "var(--color-border)" }}
          tickFormatter={(v: string) =>
            typeof v === "string" && v.length >= 10 ? v.slice(5) : v
          }
        />
        <YAxis
          allowDecimals={false}
          tick={{ fill: "var(--color-muted)", fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          width={30}
        />
        <Tooltip
          cursor={{ fill: "rgba(255,255,255,0.04)" }}
          contentStyle={{
            background: "var(--color-raised)",
            border: "1px solid var(--color-border)",
            borderRadius: 8,
            color: "var(--color-text)",
            fontSize: 12,
          }}
          labelStyle={{ color: "var(--color-muted)" }}
        />
        <Bar
          dataKey="requests"
          name="Consultas"
          fill="var(--color-accent)"
          radius={[4, 4, 0, 0]}
          maxBarSize={26}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}
