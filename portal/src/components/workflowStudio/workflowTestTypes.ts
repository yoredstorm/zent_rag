import type { RunDetail } from "../WorkflowRunInspector";
import type { WorkflowGraph } from "../../lib/workflowGraph";
import type { EffectVerification } from "../../lib/workflowEffects";
import type { WorkflowRun } from "./types";

/** Los cuatro niveles reales del backend. No agregar ni renombrar. */
export const TEST_LEVELS = ["preview", "simulation", "sandbox", "provider"] as const;
export type TestLevel = (typeof TEST_LEVELS)[number];

export type TestView = "setup" | "result";
export type TestOperation =
  | "idle"
  | "saving"
  | "preparing"
  | "executing"
  | "loading_result"
  | "completed"
  | "failed";
export type TestRunKind = "test_report" | "execution_run";
export type ResultPane = "answer" | "path" | "verification";
export type RealLane = "sandbox" | "provider";

export type TestReportOut = {
  test_report_id?: string;
  report_id?: string;
  requested_level: string;
  effective_level: string;
  capped_reason?: string | null;
  provider_verified: boolean;
  result: string;
  state?: string;
  why?: string;
  hashes?: Record<string, string>;
  timeline?: unknown[];
  executed_nodes?: unknown[];
  readiness?: {
    sandbox_ready?: boolean;
    provider_ready?: boolean;
    reasons?: string[];
    provider_refs?: string[];
  };
  explain?: Record<string, unknown>;
  simulation?: Record<string, unknown> | null;
  verification?: Record<string, unknown> | null;
  created_at?: string;
};

export type RunOut = {
  /** Run simple: el backend devuelve el id en la raíz. */
  run_id?: string;
  /** Run durable: el backend envuelve el run (y puede quedar esperando). */
  run?: { run_id: string; status?: string };
  status?: string;
  planned_effects?: { node_id: string; node_type: string; planned: Record<string, unknown> }[];
  effect_verification?: EffectVerification;
  result?: unknown;
};

export type TestRunHistory = WorkflowRun;

export type TestSessionState = {
  view: TestView;
  operation: TestOperation;
  requestedLevel: TestLevel;
  effectiveLevel?: TestLevel;
  runKind: TestRunKind | null;
  resultCode?: string;
  providerVerified: boolean;
  activeRunId?: string;
  selectedPane: ResultPane;
  report: TestReportOut | null;
  run: RunDetail | null;
  plannedEffects?: RunOut["planned_effects"];
  error: string;
  notice: string;
  historyOpen: boolean;
  historicalRun: boolean;
  historicalHash?: string;
  operationId: number;
};

export type TestSessionAction =
  | { type: "select-level"; level: TestLevel }
  | { type: "show-setup" }
  | { type: "show-result"; pane?: ResultPane }
  | { type: "start-test"; level: TestLevel; operationId: number }
  | { type: "start-run"; operationId: number }
  | { type: "saving" }
  | { type: "loading-result" }
  | {
      type: "test-completed";
      report: TestReportOut;
      run: RunDetail;
      operationId: number;
    }
  | {
      type: "run-completed";
      run: RunDetail;
      plannedEffects?: RunOut["planned_effects"];
      operationId: number;
    }
  | { type: "failed"; error: string; operationId: number }
  | {
      type: "historical-run";
      run: RunDetail;
      historicalHash?: string;
    }
  | { type: "toggle-history"; open?: boolean }
  | { type: "reset"; level?: TestLevel };

export type GenerateSampleInput = {
  graph?: WorkflowGraph | null;
};

export type ComposerPayload = {
  raw: string;
  normalized: { payload: Record<string, unknown>; wrapped: boolean };
  isJsonObject: boolean;
};
