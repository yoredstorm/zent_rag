import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AgentMemoryPanel } from "./AgentMemoryPanel";

describe("AgentMemoryPanel", () => {
  it("muestra solo la memoria autorizada por la política del rol", async () => {
    render(
      <AgentMemoryPanel
        agents={[{ id: "agent-1", name: "Mentor" }]}
        loadContext={async (agentId) => ({
          agent_id: agentId,
          policy: "long_term_consent",
          included: 1,
          omitted: 1,
          inspected: 2,
          items: [
            {
              memory_id: "mem-1",
              title: "Progreso consentido",
              scope: "long_term_consent",
              confidence: 0.9,
              memory_type: "operational",
            },
          ],
          omitted_items: [{ memory_id: "mem-2", reason: "workspace_mismatch" }],
        })}
      />
    );

    expect(await screen.findByText("Progreso consentido")).toBeInTheDocument();
    expect(screen.getByTestId("wf-agent-memory-summary")).toHaveTextContent("long_term_consent");
    expect(screen.getByTestId("wf-agent-memory-summary")).toHaveTextContent("1 incluidas");
    expect(screen.getByTestId("wf-agent-memory-omitted")).toHaveTextContent("workspace_mismatch");
  });

  it("explica cuando el workflow no tiene agentes", () => {
    render(<AgentMemoryPanel agents={[]} />);
    expect(screen.getByTestId("wf-agent-memory-empty")).toHaveTextContent("no tiene agentes");
  });
});
