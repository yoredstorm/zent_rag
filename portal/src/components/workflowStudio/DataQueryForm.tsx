/**
 * P19-03 — editor simple de «Consultar registros».
 *
 * El plan autorizado vive en el servidor. Esta UI solo selecciona un plan
 * publicado, llena parámetros declarados y prueba la lectura. Nunca escribe
 * SQL, tabla, columnas, límite ni conexión.
 */
import { Database, Play, WarningCircle } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import type { ParameterLevel } from "../../lib/businessSchema";
import type { DataFieldOption, DataSourceOption } from "../../lib/dataPicker";
import { DataPicker } from "./DataPicker";
import { PublishQueryModal } from "./PublishQueryModal";
import { Button, Field, Input, Select, StatusBadge } from "../ui";

export type DataQueryParameter = {
  name: string;
  field: string;
  operator: string;
  type: string;
  required: boolean;
  label: string;
};

type DataQueryPlan = {
  binding_ref: string;
  capability_ref: string;
  resource_ref: string;
  resource_kind: string;
  operation: string;
  projection: string[];
  max_rows: number;
  parameters: DataQueryParameter[];
  ownership_required: boolean;
  pii_class: string;
};

type PreviewResult = {
  status?: string;
  category?: string;
  found?: boolean;
  record?: Record<string, unknown> | null;
  rows?: Record<string, unknown>[];
  row_count?: number;
  truncated?: boolean;
  source_ref?: string;
  duration_ms?: number;
  reason_code?: string | null;
  safe_message?: string;
  message?: string;
};

type PreviewResponse = {
  preview: boolean;
  redacted_fields: string[];
  legacy_plan?: boolean;
  policy_hash?: string | null;
  result: PreviewResult;
};

type Props = {
  config: Record<string, unknown>;
  onChange: (patch: Record<string, unknown>) => void;
  level?: ParameterLevel;
  dataSources?: DataSourceOption[];
};

function planLabel(plan: DataQueryPlan): string {
  const operation =
    plan.operation === "get_one"
      ? "Buscar un registro"
      : plan.operation === "count"
        ? "Contar"
        : "Listar";
  return `${operation} · ${plan.resource_ref}`;
}

function emptyParam(value: unknown): boolean {
  return value === undefined || value === null || String(value).trim() === "";
}

function coerceParam(type: string, value: string): unknown {
  if (value.startsWith("{{")) return value;
  if (type === "integer") {
    const parsed = Number.parseInt(value, 10);
    return Number.isNaN(parsed) ? value : parsed;
  }
  if (type === "number") {
    const parsed = Number(value);
    return Number.isNaN(parsed) ? value : parsed;
  }
  if (type === "boolean") return value === "true";
  return value;
}

function paramInputType(type: string): string {
  if (type === "date") return "date";
  if (type === "datetime") return "datetime-local";
  return "text";
}

function previewRows(result: PreviewResult): Record<string, unknown>[] {
  if (result.record) return [result.record];
  return result.rows ?? [];
}

function previewMessage(result: PreviewResult): string {
  if (result.safe_message) return result.safe_message;
  if (result.status === "FOUND") return "Encontré la información.";
  if (result.status === "NOT_FOUND") return "No hay coincidencias.";
  if (result.status === "MULTIPLE_MATCHES") return "Hay varias coincidencias.";
  if (result.status === "SIMULATED") return "Vista previa simulada; no es un dato certificado.";
  return "No se pudo completar la consulta.";
}

