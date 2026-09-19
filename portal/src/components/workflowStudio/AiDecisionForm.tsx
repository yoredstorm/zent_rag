import { Plus, Trash } from "@phosphor-icons/react";
import { Button, Field, Input, Select, Textarea } from "../ui";

type Option = { id: string; label: string };

type Props = {
  config: Record<string, unknown>;
  onChange: (patch: Record<string, unknown>) => void;
};

const KINDS = [
  { value: "route", label: "Elegir ruta" },
  { value: "yes_no", label: "Sí / No" },
  { value: "score", label: "Evaluar puntuación" },
];

const LOW = [
  { value: "fallback", label: "Usar respaldo" },
  { value: "human_review", label: "Revisión humana" },
  { value: "stop", label: "Detener" },
  { value: "llm", label: "Preguntar a un agente" },
];

function asOptions(raw: unknown): Option[] {
  if (Array.isArray(raw)) {
    return raw
      .map((item) => {
        if (typeof item === "string") return { id: item, label: item };
        if (item && typeof item === "object") {
          const rec = item as Record<string, unknown>;
          const id = String(rec.id || rec.value || rec.label || "");
          return { id, label: String(rec.label || id) };
        }
        return { id: "", label: "" };
      })
      .filter((o) => o.id);
  }
  return [
    { id: "approve", label: "Aprobar" },
    { id: "reject", label: "Rechazar" },
    { id: "review", label: "Revisar" },
  ];
}

export function AiDecisionForm({ config, onChange }: Props) {
  const kind = String(config.decision_kind || "route");
  const options = asOptions(config.options);
  const confidence = String(config.confidence_min ?? 0.65);
  const onLow = String(config.on_low_confidence || "fallback");

  return (
    <div className="space-y-3" data-testid="wf-ai-decision">
      <Field label="Tipo">
        <Select value={kind} onChange={(e) => onChange({ decision_kind: e.target.value })}>
          {KINDS.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Pregunta">
        <Textarea
          value={String(config.question || "")}
          placeholder="Determinar si el cliente requiere revisión manual"
          onChange={(e) => onChange({ question: e.target.value })}
        />
      </Field>
      {kind === "route" ? (
        <div className="space-y-2">
          <p className="text-[12px] text-muted">Opciones</p>
          {options.map((option, index) => (
            <div key={`${option.id}-${index}`} className="flex gap-2">
              <Input
                value={option.label}
                placeholder="Aprobar"
                onChange={(e) => {
                  const next = options.map((row, i) =>
                    i === index
                      ? { id: slug(e.target.value) || row.id, label: e.target.value }
                      : row,
                  );
                  onChange({ options: next });
                }}
              />
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => onChange({ options: options.filter((_, i) => i !== index) })}
              >
                <Trash size={14} />
              </Button>
            </div>
          ))}
          <Button
            type="button"
            variant="secondary"
            size="sm"
            leadingIcon={Plus}
            onClick={() => onChange({ options: [...options, { id: `opt_${options.length + 1}`, label: "" }] })}
          >
            Agregar opción
          </Button>
        </div>
      ) : null}
      <Field label="Confianza mínima">
        <Input
          type="number"
          min={0}
          max={1}
          step={0.05}
          value={confidence}
          onChange={(e) => onChange({ confidence_min: Number(e.target.value) })}
        />
      </Field>
      <Field label="Si la confianza es baja">
        <Select
          value={onLow}
          onChange={(e) => onChange({ on_low_confidence: e.target.value })}
        >
          {LOW.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </Select>
      </Field>
    </div>
  );
}

function slug(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "")
    .slice(0, 40);
}
