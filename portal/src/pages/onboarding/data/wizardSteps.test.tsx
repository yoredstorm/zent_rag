import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AnalysisProgressStep } from "./AnalysisProgressStep";
import { QuestionValidationStep } from "./QuestionValidationStep";
import { ReadinessStep } from "./ReadinessStep";
import { UnderstandingReviewStep } from "./UnderstandingReviewStep";
import { WIZARD_STEP_HEADINGS } from "./types";

describe("wizard UI steps 3–6", () => {
  it("Analizar usa heading estable y Continuar no avanza si el análisis no terminó", async () => {
    const onContinue = vi.fn();
    const user = userEvent.setup();
    render(
      <AnalysisProgressStep
        headline="Zent está leyendo tu documento"
        phases={[{ id: "content", label: "Texto extraído", state: "active" }]}
        showTech={false}
        onToggleTech={() => {}}
        onContinue={onContinue}
        ready={false}
      />
    );
    expect(screen.getByRole("heading", { name: WIZARD_STEP_HEADINGS.analyze })).toBeInTheDocument();
    const button = screen.getByTestId("analyze-continue");
    expect(button).toBeDisabled();
    await user.click(button);
    expect(onContinue).not.toHaveBeenCalled();
  });

  it("Revisar usa heading estable y enlaza a Semántica", () => {
    render(
      <MemoryRouter>
        <UnderstandingReviewStep
          understanding={{ likely_entity: "Producto" }}
          suggestions={[]}
          onReview={() => {}}
          onFreeText={() => {}}
          onSkip={() => {}}
          busy=""
        />
      </MemoryRouter>
    );
    expect(screen.getByRole("heading", { name: WIZARD_STEP_HEADINGS.review })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Abrir Semántica" })).toHaveAttribute(
      "href",
      "/knowledge/glossary"
    );
  });

  it("Probar usa heading estable y enlaza a Mejora", () => {
    render(
      <MemoryRouter>
        <QuestionValidationStep
          questions={[]}
          answer={null}
          onAsk={() => {}}
          onFeedback={() => {}}
          onSkip={() => {}}
          busy={false}
          heading="Prueba el documento"
        />
      </MemoryRouter>
    );
    expect(screen.getByRole("heading", { name: WIZARD_STEP_HEADINGS.test })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Abrir Mejora" })).toHaveAttribute(
      "href",
      "/knowledge/learning"
    );
  });

  it("Listo usa heading estable y aterriza en Semántica y Mejora", () => {
    render(
      <MemoryRouter>
        <ReadinessStep
          overall={80}
          scores={{ data_connected: 80 }}
          labels={{ data_connected: "Datos conectados" }}
          improvements={[]}
          warning={null}
          readyHeadline="Tu documento está listo."
        />
      </MemoryRouter>
    );
    expect(screen.getByTestId("ready-heading")).toHaveTextContent(WIZARD_STEP_HEADINGS.ready);
    expect(screen.getByRole("link", { name: "Abrir Semántica" })).toHaveAttribute(
      "href",
      "/knowledge/glossary"
    );
    expect(screen.getByRole("link", { name: "Abrir Mejora" })).toHaveAttribute(
      "href",
      "/knowledge/learning"
    );
  });
});
