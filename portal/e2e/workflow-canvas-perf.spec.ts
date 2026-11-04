import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { mockWorkflowStudio, openMockStudio } from "./workflowStudioMock";

/**
 * Presupuesto de rendimiento del lienzo con un grafo grande (300 nodos):
 * tiempo hasta pintar, nodos montados (culling) y fotogramas durante el pan.
 */
const here = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(here, "..", "shots", "canvas-first", "perf.json");

function bigGraph(count: number) {
  const cols = 20;
  const nodes = Array.from({ length: count }, (_, i) => ({
    id: `n${i}`,
    type: i === 0 ? "trigger_webhook" : "notify",
    version: 1,
    label: i === 0 ? "Inicio" : `Paso ${i}`,
    position: { x: (i % cols) * 320, y: Math.floor(i / cols) * 180 },
    config: i === 0 ? {} : { channel: "in_app", title: `Paso ${i}` },
    input_ports: i === 0 ? [] : [{ name: "in", type: "json" }],
    output_ports: [{ name: "out", type: "json" }],
    retry_policy: { max_attempts: 1 },
    timeout_ms: 60000,
    error_policy: "fail",
    metadata: {},
  }));
  const edges = nodes.slice(1).map((n, i) => ({ id: `e${i}`, from_node: `n${i}`, from_port: "out", to_node: n.id, to_port: "in" }));
  return { workflow_version: 2, nodes, edges, variables: {}, entrypoints: ["n0"], metadata: { canvas: true } };
}

test.use({ viewport: { width: 1650, height: 922 } });

test("300 nodos: montaje acotado y pan fluido", async ({ page }) => {
  test.setTimeout(120_000);
  await mockWorkflowStudio(page, { graph: bigGraph(300) });
  const t0 = Date.now();
  await openMockStudio(page, 1);
  const firstPaint = Date.now() - t0;

  // Acercar al 100 % para que el culling tenga efecto.
  await page.getByTestId("wf-zoom-level").click();
  await page.waitForTimeout(200);
  const mounted = await page.getByTestId("wf-canvas-node").count();

  const canvas = page.getByTestId("workflow-canvas");
  const box = (await canvas.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  const frames = page.evaluate(
    () =>
      new Promise<number[]>((resolve) => {
        const deltas: number[] = [];
        let last = performance.now();
        const start = last;
        const tick = (now: number) => {
          deltas.push(now - last);
          last = now;
          if (now - start < 1500) requestAnimationFrame(tick);
          else resolve(deltas);
        };
        requestAnimationFrame(tick);
      }),
  );
  for (let i = 0; i < 60; i++) {
    await page.mouse.wheel(18, 10);
  }
  const deltas = (await frames).slice(1).sort((a, b) => a - b);
  const p95 = deltas[Math.floor(deltas.length * 0.95)] ?? 0;
  const worst = deltas.at(-1) ?? 0;

  const report = { nodes: 300, firstPaintMs: firstPaint, mountedAt100: mounted, frames: deltas.length, p95FrameMs: Number(p95.toFixed(1)), worstFrameMs: Number(worst.toFixed(1)) };
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  fs.writeFileSync(OUT, JSON.stringify(report, null, 2));
  console.log("PERF", JSON.stringify(report));

  expect(mounted).toBeLessThan(300);
  expect(p95).toBeLessThan(50);
});
