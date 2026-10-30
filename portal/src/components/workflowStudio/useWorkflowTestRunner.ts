import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { isApiError } from "../../lib/errors";
import { humanizeWorkflowError } from "../../lib/workflowErrors";
import type { RunDetail } from "../WorkflowRunInspector";
import { buildTestRun } from "./workflowTestPresentation";
import {
  createInitialTestSessionState,
  isTestBusy,
  workflowTestSessionReducer,
} from "./workflowTestSession";
import type { RunOut, TestLevel, TestReportOut } from "./workflowTestTypes";
import type { WorkflowRun } from "./types";

function errorText(error: unknown): string {
  if (isApiError(error)) {
    if (error.status === 401) return "La sesión expiró. Vuelve a iniciar sesión; tu borrador local se conserva.";
    if (error.status === 403) return "No tienes permiso para ejecutar esta operación. Pide acceso a un administrador.";
    if (error.status === 409) return "Otra pestaña guardó este flujo. Tus cambios siguen aquí.";
    if (error.status === 429) return "Demasiadas solicitudes. Espera unos segundos y vuelve a intentar.";
    if (error.status === 503) return "El servicio no está disponible ahora. El borrador no se perdió.";
    return humanizeWorkflowError(error.message);
  }
  return humanizeWorkflowError(error instanceof Error ? error.message : "Error");
}

/**
 * Orquesta requests del Test Studio sin acoplarse al layout.
 * Mantiene un token de operación para ignorar respuestas tardías o de otro
 * workflow. No decide permisos ni niveles: el backend manda.
 */
