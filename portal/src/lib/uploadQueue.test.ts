import { describe, expect, it } from "vitest";
import { ApiError } from "./errors";
import {
  MAX_UPLOAD_BYTES,
  isOversized,
  mergeSelectedFiles,
  uploadErrorMessage,
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
