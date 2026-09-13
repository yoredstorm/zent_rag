import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NotificationBuilder } from "./NotificationBuilder";
import { ScheduleBuilder } from "./ScheduleBuilder";

const AUTH = vi.hoisted(() => ({
  session: { token: "rag_sess_t", organizationId: "org-1", roles: ["owner"], permissions: [] },
}));

vi.mock("../../auth", () => ({ useAuth: () => AUTH }));

const TARGETS = {
  channels: [
    { value: "in_app", label: "Zent", available: true, requires: null, detail: "Centro de Zent." },
    { value: "email", label: "Correo", available: true, requires: null, detail: "SMTP configurado." },
    { value: "slack", label: "Slack", available: false, requires: "slack", detail: "Necesitas conectar Slack para usar esta acción." },
  ],
  people: [{ id: "u1", email: "compras@zent.pe", label: "compras@zent.pe" }],
  teams: [{ id: "g1", label: "Compras" }],
};

function stubTargets() {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify(TARGETS), { status: 200, headers: { "Content-Type": "application/json" } }),
      ),
    ),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("NotificationBuilder", () => {
  it("muestra canales reales y avisa los no conectados", async () => {
    stubTargets();
    render(
      <MemoryRouter>
        <NotificationBuilder config={{}} dataSources={[]} onChange={() => undefined} />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("wf-notify-channel-detail")).toHaveTextContent("Centro de Zent."));
    expect(screen.getByTestId("wf-notify-connect-slack")).toBeInTheDocument();
    const slackOption = screen.getByRole("option", { name: /Slack \(no disponible\)/ });
    expect(slackOption).toBeDisabled();
  });

  it("añade una persona como destinatario", async () => {
    stubTargets();
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <MemoryRouter>
        <NotificationBuilder config={{}} dataSources={[]} onChange={onChange} />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("wf-notify-recipient-value")).toBeInTheDocument());
    await user.selectOptions(screen.getByTestId("wf-notify-recipient-value"), "u1");
    await user.click(screen.getByTestId("wf-notify-recipient-add"));
    expect(onChange).toHaveBeenCalledWith({
      recipients: [{ kind: "person", value: "u1", label: "compras@zent.pe" }],
    });
  });

  it("lista destinatarios existentes y permite quitarlos", async () => {
    stubTargets();
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <MemoryRouter>
        <NotificationBuilder
          config={{ recipients: [{ kind: "team", value: "g1", label: "Compras" }] }}
          dataSources={[]}
          onChange={onChange}
        />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("wf-notify-recipients")).toHaveTextContent("Compras");
    await user.click(screen.getByLabelText("Quitar Compras"));
    expect(onChange).toHaveBeenCalledWith({ recipients: [] });
  });
});

describe("ScheduleBuilder", () => {
  function ScheduleHarness({
    initial,
    onChange,
  }: {
    initial: Record<string, unknown>;
    onChange?: (patch: Record<string, unknown>) => void;
  }) {
    const [config, setConfig] = useState(initial);
    return (
      <ScheduleBuilder
        config={config}
        onChange={(patch) => {
          setConfig((prev) => ({ ...prev, ...patch }));
          onChange?.(patch);
        }}
      />
    );
  }

  it("describe el schedule diario y permite cambiar la hora", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<ScheduleHarness initial={{ schedule: { mode: "daily", time: "08:00", timezone: "America/Lima" } }} onChange={onChange} />);
    expect(screen.getByTestId("wf-schedule-preview")).toHaveTextContent("Todos los días a las 8:00 a. m.");
    const time = screen.getByTestId("wf-schedule-time");
    await user.clear(time);
    await user.type(time, "10:30");
    expect(onChange).toHaveBeenCalled();
    const last = onChange.mock.calls[onChange.mock.calls.length - 1][0].schedule;
    expect(last.time).toBe("10:30");
  });

  it("cambia a semanal y alterna días con preview humano", async () => {
    const user = userEvent.setup();
    render(<ScheduleHarness initial={{ schedule: { mode: "daily", time: "09:00", timezone: "UTC" } }} />);
    await user.selectOptions(screen.getByTestId("wf-schedule-mode"), "weekly");
    expect(screen.getByTestId("wf-schedule-days")).toBeInTheDocument();
    await user.click(screen.getByTestId("wf-schedule-day-0"));
    await user.click(screen.getByTestId("wf-schedule-day-4"));
    expect(screen.getByTestId("wf-schedule-preview")).toHaveTextContent("Los lunes y viernes a las 9:00 a. m.");
  });

  it("modo avanzado muestra cron", async () => {
    const user = userEvent.setup();
    render(<ScheduleHarness initial={{ schedule: { mode: "daily", time: "09:00", timezone: "UTC" } }} />);
    await user.selectOptions(screen.getByTestId("wf-schedule-mode"), "cron");
    expect(screen.getByTestId("wf-schedule-cron")).toBeInTheDocument();
    expect(screen.getByTestId("wf-schedule-preview")).toHaveTextContent("cron");
  });
});