export function DataQueryForm({ config, onChange, level = "simple", dataSources = [] }: Props) {
  const { session } = useAuth();
  const [plans, setPlans] = useState<DataQueryPlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [busy, setBusy] = useState(false);
  const [publishOpen, setPublishOpen] = useState(false);

  const loadPlans = useCallback(async (): Promise<DataQueryPlan[]> => {
    if (!session) return [];
    setLoading(true);
    try {
      const data = await api<{ plans: DataQueryPlan[] }>("/api/v1/workflows/data-query/plans", {
        token: session.token,
        organizationId: session.organizationId,
      });
      const next = data.plans ?? [];
      setPlans(next);
      setError("");
      return next;
    } catch (exc) {
      setPlans([]);
      setError(exc instanceof Error ? exc.message : "No pude cargar las consultas publicadas.");
      return [];
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => {
    void loadPlans();
  }, [loadPlans]);

  const selected = useMemo(
    () =>
      plans.find(
        (plan) =>
          plan.capability_ref === String(config.capability ?? "") &&
          (!config.binding_ref || plan.binding_ref === String(config.binding_ref)),
      ) ?? null,
    [plans, config.capability, config.binding_ref],
  );

  const params = useMemo<Record<string, unknown>>(() => {
    const raw = config.params;
    return raw && typeof raw === "object" && !Array.isArray(raw)
      ? (raw as Record<string, unknown>)
      : {};
  }, [config.params]);

  function choosePlan(bindingRef: string) {
    const plan = plans.find((item) => item.binding_ref === bindingRef);
    if (!plan) return;
    const nextParams: Record<string, unknown> = {};
    for (const parameter of plan.parameters) {
      if (params[parameter.name] !== undefined) nextParams[parameter.name] = params[parameter.name];
    }
    setPreview(null);
    setPreviewError("");
    onChange({
      capability: plan.capability_ref,
      binding_ref: plan.binding_ref,
      params: nextParams,
    });
  }

  function setParam(parameter: DataQueryParameter, value: string) {
    onChange({ params: { ...params, [parameter.name]: coerceParam(parameter.type, value) } });
  }

  const missing = (selected?.parameters ?? []).filter(
    (parameter) => parameter.required && emptyParam(params[parameter.name]),
  );
  const canPreview = Boolean(selected) && missing.length === 0 && !busy;

  async function runPreview() {
    if (!session || !selected) return;
    setBusy(true);
    setPreviewError("");
    try {
      const response = await api<PreviewResponse>("/api/v1/workflows/data-query/preview", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ binding_id: selected.binding_ref, params }),
      });
      setPreview(response);
    } catch (exc) {
      setPreview(null);
      setPreviewError(exc instanceof Error ? exc.message : "La prueba de lectura falló.");
    } finally {
      setBusy(false);
    }
  }

  async function handlePublished(published: {
    binding_ref: string;
    capability_ref: string;
  }) {
    setPublishOpen(false);
    const next = await loadPlans();
    const target = next.find((plan) => plan.binding_ref === published.binding_ref);
    if (target) {
      onChange({
        capability: target.capability_ref,
        binding_ref: target.binding_ref,
        params: {},
      });
      setPreview(null);
      setPreviewError("");
    }
  }

  if (loading) {
    return <p className="text-[12px] text-faint">Cargando consultas autorizadas…</p>;
  }

  if (error) {
    return (
      <div className="rounded-md border border-danger/30 bg-danger/5 p-3" role="alert">
        <p className="flex items-center gap-2 text-[12px] font-medium text-danger">
          <WarningCircle size={14} /> No pude cargar las consultas
        </p>
        <p className="mt-1 text-[12px] text-muted">{error}</p>
      </div>
    );
  }

  if (plans.length === 0) {
    return (
      <>
        <div className="rounded-md border border-border bg-soft/50 p-3" data-testid="wf-dq-empty">
          <p className="text-[12px] font-medium text-text">No hay consultas publicadas</p>
          <p className="mt-1 text-[12px] text-muted">
            Publica una tabla autorizada de tu conector. Después podrás usarla aquí sin escribir SQL.
          </p>
          <Button
            variant="secondary"
            size="sm"
            className="mt-2"
            onClick={() => setPublishOpen(true)}
            data-testid="wf-dq-publish"
          >
            Publicar una consulta
          </Button>
        </div>
        <PublishQueryModal
          open={publishOpen}
          onOpenChange={setPublishOpen}
          onPublished={handlePublished}
        />
      </>
    );
  }

  return (
    <div className="space-y-3" data-testid="wf-data-query-form">
      <Field label="¿Qué consulta usar?" hint="Solo aparecen planes publicados para este workspace.">
        <Select
          value={selected?.binding_ref ?? ""}
          onChange={(event) => choosePlan(event.target.value)}
          data-testid="wf-dq-plan"
          aria-label="Consulta autorizada"
        >
          <option value="">Elige una consulta.</option>
          {plans.map((plan) => (
            <option key={plan.binding_ref} value={plan.binding_ref}>
              {planLabel(plan)}
            </option>
          ))}
        </Select>
      </Field>

      {selected && (
        <>
          <div className="rounded-md border border-border bg-soft/40 p-2.5">
            <p className="flex items-center gap-2 text-[11px] font-semibold tracking-[0.05em] text-faint uppercase">
              <Database size={13} /> {selected.resource_kind} · {selected.resource_ref}
            </p>
            <p className="mt-1 text-[12px] text-muted">
              Devuelve: {selected.projection.join(", ")} · máximo {selected.max_rows} fila(s)
            </p>
          </div>

          {selected.ownership_required && (
            <p className="rounded-md border border-warning/30 bg-warning/5 p-2 text-[12px] text-muted">
              Esta consulta exige identidad verificada. En el diseñador no se puede probar con datos
              de un cliente.
            </p>
          )}

          {(selected.parameters.length > 0 || Object.keys(params).length > 0) && (
            <div className="space-y-2">
              <p className="eyebrow">Datos para buscar</p>
              {selected.parameters.map((parameter) => (
                <Field
                  key={parameter.name}
                  label={parameter.label}
                  required={parameter.required}
                  hint={`${parameter.operator} · ${parameter.type}`}
                >
                  {parameter.type === "boolean" ? (
                    <Select
                      value={String(params[parameter.name] ?? "")}
                      onChange={(event) => setParam(parameter, event.target.value)}
                      data-testid={`wf-dq-param-${parameter.name}`}
                    >
                      <option value="">Elige un valor.</option>
                      <option value="true">Sí</option>
                      <option value="false">No</option>
                    </Select>
                  ) : (
                    <Input
                      type={paramInputType(parameter.type)}
                      inputMode={
                        ["integer", "number", "decimal"].includes(parameter.type)
                          ? "decimal"
                          : undefined
                      }
                      step={parameter.type === "integer" ? "1" : undefined}
                      value={String(params[parameter.name] ?? "")}
                      onChange={(event) => setParam(parameter, event.target.value)}
                      placeholder={parameter.required ? "Obligatorio" : "Opcional"}
                      data-testid={`wf-dq-param-${parameter.name}`}
                    />
                  )}
                  {dataSources.length > 0 && (
                    <div className="mt-1">
                      <DataPicker
                        sources={dataSources}
                        label="Usar dato anterior"
                        testId={`wf-dq-pick-${parameter.name}`}
                        emptyHint="Ejecuta una prueba para ver campos disponibles."
                        onPick={(field: DataFieldOption) => setParam(parameter, field.ref)}
                      />
                    </div>
                  )}
                </Field>
              ))}
              {selected.parameters.length === 0 && (
                <p className="text-[12px] text-faint">Este plan no necesita parámetros.</p>
              )}
            </div>
          )}

          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              leadingIcon={Play}
              disabled={!canPreview}
              onClick={runPreview}
              data-testid="wf-dq-preview"
            >
              {busy ? "Probando…" : "Probar lectura"}
            </Button>
            {!canPreview && missing.length > 0 && (
              <span className="text-[11px] text-faint">Completa {missing.map((p) => p.label).join(", ")}</span>
            )}
          </div>

          {previewError && (
            <p className="rounded-md border border-danger/30 bg-danger/5 p-2 text-[12px] text-danger" role="alert">
              {previewError}
            </p>
          )}

          {preview && (
            <div className="space-y-2 rounded-md border border-border p-2.5" data-testid="wf-dq-preview-result">
              <div className="flex items-center justify-between gap-2">
                <StatusBadge status={preview.result.status ?? "error"} raw />
                <span className="text-[11px] text-faint">
                  {preview.result.duration_ms ?? 0} ms
                </span>
              </div>
              <p className="text-[12px] text-text" role="status" aria-live="polite">
                {previewMessage(preview.result)}
              </p>
              <p className="text-[11px] text-faint">
                Fuente: {preview.result.source_ref ?? selected.resource_ref}
                {preview.redacted_fields.length > 0
                  ? ` · redactado: ${preview.redacted_fields.join(", ")}`
                  : ""}
              </p>
              {preview.legacy_plan && (
                <p className="rounded-sm border border-warning/30 bg-warning/5 p-1.5 text-[11px] text-muted">
                  Plan anterior sin política versionada. Revisar y republicar antes de usarlo en
                  producción.
                </p>
              )}
              {previewRows(preview.result).length > 0 && (
                <div className="max-h-48 overflow-auto rounded-sm border border-border">
                  <table className="w-full text-left text-[11px]">
                    <thead className="bg-soft text-faint">
                      <tr>
                        {Object.keys(previewRows(preview.result)[0] ?? {}).map((key) => (
                          <th key={key} className="px-2 py-1 font-medium">
                            {key}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {previewRows(preview.result).slice(0, 5).map((row, index) => (
                        <tr key={index} className="border-t border-border">
                          {Object.keys(previewRows(preview.result)[0] ?? {}).map((key) => (
                            <td key={key} className="px-2 py-1 text-text">
                              {String(row[key] ?? "—")}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {preview.result.reason_code && level === "advanced" && (
                <p className="font-mono text-[10px] text-danger">{preview.result.reason_code}</p>
              )}
            </div>
          )}

          {level === "advanced" && (
            <dl className="space-y-1 border-t border-border pt-2 font-mono text-[10px] text-faint">
              <div className="flex justify-between gap-2">
                <dt>binding_ref</dt>
                <dd className="truncate">{selected.binding_ref}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt>capability</dt>
                <dd className="truncate">{selected.capability_ref}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt>pii_class</dt>
                <dd>{selected.pii_class}</dd>
              </div>
            </dl>
          )}
        </>
      )}
    </div>
  );
}
