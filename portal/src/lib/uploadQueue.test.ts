import { describe, expect, it } from "vitest";
import { ApiError } from "./errors";
import {
  MAX_UPLOAD_BYTES,
  fileRowId,
  isOversized,
  jobRowStatus,
  mergeSelectedFiles,
  newUploadRow,
  overallIndexProgress,
  overallUploadProgress,
  rowsFromJobFiles,
  uploadErrorMessage,
  uploadSummary,
} from "./uploadQueue";

describe("uploadQueue", () => {
  it("suma archivos sin duplicar por nombre y tamaño", () => {
    const original = new File(["a"], "a.txt");
    const sameFile = new File(["a"], "a.txt");
    const otherSize = new File(["bb"], "a.txt");
    expect(mergeSelectedFiles([original], [sameFile, otherSize])).toEqual([
      original,
      otherSize,
    ]);
  });

  it("detecta archivos sobre 25 MB", () => {
    expect(isOversized(new File(["a"], "a.txt"))).toBe(false);
    expect(
      isOversized({ name: "enorme.pdf", size: MAX_UPLOAD_BYTES + 1 } as File),
    ).toBe(true);
  });

  it("traduce el 413 en un mensaje accionable", () => {
    const err = new ApiError("File too large (max 25 MB)", 413, "too_large", null);
    expect(uploadErrorMessage(err)).toContain("25 MB");
    expect(uploadErrorMessage(new Error("boom"))).toBe("boom");
  });
});

describe("cola de subida", () => {
  const big = new File(["a".repeat(2000)], "grande.pdf");
  const small = new File(["b".repeat(2000)], "chico.pdf");

  it("calcula el progreso global por bytes enviados", () => {
    const uploading = { ...newUploadRow(big, "uploading"), progress: 50 };
    expect(overallUploadProgress([uploading, newUploadRow(small)])).toBe(25);
    expect(overallUploadProgress([{ ...newUploadRow(big, "indexing") }, newUploadRow(small)])).toBe(50);
    expect(overallUploadProgress([{ ...newUploadRow(big, "indexed") }, { ...newUploadRow(small, "indexed") }])).toBe(100);
  });

  it("resume cuántos van subidos, indexando y con error", () => {
    const summary = uploadSummary([
      { ...newUploadRow(big, "indexed"), progress: 100 },
      { ...newUploadRow(small, "indexing"), progress: 50 },
      { ...newUploadRow(new File(["c"], "falla.pdf"), "error"), error: "boom" },
      newUploadRow(new File(["d"], "cola.pdf")),
    ]);
    expect(summary.total).toBe(4);
    expect(summary.uploaded).toBe(3);
    expect(summary.pending).toBe(1);
    expect(summary.indexing).toBe(1);
    expect(summary.indexed).toBe(1);
    expect(summary.failed).toBe(1);
  });

  it("mapea el estado del job de indexado a la fila", () => {
    expect(jobRowStatus("pending")).toBe("created");
    expect(jobRowStatus("running", 50)).toBe("indexing");
    expect(jobRowStatus("completed", 100)).toBe("indexed");
    expect(jobRowStatus("failed")).toBe("failed");
  });

  it("arma filas de solo lectura desde el progreso por archivo", () => {
    const rows = rowsFromJobFiles([
      { filename: "a.pdf", job_id: "j1", job_status: "running", job_progress: 50 },
      { filename: "b.csv", job_id: "j2", job_status: "completed", job_progress: 100 },
    ]);
    expect(rows.map((row) => row.status)).toEqual(["indexing", "indexed"]);
    expect(rows.map((row) => row.size)).toEqual([0, 0]);
    expect(overallIndexProgress(rows)).toBe(75);
  });

  it("usa el id de fila por nombre y tamaño", () => {
    expect(fileRowId(new File(["a"], "x.pdf"))).toBe("x.pdf:1");
  });
});