export function useWorkflowTestRunner({
  workflowId,
  dirty,
  hasRealLane,
  onRun,
  onRan,
  onSaveBeforeRun,
}: {
  workflowId: string;
  dirty: boolean;
  hasRealLane: boolean;
  onRun: (run: RunDetail | null) => void;
  onRan?: () => void;
  onSaveBeforeRun?: () => Promise<boolean>;
}) {
  const { session } = useAuth();
  const [state, dispatch] = useReducer(
    workflowTestSessionReducer,
    undefined,
    () => createInitialTestSessionState("simulation"),
  );
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [elapsedMs, setElapsedMs] = useState(0);
  const busyRef = useRef(false);
  const operationRef = useRef(0);
  const identityRef = useRef(`${session?.organizationId ?? ""}:${workflowId}`);
  const mountedRef = useRef(true);

  const busy = isTestBusy(state.operation);

  const loadRuns = useCallback(async () => {
    if (!session) return;
    const identity = `${session.organizationId}:${workflowId}`;
    try {
      const data = await api<{ runs: WorkflowRun[] }>(`/api/v1/workflows/${workflowId}/runs`, {
        token: session.token,
        organizationId: session.organizationId,
      });
      if (identityRef.current === identity) setRuns(data.runs || []);
    } catch {
      if (identityRef.current === identity) setRuns([]);
    }
  }, [session, workflowId]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      busyRef.current = false;
    };
  }, []);

  useEffect(() => {
    identityRef.current = `${session?.organizationId ?? ""}:${workflowId}`;
    operationRef.current += 1;
    busyRef.current = false;
    dispatch({ type: "reset", level: "simulation" });
  }, [workflowId, session?.organizationId]);

  useEffect(() => {
    void loadRuns();
  }, [loadRuns]);

  useEffect(() => {
    if (!busy) {
      setElapsedMs(0);
      return;
    }
    const started = Date.now();
    setElapsedMs(0);
    const timer = window.setInterval(() => setElapsedMs(Date.now() - started), 1000);
    return () => window.clearInterval(timer);
  }, [busy]);

  function isCurrent(operationId: number): boolean {
    return (
      mountedRef.current &&
      operationRef.current === operationId &&
      identityRef.current === `${session?.organizationId ?? ""}:${workflowId}`
    );
  }

  function beginOperation(): number | null {
    if (!session || busyRef.current) return null;
    const operationId = operationRef.current + 1;
    operationRef.current = operationId;
    busyRef.current = true;
    return operationId;
  }

  function fail(operationId: number, message: string) {
    if (!isCurrent(operationId)) return;
    dispatch({ type: "failed", error: message, operationId });
  }

  async function saveIfNeeded(operationId: number): Promise<boolean> {
    if (!dirty || !onSaveBeforeRun) return true;
    dispatch({ type: "saving" });
    const saved = await onSaveBeforeRun();
    if (!saved) {
      fail(operationId, "No pude guardar el grafo, así que no ejecuto: correría una versión vieja.");
      return false;
    }
    if (!isCurrent(operationId)) return false;
    return true;
  }

  /** Devuelve un error de formulario si la acción no debe salir. */
  async function executeTest(level: TestLevel, asked: string, allowReal = false): Promise<string | null> {
    if (level !== "preview" && !asked.trim()) {
      return "Escribe un mensaje o usa un ejemplo para probar.";
    }
    if (!allowReal && (level === "sandbox" || level === "provider") && !hasRealLane) {
      return "Elige sandbox o proveedor antes de solicitar una prueba real.";
    }
    const operationId = beginOperation();
    if (operationId === null) return null;

    dispatch({ type: "start-test", level, operationId });
    onRun(null);
    try {
      if (!(await saveIfNeeded(operationId))) return null;
      const report = await api<TestReportOut>(`/api/v1/workflows/${workflowId}/test`, {
        method: "POST",
        token: session?.token,
        organizationId: session?.organizationId,
        body: JSON.stringify({
          requested_level: level,
          scenario: {
            scenario_id: "studio",
            messages: asked.trim() ? [asked.trim()] : [],
            max_segments: 8,
          },
        }),
      });
      if (!isCurrent(operationId)) return null;
      const testRun = buildTestRun(report);
      dispatch({ type: "test-completed", report, run: testRun, operationId });
      onRun(testRun);
      void loadRuns();
      return null;
    } catch (error) {
      fail(operationId, errorText(error));
      return null;
    } finally {
      if (operationRef.current === operationId) busyRef.current = false;
    }
  }

  async function confirmRealRun(payload: Record<string, unknown>) {
    const operationId = beginOperation();
    if (operationId === null) return;

    dispatch({ type: "start-run", operationId });
    onRun(null);
    try {
      if (!(await saveIfNeeded(operationId))) return;
      const out = await api<RunOut>(`/api/v1/workflows/${workflowId}/run`, {
        method: "POST",
        token: session?.token,
        organizationId: session?.organizationId,
        body: JSON.stringify({ payload, simulate: false }),
      });
      if (!isCurrent(operationId)) return;
      const runId = out.run_id ?? out.run?.run_id;
      if (!runId) {
        fail(operationId, "El workflow arrancó pero no devolvió un run identificable.");
        return;
      }
      const detail = await api<RunDetail>(`/api/v1/workflows/runs/${runId}`, {
        token: session?.token,
        organizationId: session?.organizationId,
      });
      if (!isCurrent(operationId)) return;
      dispatch({
        type: "run-completed",
        run: detail,
        plannedEffects: out.planned_effects,
        operationId,
      });
      onRun(detail);
      onRan?.();
      void loadRuns();
    } catch (error) {
      fail(operationId, errorText(error));
    } finally {
      if (operationRef.current === operationId) busyRef.current = false;
    }
  }

  async function loadLastSample(): Promise<{ payload?: string; note: string; error?: string }> {
    if (!session) return { note: "", error: "La sesión expiró. Vuelve a iniciar sesión." };
    try {
      const data = await api<{ run_id?: string | null; trigger_payload?: Record<string, unknown> }>(
        `/api/v1/workflows/${workflowId}/sample-outputs`,
        { token: session.token, organizationId: session.organizationId },
      );
      const payload = data.trigger_payload ?? {};
      if (data.run_id && Object.keys(payload).length > 0) {
        return {
          payload: JSON.stringify(payload, null, 2),
          note: "Payload del último run. No cambia el modo ni la versión del grafo.",
        };
      }
      return { note: "Todavía no hay una prueba anterior con datos; usa «Generar ejemplo»." };
    } catch (error) {
      return { note: "", error: errorText(error) };
    }
  }

  async function showRun(runId: string) {
    if (!session) return;
    const operationId = operationRef.current + 1;
    operationRef.current = operationId;
    busyRef.current = true;
    dispatch({ type: "loading-result" });
    onRun(null);
    try {
      const detail = await api<RunDetail>(`/api/v1/workflows/runs/${runId}`, {
        token: session.token,
        organizationId: session.organizationId,
      });
      if (!isCurrent(operationId)) return;
      dispatch({ type: "historical-run", run: detail });
      onRun(detail);
    } catch (error) {
      fail(operationId, errorText(error));
    } finally {
      if (operationRef.current === operationId) busyRef.current = false;
    }
  }

  return {
    state,
    dispatch,
    runs,
    busy,
    elapsedMs,
    executeTest,
    confirmRealRun,
    loadLastSample,
    showRun,
  };
}
