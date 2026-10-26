import { Sparkle, User } from "@phosphor-icons/react";
import { useRef, useState } from "react";
import { api } from "../../api";
import { Badge, Button, IconButton, Input, Select, Textarea } from "../ui";
import { AgentCollapsible, AgentField, AgentSection } from "./AgentField";
import { describeWarnings } from "./purposeWarnings";
import type { ResponseProfile } from "./types";

/** Resumen de una línea para el disclosure de instrucciones libres. */
function instructionsSummary(value: string): string {
  const firstLine = value.trim().split("\n")[0]?.trim() ?? "";
  if (!firstLine) return "Sin instrucciones extra";
  return firstLine.length > 56 ? `${firstLine.slice(0, 56)}…` : firstLine;
}

type PurposeMode = "auto" | "expand" | "improve" | "create";
type InstructionsChoice = "keep" | "combine" | "replace";

type PurposeQuality = {
  passed?: boolean;
  score?: number;
  criteria?: Record<string, boolean>;
  issues?: string[];
  generic_phrases?: string[];
  unnecessary_tools?: string[];
};

type PurposeProposal = {
  purpose: string;
  additional_instructions: string;
  intent_summary: string;
  persona: {
    role?: string;
    audience?: string;
    voice?: string;
    communication_principles?: string[];
  };
  behavioral_objectives: string[];
  knowledge_boundaries: string[];
  warnings: string[];
  source: string;
  generation_source: string;
  mode: string;
  quality?: PurposeQuality;
  saved: boolean;
};

function combineInstructions(current: string, suggested: string): string {
  const lines: string[] = [];
  const seen = new Set<string>();
  for (const raw of [current, suggested]) {
    for (const line of raw.split("\n")) {
      const clean = line.trim();
      if (!clean) continue;
      const key = clean.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      lines.push(line.startsWith("- ") || line.startsWith("* ") ? line : `- ${clean}`);
    }
  }
  return lines.join("\n");
}

