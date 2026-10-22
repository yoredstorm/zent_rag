import { Field, Input, Textarea } from "../ui";

export type MissionFields = {
  role: string;
  audience: string;
  goal: string;
  limits: string;
  capabilities: string;
  sources: string;
  memory: string;
  actions: string;
  outcomes: string;
};

export const EMPTY_MISSION: MissionFields = {
  role: "",
  audience: "",
  goal: "",
  limits: "",
  capabilities: "",
  sources: "",
  memory: "",
  actions: "",
  outcomes: "",
};

export function missionFromGraph(metadata: Record<string, unknown> | undefined): MissionFields {
  const raw = metadata?.mission;
  if (!raw || typeof raw !== "object") return { ...EMPTY_MISSION };
  const record = raw as Record<string, unknown>;
  const next = { ...EMPTY_MISSION };
  for (const key of Object.keys(next) as (keyof MissionFields)[]) {
    const value = record[key];
    if (typeof value === "string") next[key] = value;
  }
  return next;
}

const FIELDS: { key: keyof MissionFields; label: string; hint?: string }[] = [
  { key: "role", label: "Rol" },
  { key: "audience", label: "Público" },
  { key: "goal", label: "Objetivo" },
  { key: "limits", label: "Límites", hint: "Lo que este flujo no debe hacer." },
  { key: "capabilities", label: "Capacidades" },
  { key: "sources", label: "Fuentes" },
  { key: "memory", label: "Memoria", hint: "Solo lo que la persona autorizó." },
  { key: "actions", label: "Acciones permitidas" },
  { key: "outcomes", label: "Resultados" },
];

/** Ficha de misión. La vista primaria son campos, no JSON. */
export function MissionCard({
  value,
  onChange,
}: {
  value: MissionFields;
  onChange: (next: MissionFields) => void;
}) {
  return (
    <section className="rounded-lg border border-border bg-surface p-3" data-testid="wf-mission">
      <h2 className="text-[13px] font-medium text-text">Ficha de misión</h2>
      <p className="mt-1 text-[12px] leading-relaxed text-faint">
        Simple, Guiado y Avanzado cambian el detalle del mismo flujo. Esta ficha viaja con el lienzo.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {FIELDS.map((field) => {
          const long = field.key === "limits" || field.key === "outcomes" || field.key === "goal";
          return (
            <Field key={field.key} label={field.label} hint={field.hint} className={long ? "sm:col-span-2" : ""}>
              {long ? (
                <Textarea
                  value={value[field.key]}
                  rows={2}
                  data-testid={`wf-mission-${field.key}`}
                  onChange={(event) => onChange({ ...value, [field.key]: event.target.value })}
                />
              ) : (
                <Input
                  value={value[field.key]}
                  data-testid={`wf-mission-${field.key}`}
                  onChange={(event) => onChange({ ...value, [field.key]: event.target.value })}
                />
              )}
            </Field>
          );
        })}
      </div>
    </section>
  );
}
