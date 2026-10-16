import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { InstanceTimeline } from "./InstanceTimeline";

const AUTH = vi.hoisted(() => ({
  session: { token: "rag_sess_t", organizationId: "org-1", roles: ["owner"], permissions: [] },
}));

vi.mock("../../auth", () => ({ useAuth: () => AUTH }));

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

const TIMELINE = {
  instance: {
    id: "i1",
    status: "WAITING",
    waiting_event_type: "conversation.message",
    state: { cart: { items: [{ sku: "ARZ-1" }] } },
  },
  runs: [
    {
      run_id: "r1",
      status: "waiting",
      trigger: "manual",
      instance_seq: 1,
      started_at: "2026-10-16T10:02:00Z",
    },
  ],
  signals: [
    {
      signal_id: "s1",
      event_type: "conversation.message",
      status: "consumed",
      external_event_id: "wa-msg-1",
      received_at: "2026-10-16T10:04:00Z",
    },
  ],
  events: [
    { id: "e1", kind: "wait_entered", node_id: "w1", created_at: "2026-10-16T10:02:30Z" },
  ],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("InstanceTimeline", () => {
  it("muestra estado, timeline unificado y State sin secretos", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(json(TIMELINE))));
    const user = userEvent.setup();
    render(<InstanceTimeline instanceId="i1" />);

    await waitFor(() =>
      expect(screen.getByTestId("wf-instance-status")).toHaveTextContent("WAITING"),
    );
    const items = screen.getByTestId("wf-instance-timeline-items");
    expect(items).toHaveTextContent("Run 1 · manual");
    expect(items).toHaveTextContent("Señal · conversation.message");
    expect(items).toHaveTextContent("wait_entered · w1");

    await user.click(screen.getByTestId("wf-instance-state-toggle"));
    expect(screen.getByTestId("wf-instance-state")).toHaveTextContent('"sku": "ARZ-1"');
  });
});
