import axe from "axe-core";
import { expect } from "vitest";

/**
 * Helper de accesibilidad para tests unitarios (FASE 04).
 * Corre axe-core sobre el contenedor y falla si hay violaciones serias.
 */
export async function expectAxeToHaveNoViolations(container: HTMLElement) {
  const results = await axe.run(container, {
    rules: {
      "color-contrast": { enabled: false },
    },
  });
  const serious = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical"
  );
  if (serious.length > 0) {
    const summary = serious
      .map((v) => `${v.id}: ${v.help} (${v.impact})`)
      .join("\n");
    expect.fail(`Violaciones de accesibilidad:\n${summary}`);
  }
}