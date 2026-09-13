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
    const ring = screen.getByTestId("analyze-ring");
    expect(ring).toHaveAttribute("role", "progressbar");
    expect(ring).toHaveTextContent("%");
    expect(screen.getByTestId("analyze-live")).toBeInTheDocument();
    const button = screen.getByTestId("analyze-continue");
    expect(button).toBeDisabled();
    await user.click(button);
    expect(onContinue).not.toHaveBeenCalled();
  });

  it("Analizar muestra nube de glimpses y anillo con percent", () => {
    render(
      <AnalysisProgressStep
        headline="Zent está leyendo tu documento"
        phases={[{ id: "content", label: "Texto extraído", state: "done" }]}
        showTech={false}
        onToggleTech={() => {}}
        onContinue={() => {}}
        ready={false}
        percent={42}
        glimpses={[
          { id: "g1", text: "Ah, Empresa es AIR FRANCE" },
          { id: "g2", text: "Vi un monto: 29733" },
        ]}
      />
    );
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "42");
    expect(screen.getByTestId("analyze-ring")).toHaveTextContent("42%");
    expect(screen.getByTestId("analyze-cloud")).toHaveTextContent("Ah, Empresa es AIR FRANCE");
    expect(screen.getByTestId("analyze-live")).toHaveTextContent("Vi un monto: 29733");
    expect(screen.getByTestId("analyze-continue")).toBeDisabled();
  });

  it("Analizar listo muestra 100% y copy de continuar", () => {
    render(
      <AnalysisProgressStep
        headline="Zent está leyendo tu documento"
        phases={[{ id: "content", label: "Texto extraído", state: "done" }]}
        showTech={false}
        onToggleTech={() => {}}
        onContinue={() => {}}
        ready
        percent={90}
        glimpses={[{ id: "g1", text: "Ah, Empresa es AIR FRANCE" }]}
      />
    );
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
    expect(screen.getByTestId("analyze-live")).toHaveTextContent(
      "Ya entendí lo suficiente. Revisa cuando quieras."
    );
    expect(screen.getByTestId("analyze-continue")).toBeEnabled();
  });

  it("Analizar reduced-motion no rompe la nube", () => {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: query.includes("prefers-reduced-motion"),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
    render(
      <AnalysisProgressStep
        headline="Zent está leyendo tu documento"
        phases={[{ id: "content", label: "Texto extraído", state: "active" }]}
        showTech={false}
        onToggleTech={() => {}}
        onContinue={() => {}}
        ready={false}
        glimpses={[{ id: "g1", text: "Columna precio…" }]}
      />
    );
    expect(screen.getByTestId("analyze-cloud")).toHaveTextContent("Columna precio…");
    expect(screen.getByRole("progressbar")).toBeInTheDocument();
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
          onAcceptAll={() => {}}
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

  it("Revisar muestra ficha de highlights, no una card por hecho, y Se ve bien", async () => {
    const user = userEvent.setup();
    const onAcceptAll = vi.fn();
    const suggestions = [
      {
        id: "c1",
        type: "document_fact",
        title: "Jurisdicción",
        description: "Perú",
        confidence: "medium",
        evidence: ["leyes"],
        payload: { fact_type: "clause", key: "Jurisdicción", value: "Perú" },
      },
      {
        id: "c2",
        type: "document_fact",
        title: "Responsabilidad",
        description: "Sanciones",
        confidence: "medium",
        evidence: [],
        payload: { fact_type: "clause", key: "Responsabilidad", value: "Sanciones" },
      },
      {
        id: "p1",
        type: "document_fact",
        title: "Empresa",
        description: "AIR FRANCE",
        confidence: "high",
        evidence: [],
        payload: { fact_type: "party", key: "Empresa", value: "AIR FRANCE" },
      },
      {
        id: "a1",
        type: "document_fact",
        title: "Monto",
        description: "29733",
        confidence: "high",
        evidence: [],
        payload: { fact_type: "amount", key: "Monto", value: "29733" },
      },
      {
        id: "c3",
        type: "document_fact",
        title: "Objeto",
        description: "NDA",
        confidence: "medium",
        evidence: [],
        payload: { fact_type: "clause", key: "Objeto", value: "NDA" },
      },
      {
        id: "c4",
        type: "document_fact",
        title: "Excepciones",
        description: "Dominio público",
        confidence: "medium",
        evidence: [],
        payload: { fact_type: "clause", key: "Excepciones", value: "Dominio público" },
      },
      {
        id: "id1",
        type: "document_fact",
        title: "RUC Empresa",
        description: "2053592914",
        confidence: "high",
        evidence: [],
        payload: { fact_type: "identifier", key: "RUC Empresa", value: "2053592914" },
      },
    ];
    render(
      <MemoryRouter>
        <UnderstandingReviewStep
          understanding={{ flow: "documents", document_type: "Contract", pages: 3 }}
          suggestions={suggestions}
          onReview={() => {}}
          onFreeText={() => {}}
          onSkip={() => {}}
          onAcceptAll={onAcceptAll}
          busy=""
        />
      </MemoryRouter>
    );
    expect(screen.getByText("AIR FRANCE")).toBeInTheDocument();
    expect(screen.getByText("2053592914")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirmar" })).not.toBeInTheDocument();
    expect(screen.getByTestId("goto-questions")).toHaveTextContent("Se ve bien");
    expect(screen.getByRole("button", { name: /2 datos más/ })).toBeInTheDocument();
    await user.click(screen.getByTestId("goto-questions"));
    expect(onAcceptAll).toHaveBeenCalledTimes(1);
  });

  it("Revisar abre Corregir e Ignorar solo al expandir un highlight", async () => {
    const user = userEvent.setup();
    const onReview = vi.fn();
    render(
      <MemoryRouter>
        <UnderstandingReviewStep
          understanding={{ flow: "documents" }}
          suggestions={[
            {
              id: "p1",
              type: "document_fact",
              title: "Empresa",
              description: "Acme",
              confidence: "high",
              evidence: ["entre Acme"],
              payload: { fact_type: "party", key: "Empresa", value: "Acme" },
            },
          ]}
          onReview={onReview}
          onFreeText={() => {}}
          onSkip={() => {}}
          onAcceptAll={() => {}}
          busy=""
        />
      </MemoryRouter>
    );
    expect(screen.queryByRole("button", { name: "Ignorar" })).not.toBeInTheDocument();
    await user.click(screen.getByTestId("digest-row-p1"));
    expect(screen.getByRole("button", { name: "Corregir" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ignorar" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Ignorar" }));
    expect(onReview).toHaveBeenCalledWith("p1", "ignore");
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

  it("Probar muestra loading en el chip y acepta pregunta libre", async () => {
    const user = userEvent.setup();
    const onAsk = vi.fn();
    render(
      <MemoryRouter>
        <QuestionValidationStep
          questions={[{ id: "q1", text: "¿Quiénes son las partes?" }]}
          answer={null}
          onAsk={onAsk}
          onFeedback={() => {}}
          onSkip={() => {}}
          busy
          heading="Prueba el documento"
        />
      </MemoryRouter>
    );
    expect(screen.getByText("Zent está buscando…")).toBeInTheDocument();
    const chip = screen.getByTestId("generated-question");
    expect(chip).toBeDisabled();
    await user.type(screen.getByTestId("custom-question"), "¿Cuál es el monto?");
    await user.click(screen.getByRole("button", { name: "Enviar" }));
    expect(onAsk).not.toHaveBeenCalled();
  });

  it("Probar envía pregunta libre cuando no está busy", async () => {
    const user = userEvent.setup();
    const onAsk = vi.fn();
    render(
      <MemoryRouter>
        <QuestionValidationStep
          questions={[{ id: "q1", text: "¿Quiénes son las partes?" }]}
          answer={null}
          onAsk={onAsk}
          onFeedback={() => {}}
          onSkip={() => {}}
          busy={false}
        />
      </MemoryRouter>
    );
    await user.type(screen.getByTestId("custom-question"), "¿Cuál es el monto?");
    await user.click(screen.getByRole("button", { name: "Enviar" }));
    expect(onAsk).toHaveBeenCalledWith("¿Cuál es el monto?");
  });

  it("Probar muestra indexando con Reintentar y error inline", async () => {
    const user = userEvent.setup();
    const onAsk = vi.fn();
    render(
      <MemoryRouter>
        <QuestionValidationStep
          questions={[{ id: "q1", text: "¿Quiénes son las partes?" }]}
          answer={{
            question: "¿Quiénes son las partes?",
            answer: "Zent aún está indexando esta fuente.",
            understood: false,
          }}
          onAsk={onAsk}
          onFeedback={() => {}}
          onSkip={() => {}}
          busy={false}
          askError="Missing required permission: rag:read"
        />
      </MemoryRouter>
    );
    expect(screen.queryByText("Pregunta entendida")).not.toBeInTheDocument();
    expect(screen.getByText("Pendiente de indexar")).toBeInTheDocument();
    expect(screen.getByText("Missing required permission: rag:read")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(onAsk).toHaveBeenCalledWith("¿Quiénes son las partes?");
  });

  it("Probar muestra evidencia legible, no [object Object]", () => {
    render(
      <MemoryRouter>
        <QuestionValidationStep
          questions={[]}
          answer={{
            question: "¿Quiénes son las partes?",
            answer: "AIR FRANCE y PIMENTEL",
            understood: true,
            confidence: "high",
            evidence: [
              {
                type: "document_chunk",
                source_name: "NDA AIR FRANCE.pdf",
                snippet: "LA EMPRESA: AIR FRANCE PROCESSING CENTER S.A.C.",
              },
            ],
          }}
          onAsk={() => {}}
          onFeedback={() => {}}
          onSkip={() => {}}
          busy={false}
        />
      </MemoryRouter>
    );
    const evidence = screen.getByTestId("ask-evidence");
    expect(evidence).toHaveTextContent("NDA AIR FRANCE.pdf");
    expect(evidence).toHaveTextContent("AIR FRANCE PROCESSING CENTER");
    expect(evidence).not.toHaveTextContent("[object Object]");
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
