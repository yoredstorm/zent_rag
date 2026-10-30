import type {
  TestLevel,
  TestSessionAction,
  TestSessionState,
} from "./workflowTestTypes";

export function createInitialTestSessionState(level: TestLevel = "simulation"): TestSessionState {
  return {
    view: "setup",
    operation: "idle",
    requestedLevel: level,
    runKind: null,
    providerVerified: false,
    selectedPane: "answer",
    report: null,
    run: null,
    error: "",
    notice: "",
    historyOpen: false,
    historicalRun: false,
    operationId: 0,
  };
}

export function isTestBusy(operation: TestSessionState["operation"]): boolean {
  return (
    operation === "saving" ||
    operation === "preparing" ||
    operation === "executing" ||
    operation === "loading_result"
  );
}

export function workflowTestSessionReducer(
  state: TestSessionState,
  action: TestSessionAction,
): TestSessionState {
  switch (action.type) {
    case "select-level":
      if (isTestBusy(state.operation)) return state;
      return {
        ...state,
        requestedLevel: action.level,
        error: "",
        notice: "",
      };

    case "saving":
      return { ...state, operation: "saving", error: "" };

    case "start-test":
      return {
        ...state,
        requestedLevel: action.level,
        operation: "preparing",
        operationId: action.operationId,
        runKind: "test_report",
        resultCode: undefined,
        providerVerified: false,
        activeRunId: undefined,
        effectiveLevel: undefined,
        report: null,
        run: null,
        plannedEffects: undefined,
        error: "",
        notice: "",
        view: "setup",
        historicalRun: false,
        historicalHash: undefined,
      };

    case "start-run":
      return {
        ...state,
        operation: "executing",
        operationId: action.operationId,
        runKind: "execution_run",
        resultCode: undefined,
        providerVerified: false,
        activeRunId: undefined,
        effectiveLevel: undefined,
        report: null,
        run: null,
        plannedEffects: undefined,
        error: "",
        notice: "",
        view: "setup",
        historicalRun: false,
        historicalHash: undefined,
      };

    case "loading-result":
      return { ...state, operation: "loading_result", error: "" };

    case "test-completed":
      return {
        ...state,
        view: "result",
        operation: "completed",
        requestedLevel: (action.report.requested_level as TestLevel) ?? state.requestedLevel,
        effectiveLevel: (action.report.effective_level as TestLevel) ?? state.requestedLevel,
        runKind: "test_report",
        resultCode: action.report.result,
        providerVerified: Boolean(action.report.provider_verified),
        activeRunId: action.run.id,
        selectedPane: "answer",
        report: action.report,
        run: action.run,
        plannedEffects: undefined,
        error: "",
        notice: "",
        historicalRun: false,
        historicalHash: undefined,
        operationId: action.operationId,
      };

    case "run-completed":
      return {
        ...state,
        view: "result",
        operation: "completed",
        runKind: "execution_run",
        resultCode: action.run.status,
        providerVerified: false,
        activeRunId: action.run.id,
        selectedPane: "answer",
        report: null,
        run: action.run,
        plannedEffects: action.plannedEffects,
        error: "",
        notice: "",
        historicalRun: false,
        historicalHash: undefined,
        operationId: action.operationId,
      };

    case "failed": {
      const hasResult = Boolean(state.report || state.run);
      return {
        ...state,
        operation: "failed",
        error: action.error,
        view: hasResult ? "result" : "setup",
        operationId: action.operationId,
      };
    }

    case "historical-run":
      return {
        ...state,
        view: "result",
        operation: "completed",
        report: null,
        run: action.run,
        plannedEffects: undefined,
        runKind: "execution_run",
        resultCode: action.run.status,
        providerVerified: false,
        activeRunId: action.run.id,
        selectedPane: "path",
        error: "",
        notice: "Resultado histórico. No es el estado actual del grafo.",
        historicalRun: true,
        historicalHash: action.historicalHash,
      };

    case "show-setup":
      return { ...state, view: "setup", selectedPane: "answer", notice: "" };

    case "show-result":
      return {
        ...state,
        view: "result",
        selectedPane: action.pane ?? state.selectedPane,
      };

    case "toggle-history":
      return {
        ...state,
        historyOpen: action.open ?? !state.historyOpen,
      };

    case "reset":
      return createInitialTestSessionState(action.level ?? state.requestedLevel);

    default:
      return state;
  }
}
