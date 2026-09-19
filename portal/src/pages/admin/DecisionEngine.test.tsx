import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DecisionEnginePage from "./DecisionEngine";

vi.mock("../../api", () => ({
  platformApi: vi.fn(),
}));

vi.mock("../../platformAuth", () => ({
  usePlatformAuth: () => ({ session: { token: "t" } }),
}));

import { platformApi } from "../../api";

describe("DecisionEngine admin page", () => {
  beforeEach(() => {
    vi.mocked(platformApi).mockImplementation(async (path: string) => {
      if (path.includes("/adaptive/status")) {
        return {
          mode: "off",
          canary_percentage: 0,
          max_retrieval_attempts: 3,
          top_k: { min: 3, max: 12 },
          jev_evidence: true,
          fast_path: true,
          rewrite: true,
          policy_version: "adaptive-v1",
        };
      }
      if (path.includes("/status")) {
        return {
          primary_provider: "rules",
          fallback: "gpt-4o-mini",
          mode: "legacy",
          shadow: false,
          high_confidence: 0.9,
          low_confidence: 0.65,
          canary_percentage: 0,
          jev_status: "not_configured",
          rules_loaded: true,
        };
      }
      if (path.includes("/dashboard")) {
        return {
          decisions_today: 0,
          rules_pct: 0,
          jev_pct: 0,
          small_llm_pct: 0,
          reasoning_llm_pct: 0,
          average_confidence: 0,
          fallback_rate: 0,
          average_latency_ms: 0,
          estimated_savings: 0,
        };
      }
      return { items: [] };
    });
  });

  it("renders Decision Engine status", async () => {
    render(
      <MemoryRouter>
        <DecisionEnginePage />
      </MemoryRouter>
    );
    expect(await screen.findByText("Decision Engine")).toBeInTheDocument();
    expect(await screen.findByText("legacy")).toBeInTheDocument();
    expect(screen.getByText("rules")).toBeInTheDocument();
  });
});
