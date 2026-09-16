/**
 * BusinessParameterForm — renderer de parámetros de negocio.
 *
 * El backend declara (BusinessParameterSchema) y este componente dibuja:
 * Simple/Guided/Advanced, tipos de negocio, opciones dinámicas y secretos.
 * No conoce nodos concretos ni escribe Graph IR.
 */
import { LockSimple, WarningCircle } from "@phosphor-icons/react";
import { useId, useState } from "react";
import type { BusinessParameter, ParameterLevel, SelectOption } from "../../lib/businessSchema";
import { fromInputValue, staticOptions, toInputValue, visibleParameters } from "../../lib/businessSchema";
import type { DataSourceOption } from "../../lib/dataPicker";
import { Button, Input, Popover, Select, Textarea, cn } from "../ui";
import { DataPicker } from "./DataPicker";

type Props = {
  parameters: BusinessParameter[];
  level: ParameterLevel;
  values: Record<string, unknown>;
  onChange: (key: string, value: unknown, param: BusinessParameter) => void;
  optionsFor?: (param: BusinessParameter) => SelectOption[] | undefined;
  includeSecret?: boolean;
  /** Referencias a datos de otros pasos (label visible + ref técnica). El
   *  formulario inserta la ref, pero Simple Mode no la muestra como tal. */
  referenceOptions?: SelectOption[];
  /** Fuentes del Data Picker (contratos + samples reales). Tiene prioridad. */
  dataSources?: DataSourceOption[];
  /** Clase del contenedor; el panel controla el layout. */
  className?: string;
  emptyHint?: string;
};

function optionList(param: BusinessParameter, optionsFor?: Props["optionsFor"]): SelectOption[] {
  const staticOnes = staticOptions(param);
  if (staticOnes.length > 0) return staticOnes;
  if (param.type === "boolean") {
    return [
      { value: "true", label: "Sí" },
      { value: "false", label: "No" },
    ];
  }
  return optionsFor?.(param) ?? [];
}

function acceptsReferences(param: BusinessParameter): boolean {
  if (param.data_source) return true;
  return ["text", "textarea", "json", "data_reference"].includes(param.type);
}

