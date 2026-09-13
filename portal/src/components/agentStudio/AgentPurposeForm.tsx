export function AgentPurposeForm({
  name,
  purpose,
  instructions,
  onName,
  onPurpose,
  onInstructions,
}: {
  name: string;
  purpose: string;
  instructions: string;
  onName: (value: string) => void;
  onPurpose: (value: string) => void;
  onInstructions: (value: string) => void;
}) {
  return (
    <section className="grid gap-4">
      <label className="block" htmlFor="agent-studio-name">
        <span className="mb-1 block text-sm font-medium text-text">Nombre</span>
        <input
          id="agent-studio-name"
          className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus-visible:ring-2 focus-visible:ring-accent"
          value={name}
          onChange={(e) => onName(e.target.value)}
          autoComplete="off"
        />
      </label>
      <div>
        <label className="mb-1 block text-sm font-medium text-text" htmlFor="agent-studio-purpose">
          Propósito
        </label>
        <p id="agent-studio-purpose-hint" className="mb-1.5 text-xs text-muted">
          ¿Qué debe lograr este agente?
        </p>
        <textarea
          id="agent-studio-purpose"
          className="min-h-24 w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus-visible:ring-2 focus-visible:ring-accent"
          value={purpose}
          onChange={(e) => onPurpose(e.target.value)}
          placeholder="Responder dudas de RRHH con las políticas internas"
          aria-describedby="agent-studio-purpose-hint"
        />
      </div>
      <div>
        <label className="mb-1 block text-sm font-medium text-text" htmlFor="agent-studio-instructions">
          Cómo debe responder
        </label>
        <p id="agent-studio-instructions-hint" className="mb-1.5 text-xs text-muted">
          Instrucciones de tono, límites y formato.
        </p>
        <textarea
          id="agent-studio-instructions"
          className="min-h-32 w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus-visible:ring-2 focus-visible:ring-accent"
          value={instructions}
          onChange={(e) => onInstructions(e.target.value)}
          placeholder="Sé claro, cita las políticas y no inventes datos."
          aria-describedby="agent-studio-instructions-hint"
        />
      </div>
    </section>
  );
}
