import { Sparkle } from "@phosphor-icons/react";
import { useState } from "react";
import { api } from "../../api";
import { IconButton, Input, Textarea } from "../ui";
import { AgentCollapsible, AgentField, AgentSection } from "./AgentField";

/** Resumen de una línea para el disclosure de instrucciones libres. */
function instructionsSummary(value: string): string {
  const firstLine = value.trim().split("\n")[0]?.trim() ?? "";
  if (!firstLine) return "Sin instrucciones extra";
  return firstLine.length > 56 ? `${firstLine.slice(0, 56)}…` : firstLine;
}

export function AgentPurposeForm({
  name,
  purpose,
  instructions,
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
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [instructionsOpen, setInstructionsOpen] = useState(false);

  async function generatePurpose() {
    if (!agentId) {
      setNotice("");
      setError("Guardá el agente primero: el generador sólo usa datos reales del agente.");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const data = await api<{ draft: string; warnings: string[] }>(
        `/api/v1/agents/${agentId}/config/purpose`,
        { method: "POST", token, organizationId, body: JSON.stringify({}) },
      );
      onPurpose(data.draft);
      setNotice("Borrador generado. Revisalo y guardá cuando estés conforme.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo generar el propósito");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-6">
      <AgentSection title="Identidad" hint="Cómo se llama y qué debe lograr.">
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
          hint="¿Qué debe lograr? Es lo que guía sus decisiones y su forma de responder."
          labelAction={
            <IconButton
              label="Generar propósito con IA"
              icon={Sparkle}
              iconSize={15}
              loading={busy}
              onClick={() => void generatePurpose()}
            />
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
          <p className="text-xs text-ok" role="status">
            {notice}
          </p>
        ) : null}
        {error ? (
          <p className="text-xs text-danger" role="alert">
            {error}
          </p>
        ) : null}
      </AgentSection>

      <AgentCollapsible
        id="agent-studio-instructions-panel"
        title="Instrucciones libres"
        summary={instructionsSummary(instructions)}
        open={instructionsOpen}
        onToggle={setInstructionsOpen}
      >
        <AgentField
          id="agent-studio-instructions"
          label="Texto libre"
          hint="Para casos puntuales. El estilo general se define en «Cómo debe responder»."
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