export function BusinessParameterForm({
  parameters,
  level,
  values,
  onChange,
  optionsFor,
  includeSecret = false,
  referenceOptions,
  dataSources,
  className = "",
  emptyHint = "Este paso no tiene parámetros configurables.",
}: Props) {
  const uid = useId();
  const [refAnchor, setRefAnchor] = useState<string | null>(null);
  const visible = visibleParameters(parameters, level, includeSecret);

  function appendRef(param: BusinessParameter, ref: string) {
    const current = toInputValue(values[param.key]);
    onChange(param.key, current ? `${current} ${ref}` : ref, param);
    setRefAnchor(null);
  }

  if (visible.length === 0) {
    return <p className={cn("px-0.5 text-[12px] text-faint", className)}>{emptyHint}</p>;
  }

  return (
    <div className={cn("space-y-3", className)} data-testid="wf-business-form">
      {visible.map((param) => {
        const id = `${uid}-${param.key}`;
        const value = values[param.key];
        const hasValue = value !== undefined && value !== null && value !== "";
        const invalid = Boolean(param.required && !hasValue);
        const options = optionList(param, optionsFor);
        const isSelect = param.type === "enum" || options.length > 0 || param.type === "boolean";
        const help = param.help || param.description;
        const helpId = help ? `${id}-help` : undefined;
        const requiredId = invalid ? `${id}-required` : undefined;
        const describedBy = [requiredId, helpId].filter(Boolean).join(" ") || undefined;
        const usesDataPicker = Boolean(dataSources && dataSources.length > 0 && acceptsReferences(param));
        const usesRefs = !usesDataPicker && Boolean(referenceOptions?.length) && acceptsReferences(param);
        return (
          <div key={param.key} className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <label htmlFor={id} className="text-[13px] font-medium text-text">
                {param.label}
              </label>
              {param.required && (
                <span className="text-danger" aria-hidden>
                  *
                </span>
              )}
              {param.secret && <LockSimple size={12} className="shrink-0 text-warn" aria-label="Secreto" />}
              {param.unit && <span className="text-[11px] text-faint">({param.unit})</span>}
              {(usesDataPicker || usesRefs) && (
                <span className="ml-auto">
                  {usesDataPicker ? (
                    <DataPicker
                      sources={dataSources ?? []}
                      label="dato"
                      testId={`wf-param-${param.key}-refs`}
                      onPick={(field) => appendRef(param, field.ref)}
                    />
                  ) : (
                    <Popover
                      open={refAnchor === param.key}
                      onOpenChange={(open) => setRefAnchor(open ? param.key : null)}
                      width={264}
                      trigger={
                        <Button
                          variant="ghost"
                          size="sm"
                          className="px-1.5 text-[11px]"
                          aria-label={`Insertar dato en ${param.label}`}
                          data-testid={`wf-param-${param.key}-refs`}
                        >
                          Dato
                        </Button>
                      }
                    >
                      <div className="max-h-56 space-y-0.5 overflow-y-auto">
                        {(referenceOptions ?? []).map((r) => (
                          <button
                            key={r.value}
                            type="button"
                            className="block w-full truncate rounded-sm px-2 py-1.5 text-left text-[12px] text-text transition-colors duration-150 hover:bg-soft"
                            onClick={() => appendRef(param, r.value)}
                          >
                            {r.label}
                          </button>
                        ))}
                      </div>
                    </Popover>
                  )}
                </span>
              )}
            </div>

            {isSelect ? (
              <Select
                id={id}
                value={toInputValue(value)}
                aria-invalid={invalid || undefined}
                aria-describedby={describedBy}
                data-testid={`wf-param-${param.key}`}
                onChange={(e) => onChange(param.key, fromInputValue(param, e.target.value), param)}
              >
                <option value="">Elige…</option>
                {options.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            ) : param.type === "textarea" || param.type === "json" ? (
              <Textarea
                id={id}
                className={param.type === "json" ? "font-mono text-[12px]" : undefined}
                rows={param.type === "json" ? 2 : 3}
                aria-invalid={invalid || undefined}
                aria-describedby={describedBy}
                placeholder={param.placeholder ?? (param.type === "json" ? "{}" : undefined)}
                value={
                  param.type === "json" && typeof value === "object"
                    ? JSON.stringify(value)
                    : toInputValue(value)
                }
                data-testid={`wf-param-${param.key}`}
                onChange={(e) => {
                  if (param.type !== "json") {
                    onChange(param.key, e.target.value, param);
                    return;
                  }
                  try {
                    onChange(param.key, JSON.parse(e.target.value || "{}"), param);
                  } catch {
                    onChange(param.key, e.target.value, param);
                  }
                }}
              />
            ) : (
              <Input
                id={id}
                type={
                  param.type === "number" || param.type === "integer" || param.type === "money" || param.type === "percentage"
                    ? "number"
                    : param.type === "date"
                      ? "date"
                      : param.type === "time"
                        ? "time"
                        : param.type === "datetime"
                          ? "datetime-local"
                          : param.type === "secret"
                            ? "password"
                            : "text"
                }
                aria-invalid={invalid || undefined}
                aria-describedby={describedBy}
                placeholder={
                  param.placeholder ?? (param.examples.length > 0 ? String(param.examples[0]) : undefined)
                }
                value={toInputValue(value)}
                data-testid={`wf-param-${param.key}`}
                onChange={(e) => onChange(param.key, fromInputValue(param, e.target.value), param)}
              />
            )}

            {help && (
              <p id={helpId} className="field-hint">
                {help}
              </p>
            )}
            {invalid && (
              <p id={requiredId} className="field-error" role="status">
                Campo obligatorio.
              </p>
            )}
            {isSelect && options.length === 0 && (
              <p className="flex items-center gap-1.5 text-[11px] text-warn" data-testid={`wf-param-${param.key}-no-options`}>
                <WarningCircle size={11} aria-hidden />
                No hay opciones disponibles todavía.
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
