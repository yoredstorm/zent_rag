import { Input, Textarea } from "../ui";
import { AgentField } from "./AgentField";

export function AgentPurposeForm({
  name,
  purpose,
  instructions,
  nameError,
  onName,
  onPurpose,
  onInstructions,
}: {
  name: string;
  purpose: string;
  instructions: string;
  /** Error de validación del nombre (solo tras tocarlo). */
  nameError?: string;
  onName: (value: string) => void;
  onPurpose: (value: string) => void;
  onInstructions: (value: string) => void;
}) {
  return (
    <section className="grid gap-4">
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
        hint="¿Qué debe lograr este agente?"
      >
        <Textarea
          id="agent-studio-purpose"
          className="min-h-24"
          value={purpose}
          onChange={(e) => onPurpose(e.target.value)}
          placeholder="Responder dudas de RRHH con las políticas internas"
        />
      </AgentField>

      <AgentField
        id="agent-studio-instructions"
        label="Instrucciones libres"
        hint="Texto libre para casos puntuales; el estilo general se define en «Cómo debe responder»."
      >
        <Textarea
          id="agent-studio-instructions"
          className="min-h-32"
          value={instructions}
          onChange={(e) => onInstructions(e.target.value)}
          placeholder="Sé claro, cita las políticas y no inventes datos."
        />
      </AgentField>
    </section>
  );
}
