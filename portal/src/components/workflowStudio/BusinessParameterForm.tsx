/**
 * BusinessParameterForm — renderer de parámetros de negocio.
 *
 * El backend declara (BusinessParameterSchema) y este componente dibuja:
 * Simple/Guided/Advanced, tipos de negocio, opciones dinámicas y secretos.
 * No conoce nodos concretos ni escribe Graph IR.
 */
import { Code, LockSimple, WarningCircle } from "@phosphor-icons/react";
import { useState } from "react";
import type { BusinessParameter, ParameterLevel, SelectOption } from "../../lib/businessSchema";
import { fromInputValue, staticOptions, toInputValue, visibleParameters } from "../../lib/businessSchema";
import type { DataSourceOption } from "../../lib/dataPicker";
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
  const [refOpen, setRefOpen] = useState<string | null>(null);
  const visible = visibleParameters(parameters, level, includeSecret);

  function appendRef(param: BusinessParameter, ref: string) {
    const current = toInputValue(values[param.key]);
    onChange(param.key, current ? `${current} ${ref}` : ref, param);
    setRefOpen(null);
  }

  if (visible.length === 0) {
    return <p className={`px-0.5 text-[10px] text-faint ${className}`}>{emptyHint}</p>;
  }

  return (
    <div className={`space-y-2.5 ${className}`} data-testid="wf-business-form">
      {visible.map((param) => {
        const value = values[param.key];
        const hasValue = value !== undefined && value !== null && value !== "";
        const options = optionList(param, optionsFor);
        const isSelect = param.type === "enum" || options.length > 0 || param.type === "boolean";
        return (
          <label key={param.key} className="block">
            <span className="mb-0.5 flex items-center gap-1 text-[10px] font-medium text-muted">
              <span>
                {param.label}
                {param.required && <span className="ml-1 text-danger">*</span>}
              </span>
              {param.secret && <LockSimple size={11} className="text-warn" aria-label="Secreto" />}
              {param.unit && <span className="text-faint">({param.unit})</span>}
              {dataSources && dataSources.length > 0 && acceptsReferences(param) ? (
                <span className="ml-auto">
                  <DataPicker
                    sources={dataSources}
                    label="dato"
                    testId={`wf-param-${param.key}-refs`}
                    onPick={(field) => appendRef(param, field.ref)}
                  />
                </span>
              ) : (
                referenceOptions &&
                referenceOptions.length > 0 &&
                acceptsReferences(param) && (
                  <span className="relative ml-auto">
                    <button
                      type="button"
                      className="btn btn-ghost min-h-5 gap-0.5 px-1 text-[9px]"
                      data-testid={`wf-param-${param.key}-refs`}
                      aria-label={`Insertar dato en ${param.label}`}
                      onClick={() => setRefOpen(refOpen === param.key ? null : param.key)}
                    >
                      <Code size={10} aria-hidden /> dato
                    </button>
                    {refOpen === param.key && (
                      <span className="absolute top-5 right-0 z-30 max-h-48 w-52 overflow-y-auto rounded-md border border-border bg-raised p-1 shadow-pop">
                        {referenceOptions.map((r) => (
                          <button
                            key={r.value}
                            type="button"
                            className="block w-full truncate rounded px-2 py-1 text-left text-[10px] text-text hover:bg-soft"
                            onClick={() => appendRef(param, r.value)}
                          >
                            {r.label}
                          </button>
                        ))}
                      </span>
                    )}
                  </span>
                )
              )}
            </span>

            {isSelect ? (
              <select
                className={`w-full rounded-md border bg-soft px-2 py-2 text-[11px] ${
                  param.required && !hasValue ? "border-warn/60" : "border-border"
                }`}
                value={toInputValue(value)}
                data-testid={`wf-param-${param.key}`}
                onChange={(e) => onChange(param.key, fromInputValue(param, e.target.value), param)}
              >
                <option value="">Elige…</option>
                {options.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            ) : param.type === "textarea" || param.type === "json" ? (
              <textarea
                className={`w-full rounded-md border border-border bg-soft px-2 py-1.5 ${
                  param.type === "json" ? "font-mono text-[10px]" : "text-[11px]"
                }`}
                rows={param.type === "json" ? 2 : 3}
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
            ) : param.type === "boolean" ? (
              <input
                type="checkbox"
                className="mt-1"
                checked={value === true}
                data-testid={`wf-param-${param.key}`}
                onChange={(e) => onChange(param.key, e.target.checked, param)}
              />
            ) : (
              <input
                className={`w-full rounded-md border bg-soft px-2 py-1.5 text-[11px] ${
                  param.required && !hasValue ? "border-warn/60" : "border-border"
                }`}
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
                placeholder={param.placeholder ?? (param.examples.length > 0 ? String(param.examples[0]) : undefined)}
                value={toInputValue(value)}
                data-testid={`wf-param-${param.key}`}
                onChange={(e) => onChange(param.key, fromInputValue(param, e.target.value), param)}
              />
            )}

            {param.help && <span className="mt-0.5 block text-[9px] text-faint">{param.help}</span>}
            {param.description && <span className="mt-0.5 block text-[9px] text-faint">{param.description}</span>}
            {isSelect && options.length === 0 && (
              <span className="mt-0.5 flex items-center gap-1 text-[9px] text-warn" data-testid={`wf-param-${param.key}-no-options`}>
                <WarningCircle size={10} aria-hidden />
                No hay opciones disponibles todavía.
              </span>
            )}
          </label>
        );
      })}
    </div>
  );
}
