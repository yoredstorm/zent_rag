import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { studioApi as api } from "../../lib/studioApi";
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
  conversational = false,
  onRun,
  onRan,
  onSaveBeforeRun,
}: {
  workflowId: string;
  dirty: boolean;
  hasRealLane: boolean;
  /** El grafo escucha `conversation.message` y espera respuestas. */
  conversational?: boolean;
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
  const followRef = useRef<{
    token: number;
    timer: number | null;
    abort: AbortController | null;
  }>({ token: 0, timer: null, abort: null });

  const busy = isTestBusy(state.operation);

  const stopFollow = useCallback(() => {
    followRef.current.token += 1;
    if (followRef.current.timer !== null) {
      window.clearTimeout(followRef.current.timer);
      followRef.current.timer = null;
    }
    followRef.current.abort?.abort();
    followRef.current.abort = null;
  }, []);

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
      stopFollow();
    };
  }, [stopFollow]);

  useEffect(() => {
    identityRef.current = `${session?.organizationId ?? ""}:${workflowId}`;
    operationRef.current += 1;
    busyRef.current = false;
    stopFollow();
    dispatch({ type: "reset", level: "simulation" });
  }, [workflowId, session?.organizationId, stopFollow]);

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

  async function confirmRealRun(
    payload: Record<string, unknown>,
    options?: { idempotencyKey?: string },
  ) {
    const operationId = beginOperation();
    if (operationId === null) return;

    dispatch({ type: "start-run", operationId });
    onRun(null);
    try {
      if (!(await saveIfNeeded(operationId))) return;
      // Un grafo conversacional necesita una llave estable para correlacionar
      // cada mensaje con ESTA conversación y un número de pedido para bodega.
      const effectivePayload = conversational
        ? {
            ...payload,
            customer_ref:
              String(payload.customer_ref || "").trim() ||
              `WEB-${crypto.randomUUID().slice(0, 8).toUpperCase()}`,
            order_number:
              String(payload.order_number || "").trim() ||
              `WEB-${crypto.randomUUID().slice(0, 8).toUpperCase()}`,
          }
        : payload;
      // Una intención real = una llave. Reintentos del mismo payload reutilizan
      // la llave; un payload nuevo debe generar otra intención en la UI.
      const idempotencyKey = options?.idempotencyKey || `wf-run-${crypto.randomUUID()}`;
      const out = await api<RunOut>(`/api/v1/workflows/${workflowId}/run`, {
        method: "POST",
        token: session?.token,
        organizationId: session?.organizationId,
        headers: { "Idempotency-Key": idempotencyKey },
        body: JSON.stringify({ payload: effectivePayload, simulate: false }),
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
        instanceId: out.instance_id ?? detail.instance_id ?? undefined,
        durableStatus: out.status,
        operationId,
      });
      onRun(detail);
      onRan?.();
      void loadRuns();
      if (out.instance_id) {
        void followInstance(
          out.instance_id,
          operationId,
          runId,
        );
      }
    } catch (error) {
      fail(operationId, errorText(error));
    } finally {
      if (operationRef.current === operationId) busyRef.current = false;
    }
  }

  async function followInstance(
    instanceId: string,
    operationId: number,
    initialRunId: string,
  ) {
    stopFollow();
    const token = followRef.current.token;
    const terminal = new Set(["COMPLETED", "FAILED", "CANCELLED", "EXPIRED", "SUSPENDED"]);
    let delay = 1500;
    let lastRunId = initialRunId;
    dispatch({ type: "durable-status", status: "RUNNING" });
    while (
      mountedRef.current &&
      isCurrent(operationId) &&
      followRef.current.token === token
    ) {
      await new Promise<void>((resolve) => {
        followRef.current.timer = window.setTimeout(resolve, delay);
      }).catch(() => undefined);
      if (!mountedRef.current || !isCurrent(operationId)) return;
      if (followRef.current.token !== token) return;
      const controller = new AbortController();
      followRef.current.abort = controller;
      try {
        const instance = await api<{
          id: string;
          status: string;
          last_run_id?: string | null;
          waiting_event_type?: string | null;
        }>(`/api/v1/workflows/instances/${instanceId}`, {
          token: session?.token,
          organizationId: session?.organizationId,
          signal: controller.signal,
        });
        if (!mountedRef.current || !isCurrent(operationId)) return;
        const status = String(instance.status || "").toUpperCase();
        const notice =
          status === "WAITING"
            ? instance.waiting_event_type
              ? `Esperando "${instance.waiting_event_type}". La instancia sigue viva.`
              : "Esperando señal. La instancia sigue viva."
            : status === "SUSPENDED"
              ? "Instancia suspendida. Reanúdala para continuar; no se envió nada."
              : "";
        dispatch({ type: "durable-status", status, notice });
        if (instance.last_run_id && instance.last_run_id !== lastRunId) {
          try {
            const detail = await api<RunDetail>(
              `/api/v1/workflows/runs/${instance.last_run_id}`,
              {
                token: session?.token,
                organizationId: session?.organizationId,
                signal: controller.signal,
              },
            );
            if (!mountedRef.current || !isCurrent(operationId)) return;
            lastRunId = instance.last_run_id;
            dispatch({
              type: "run-refreshed",
              run: detail,
              durableStatus: status,
              notice,
            });
            onRun(detail);
            void loadRuns();
          } catch {
            if (!mountedRef.current || !isCurrent(operationId)) return;
            dispatch({
              type: "durable-status",
              status,
              notice: `${notice} No pude cargar el nuevo segmento.`.trim(),
            });
          }
        }
        if (terminal.has(status)) return;
        delay = Math.min(Math.round(delay * 1.6), 10000);
      } catch {
        if (controller.signal.aborted) return;
        if (!mountedRef.current || !isCurrent(operationId)) return;
        dispatch({
          type: "durable-status",
          status: "CONNECTION_LOST",
          notice: "Conexión perdida con la instancia. Reintentando; no se ejecutó otro run.",
        });
        delay = Math.min(Math.round(delay * 2), 15000);
      } finally {
        if (followRef.current.abort === controller) followRef.current.abort = null;
      }
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

  /**
   * Responde a una instancia durable que espera `conversation.message`.
   * La correlación sale del propio estado de la instancia, no de memoria local:
   * recargar la página no rompe la conversación.
   */
  async function sendMessage(text: string): Promise<string | null> {
    const trimmed = text.trim();
    if (!trimmed) return "Escribe un mensaje para el flujo.";
    const instanceId = state.instanceId;
    if (!instanceId) {
      return "No hay una instancia durable activa. Ejecuta el flujo en modo Real.";
    }
    const operationId = beginOperation();
    if (operationId === null) return null;
    dispatch({ type: "sending-message" });
    try {
      const instance = await api<{
        id: string;
        status: string;
        last_run_id?: string | null;
        waiting_event_type?: string | null;
        waiting_for?: { correlation?: Record<string, unknown> };
        state?: { order?: { order_number?: string } };
      }>(`/api/v1/workflows/instances/${instanceId}`, {
        token: session?.token,
        organizationId: session?.organizationId,
      });
      if (!isCurrent(operationId)) return null;
      if (String(instance.status || "").toUpperCase() !== "WAITING") {
        return "La instancia ya no está esperando un mensaje. Inicia una conversación nueva.";
      }
      const correlationValue = String(
        instance.waiting_for?.correlation?.order_number ??
          instance.state?.order?.order_number ??
          "",
      );
      const result = await api<{
        status: string;
        resumed: boolean;
        results?: Array<{ status?: string; run?: { run_id?: string } }>;
      }>(`/api/v1/workflows/instances/${instanceId}/signal`, {
        method: "POST",
        token: session?.token,
        organizationId: session?.organizationId,
        body: JSON.stringify({
          event_type: "conversation.message",
          correlation: correlationValue ? { order_number: correlationValue } : {},
          payload: { text: trimmed },
        }),
      });
      if (!isCurrent(operationId)) return null;
      if (!result.resumed) {
        return "El mensaje no despertó la instancia (correlación distinta). Vuelve a iniciar la conversación.";
      }
      const runId =
        result.results?.[0]?.run?.run_id || instance.last_run_id || null;
      const detail = runId
        ? await api<RunDetail>(`/api/v1/workflows/runs/${runId}`, {
            token: session?.token,
            organizationId: session?.organizationId,
          })
        : null;
      if (!isCurrent(operationId)) return null;
      const durableStatus = String(
        result.results?.[0]?.status || instance.status || "",
      ).toUpperCase();
      if (detail) {
        dispatch({
          type: "run-refreshed",
          run: detail,
          durableStatus,
          notice: "",
        });
        onRun(detail);
        if (detail.id) void followInstance(instanceId, operationId, detail.id);
      }
      void loadRuns();
      return null;
    } catch (error) {
      fail(operationId, errorText(error));
      return null;
    } finally {
      if (operationRef.current === operationId) busyRef.current = false;
    }
  }

  /** Refresca el run de la instancia (p. ej. tras aprobar o rechazar). */
  async function refreshInstance(): Promise<void> {
    const instanceId = state.instanceId;
    if (!instanceId || !session) return;
    try {
      const instance = await api<{ status: string; last_run_id?: string | null }>(
        `/api/v1/workflows/instances/${instanceId}`,
        { token: session.token, organizationId: session.organizationId },
      );
      if (!instance.last_run_id) return;
      const detail = await api<RunDetail>(
        `/api/v1/workflows/runs/${instance.last_run_id}`,
        { token: session.token, organizationId: session.organizationId },
      );
      dispatch({
        type: "run-refreshed",
        run: detail,
        durableStatus: String(instance.status || "").toUpperCase(),
        notice: "",
      });
      onRun(detail);
    } catch {
      // El polling de la instancia sigue activo; un fallo puntual no rompe el panel.
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
    sendMessage,
    refreshInstance,
    loadLastSample,
    showRun,
  };
}
