import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AdminRuntimePage from "./Runtime";

vi.mock("../../api", () => ({
  platformApi: vi.fn(),
}));

vi.mock("../../platformAuth", () => ({
  usePlatformAuth: () => ({ session: { token: "t" } }),
}));

import { platformApi } from "../../api";

describe("AI Runtime admin page", () => {
  beforeEach(() => {
    vi.mocked(platformApi).mockImplementation(async (path: string) => {
      if (path.includes("/dashboard")) {
        return {
          decisions: {
            decisions_today: 4,
            rules_pct: 25,
            jev_pct: 50,
            small_llm_pct: 15,
            reasoning_llm_pct: 10,
            average_confidence: 0.8,
            fallback_rate: 0.1,
            average_latency_ms: 120,
          },
          usage: {
            requests: 10,
            tokens: 1000,
            cost: 0.12,
            average_cost: 0.012,
            weighted_average_cost: 0.012,
            by_event_type: [],
            by_provider: [],
          },
          efficiency: {
            score: 0.77,
            components: { quality: 0.8, cost: 0.7, latency: 0.9, fallback: 0.9 },
            weights: { quality: 0.4, cost: 0.25, latency: 0.2, fallback: 0.15 },
            formula: "weighted sum",
          },
          llm_calls_avoided_estimate: 3,
          flags: { decision_mode: "legacy" },
        };
      }
      if (path.includes("/providers")) return { prices: [] };
      if (path.includes("/capabilities")) return { items: [] };
      return {};
    });
  });

  it("renders AI Runtime dashboard", async () => {
    render(
      <MemoryRouter>
        <AdminRuntimePage />
      </MemoryRouter>,
    );
    expect(await screen.findByText("AI Runtime")).toBeInTheDocument();
    expect(await screen.findByText("AI Efficiency Score")).toBeInTheDocument();
  });
});
