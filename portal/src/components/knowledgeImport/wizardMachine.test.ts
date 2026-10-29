import { describe, expect, it } from "vitest";

import {
  canAskBatch,
  initialWizardBatch,
  wizardBatchReducer,
  type WizardBatchState,
} from "./wizardMachine";

function reduce(
  events: Parameters<typeof wizardBatchReducer>[1][],
): WizardBatchState {
  return events.reduce(wizardBatchReducer, initialWizardBatch);
}

describe("wizardBatchReducer", () => {
  it("no pasa a comprobar hasta confirmar todos los archivos", () => {
    let state = reduce([{ type: "start", total: 3 }]);
    expect(state.phase).toBe("transfer");

    state = wizardBatchReducer(state, { type: "uploaded", ok: true });
    state = wizardBatchReducer(state, { type: "uploaded", ok: false });
    expect(state.phase).toBe("transfer");
    expect(state.confirmed).toBe(1);
    expect(state.failed).toBe(1);

    state = wizardBatchReducer(state, { type: "uploaded", ok: true });
    expect(state.phase).toBe("processing");
    expect(state.confirmed).toBe(2);
    expect(state.failed).toBe(1);
  });

  it("no permite preguntar sin sesión o sin fuentes listas", () => {
    const processing = reduce([
      { type: "start", total: 1 },
      { type: "uploaded", ok: true },
    ]);
    expect(canAskBatch(processing)).toBe(false);

    const available = wizardBatchReducer(processing, {
      type: "settled",
      ready: 1,
      failed: 0,
      total: 1,
    });
    expect(canAskBatch(available)).toBe(false);

    const withSession = wizardBatchReducer(available, {
      type: "session",
      sessionId: "ses-1",
    });
    expect(canAskBatch(withSession)).toBe(true);
  });

  it("distingue parcial, disponible y fallido", () => {
    const base = reduce([
      { type: "start", total: 3 },
      { type: "uploaded", ok: true },
      { type: "uploaded", ok: true },
      { type: "uploaded", ok: false },
      { type: "session", sessionId: "ses-1" },
    ]);
    expect(
      wizardBatchReducer(base, {
        type: "settled",
        ready: 2,
        failed: 1,
        total: 3,
      }).phase,
    ).toBe("partial");
    expect(
      wizardBatchReducer(base, {
        type: "settled",
        ready: 3,
        failed: 0,
        total: 3,
      }).phase,
    ).toBe("available");
    expect(
      wizardBatchReducer(base, {
        type: "settled",
        ready: 0,
        failed: 3,
        total: 3,
      }).phase,
    ).toBe("failed");
  });

  it("ignora eventos tardíos que intentan retroceder", () => {
    const available = reduce([
      { type: "start", total: 1 },
      { type: "uploaded", ok: true },
      { type: "settled", ready: 1, failed: 0, total: 1 },
    ]);
    const late = wizardBatchReducer(available, { type: "processing" });
    expect(late.phase).toBe("available");
    const lateUpload = wizardBatchReducer(available, {
      type: "uploaded",
      ok: true,
    });
    expect(lateUpload).toEqual(available);
  });

  it("reset prepara un lote nuevo sin reutilizar la sesión sellada", () => {
    const state = reduce([
      { type: "start", total: 1 },
      { type: "uploaded", ok: true },
      { type: "session", sessionId: "ses-1" },
      { type: "reset" },
    ]);
    expect(state).toEqual(initialWizardBatch);
  });
});