export function AgentPurposeForm({
  name,
  purpose,
  instructions,
  profile,
  sourceTitles = [],
  tools = [],
  nameError,
  onName,
  onPurpose,
  onInstructions,
  agentId,
  token,
  organizationId,
}: {
  name: string;
  purpose: string;
  instructions: string;
  profile?: ResponseProfile;
  sourceTitles?: string[];
  tools?: string[];
  /** Error de validación del nombre (solo tras tocarlo). */
  nameError?: string;
  onName: (value: string) => void;
  onPurpose: (value: string) => void;
  onInstructions: (value: string) => void;
  /** Sin agente guardado no hay generación: se avisa, no se simula. */
  agentId?: string;
  token?: string;
  organizationId?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ text: string; tone: "ok" | "warn" } | null>(null);
  const [error, setError] = useState("");
  const [instructionsOpen, setInstructionsOpen] = useState(false);
  const [mode, setMode] = useState<PurposeMode>("auto");
  const [proposal, setProposal] = useState<PurposeProposal | null>(null);
  const [proposalPurpose, setProposalPurpose] = useState("");
  const [proposalInstructions, setProposalInstructions] = useState("");
  const [originalSnapshot, setOriginalSnapshot] = useState("");
  const [instructionsChoice, setInstructionsChoice] =
    useState<InstructionsChoice>("combine");
  const requestRef = useRef(0);

  async function generatePurpose() {
    if (!agentId) {
      setNotice(null);
      setError("Guardá el agente primero: el generador sólo usa datos reales del agente.");
      return;
    }
    const requestId = requestRef.current + 1;
    requestRef.current = requestId;
    const purposeSnapshot = purpose;
    const instructionsSnapshot = instructions;
    setBusy(true);
    setError("");
    setNotice(null);
    setOriginalSnapshot(purposeSnapshot || "(sin propósito todavía)");
    try {
      const data = await api<{
        draft: string;
        purpose?: string;
        additional_instructions?: string;
        intent_summary?: string;
        persona?: PurposeProposal["persona"];
        behavioral_objectives?: string[];
        knowledge_boundaries?: string[];
        warnings?: string[];
        source?: string;
        generation_source?: string;
        mode?: string;
        quality?: PurposeQuality;
        saved?: boolean;
      }>(`/api/v1/agents/${agentId}/config/purpose`, {
        method: "POST",
        token,
        organizationId,
        body: JSON.stringify({
          purpose: purposeSnapshot,
          instructions: instructionsSnapshot,
          name,
          mode,
          profile,
          tools,
        }),
      });
      if (requestRef.current !== requestId) return;
      const next: PurposeProposal = {
        purpose: data.purpose ?? data.draft ?? "",
        additional_instructions: data.additional_instructions ?? "",
        intent_summary: data.intent_summary ?? "",
        persona: data.persona ?? {},
        behavioral_objectives: data.behavioral_objectives ?? [],
        knowledge_boundaries: data.knowledge_boundaries ?? [],
        warnings: data.warnings ?? [],
        source: data.source ?? "model",
        generation_source: data.generation_source ?? "model",
        mode: data.mode ?? mode,
        quality: data.quality,
        saved: false,
      };
      setProposal(next);
      setProposalPurpose(next.purpose);
      setProposalInstructions(next.additional_instructions);
      setInstructionsChoice(instructionsSnapshot.trim() ? "combine" : "replace");
      const warningsText = describeWarnings(next.warnings);
      const qualityFailed = next.quality?.passed === false;
      setNotice({
        text: [
          qualityFailed
            ? `La propuesta no superó todos los chequeos. ${warningsText || "Revisala antes de aplicar."}`
            : "Propuesta lista para revisar. No se guardó nada.",
          "Aplicá propósito o propósito e instrucciones cuando estés conforme.",
        ].join(" "),
        tone: qualityFailed || next.source === "rules" ? "warn" : "ok",
      });
    } catch (err) {
      if (requestRef.current !== requestId) return;
      setError(err instanceof Error ? err.message : "No se pudo generar el propósito");
    } finally {
      if (requestRef.current === requestId) setBusy(false);
    }
  }

  function chosenInstructions(): string {
    if (!proposal) return "";
    if (!instructions.trim()) return proposalInstructions;
    if (instructionsChoice === "keep") return instructions;
    if (instructionsChoice === "replace") return proposalInstructions;
    return combineInstructions(instructions, proposalInstructions);
  }

  function applyPurposeOnly() {
    if (!proposal) return;
    onPurpose(proposalPurpose.trim());
    setNotice({ text: "Propósito aplicado al borrador. Guardá para conservarlo.", tone: "ok" });
    setProposal(null);
  }

  function applyPurposeAndInstructions() {
    if (!proposal) return;
    onPurpose(proposalPurpose.trim());
    onInstructions(chosenInstructions());
    setNotice({
      text: "Propósito e instrucciones aplicados al borrador. Guardá para conservarlos.",
      tone: "ok",
    });
    setProposal(null);
  }

  function cancelProposal() {
    setProposal(null);
    setNotice(null);
    setError("");
  }

  return (
    <div className="grid gap-6">
      <AgentSection title="Identidad" icon={User} hint="Cómo se llama y qué debe lograr.">
        <AgentField
          id="agent-studio-name"
          label="Nombre"
          hint="Así lo verás en la lista y en las publicaciones."
          error={nameError}
          required
        >
          <Input
            id="agent-studio-name"
            value={name}
            onChange={(e) => onName(e.target.value)}
            autoComplete="off"
            placeholder="Soporte interno"
          />
        </AgentField>

        <AgentField
          id="agent-studio-purpose"
          label="Propósito"
          hint={
            "¿Qué debe lograr? Es lo que guía sus decisiones y su forma de responder." +
            (sourceTitles.length ? ` Fuentes: ${sourceTitles.slice(0, 3).join(", ")}.` : "")
          }
          labelAction={
            <div className="flex items-center gap-1.5">
              <Select
                aria-label="Modo de generación"
                className="h-8 w-auto text-[11.5px]"
                value={mode}
                onChange={(e) => setMode(e.target.value as PurposeMode)}
              >
                <option value="auto">Auto</option>
                <option value="expand">Expandir</option>
                <option value="improve">Mejorar</option>
                <option value="create">Crear</option>
              </Select>
              <IconButton
                label="Generar propósito con IA"
                icon={Sparkle}
                iconSize={15}
                loading={busy}
                onClick={() => void generatePurpose()}
              />
            </div>
          }
        >
          <Textarea
            id="agent-studio-purpose"
            className="min-h-20"
            value={purpose}
            onChange={(e) => onPurpose(e.target.value)}
            placeholder="Responder dudas de RRHH con las políticas internas"
          />
        </AgentField>

        {notice ? (
          <p
            className={notice.tone === "warn" ? "text-xs text-warn" : "text-xs text-ok"}
            role="status"
          >
            {notice.text}
          </p>
        ) : null}
        {error ? (
          <p className="text-xs text-danger" role="alert">
            {error}
          </p>
        ) : null}
      </AgentSection>

      {proposal ? (
        <AgentSection
          title="Propuesta de propósito"
          hint="Revisá y editá antes de aplicar. Nada se guarda hasta que guardes el agente."
          className="min-w-0"
        >
          <div className="grid min-w-0 gap-4" data-testid="purpose-proposal">
            <div className="min-w-0">
              <p className="text-[11px] font-medium uppercase tracking-wide text-faint">
                Tu objetivo original
              </p>
              <p className="mt-1 break-words whitespace-pre-wrap text-xs text-muted">
                {originalSnapshot}
              </p>
            </div>

            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
              {proposal.quality ? (
                <Badge tone={proposal.quality.passed ? "ok" : "warn"}>
                  {proposal.quality.passed ? "Chequeos superados" : "Revisar propuesta"}
                </Badge>
              ) : null}
              <Badge tone="neutral">
                {proposal.source === "rules" ? "Entrada preservada" : "Generado con IA"}
              </Badge>
              <Badge tone="neutral">Modo: {proposal.mode}</Badge>
            </div>

            {proposal.intent_summary ? (
              <p className="min-w-0 break-words text-[11.5px] leading-relaxed text-muted">
                <span className="font-medium text-faint">Intención detectada: </span>
                {proposal.intent_summary}
              </p>
            ) : null}

            <AgentField
              id="purpose-proposal-purpose"
              label="Propósito propuesto"
              className="min-w-0"
            >
              <Textarea
                id="purpose-proposal-purpose"
                className="min-h-28 min-w-0"
                value={proposalPurpose}
                onChange={(e) => setProposalPurpose(e.target.value)}
              />
            </AgentField>

            <AgentField
              id="purpose-proposal-instructions"
              label="Instrucciones adicionales sugeridas"
              hint="Se aplican al campo de instrucciones; no reemplazan nada sin tu elección."
              className="min-w-0"
            >
              <Textarea
                id="purpose-proposal-instructions"
                className="min-h-32 min-w-0"
                value={proposalInstructions}
                onChange={(e) => setProposalInstructions(e.target.value)}
              />
            </AgentField>

            {instructions.trim() ? (
              <div className="grid min-w-0 gap-2 rounded-md border border-border bg-surface/60 p-3">
                <p className="text-xs font-medium text-text">Ya tenés instrucciones</p>
                <p className="break-words whitespace-pre-wrap text-[11.5px] text-faint">
                  {instructions}
                </p>
                <div className="flex flex-wrap gap-1.5" role="group" aria-label="Cómo aplicar instrucciones">
                  {(
                    [
                      ["keep", "Conservar las actuales"],
                      ["combine", "Combinar sin duplicar"],
                      ["replace", "Reemplazar por las sugeridas"],
                    ] as const
                  ).map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      aria-pressed={instructionsChoice === value}
                      className={`rounded-full border px-2.5 py-1 text-[11.5px] ${
                        instructionsChoice === value
                          ? "border-accent bg-accent/10 text-accent"
                          : "border-border bg-surface text-muted"
                      }`}
                      onClick={() => setInstructionsChoice(value)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            {proposal.persona.role || proposal.persona.voice || proposal.persona.audience ? (
              <p className="min-w-0 break-words text-[11.5px] text-faint">
                Identidad: {proposal.persona.role || "sin rol"} ·{" "}
                {proposal.persona.audience || "audiencia no declarada"} ·{" "}
                {proposal.persona.voice || "voz no declarada"}
              </p>
            ) : null}
            {proposal.warnings.length ? (
              <p className="min-w-0 break-words text-[11.5px] text-warn">
                {describeWarnings(proposal.warnings) || proposal.warnings.join(" · ")}
              </p>
            ) : null}

            <div className="flex min-w-0 flex-wrap gap-2">
              <Button variant="primary" size="sm" onClick={applyPurposeOnly}>
                Aplicar propósito
              </Button>
              <Button variant="secondary" size="sm" onClick={applyPurposeAndInstructions}>
                Aplicar propósito e instrucciones
              </Button>
              <Button
                variant="ghost"
                size="sm"
                loading={busy}
                onClick={() => void generatePurpose()}
              >
                Regenerar propuesta
              </Button>
              <Button variant="ghost" size="sm" onClick={cancelProposal}>
                Cancelar
              </Button>
            </div>
          </div>
        </AgentSection>
      ) : null}

      <AgentCollapsible
        id="agent-studio-instructions-panel"
        title="Instrucciones adicionales"
        summary={instructionsSummary(instructions)}
        open={instructionsOpen}
        onToggle={setInstructionsOpen}
      >
        <AgentField
          id="agent-studio-instructions"
          label="Texto libre"
          hint="Para casos puntuales. El estilo general se define en Comportamiento."
        >
          <Textarea
            id="agent-studio-instructions"
            className="min-h-32"
            value={instructions}
            onChange={(e) => onInstructions(e.target.value)}
            placeholder="Sé claro, cita las políticas y no inventes datos."
          />
        </AgentField>
      </AgentCollapsible>
    </div>
  );
}
