export type OnboardingKind =
  | "database"
  | "documents"
  | "spreadsheets"
  | "drive"
  | "website"
  | "api";

export type SessionStatus =
  | "NOT_STARTED"
  | "CONNECTING"
  | "CONNECTED"
  | "DISCOVERING"
  | "ANALYZING"
  | "REVIEW_REQUIRED"
  | "TESTING"
  | "READY"
  | "NEEDS_ATTENTION"
  | "FAILED";

export type WizardStep =
  | "choose"
  | "connect"
  | "analyze"
  | "review"
  | "confirm"
  | "test"
  | "ready";

export type OnboardingSession = {
  id: string;
  kind: OnboardingKind;
  status: SessionStatus;
  step: WizardStep;
  connector_id: string | null;
  catalog_source_id: string | null;
  kb_source_id: string | null;
  skipped_review: boolean;
  skipped_test: boolean;
  usable: boolean;
  warning: string | null;
  state: Record<string, unknown>;
  connection?: {
    ok?: boolean;
    latency_ms?: number;
    server_version?: string | null;
    tables?: number;
    columns?: number;
    message?: string;
  };
  preview?: unknown;
  understanding?: Understanding;
};

export type Suggestion = {
  id: string;
  type: string;
  title: string;
  description: string | null;
  confidence: string;
  evidence: string[];
  payload: Record<string, unknown>;
};

export type Understanding = {
  kind?: string;
  filename?: string;
  row_count?: number;
  likely_entity?: string;
  columns?: Array<{
    physical_name: string;
    inferred_type?: string;
    null_ratio?: number;
    possible_meanings?: [string, number][];
    uncertain?: boolean;
  }>;
  interpretation?: Array<{ physical: string; business: string }>;
  entities?: Array<{ name: string; confidence?: string }>;
  relationships?: Array<{ from?: string; to?: string }>;
  title?: string;
  topics?: string[];
  document_type?: string;
  dates?: string[];
  headings?: string[];
  suggestions?: Suggestion[];
};

export type ProgressPayload = {
  session: OnboardingSession;
  phases: Array<{ id: string; label: string; state: string }>;
  headline: string;
  technical_details: Record<string, unknown>;
};

export const WIZARD_STEPS: { id: WizardStep; label: string }[] = [
  { id: "choose", label: "Elegir" },
  { id: "connect", label: "Conectar" },
  { id: "analyze", label: "Analizar" },
  { id: "review", label: "Revisar" },
  { id: "test", label: "Probar" },
  { id: "ready", label: "Listo" },
];

export const API = "/api/v1/data-onboarding";
