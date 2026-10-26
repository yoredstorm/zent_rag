// =============================================================================
// AgentStyleComparator — A/B de estilos con la misma pregunta y evidencia.
// =============================================================================
// Simulado por diseño: no ejecuta herramientas reales, no persiste el perfil y
// no cambia el agente hasta que el usuario elige "Usar este estilo" (que sólo
// actualiza el borrador; guardar sigue siendo una acción explícita aparte).
import { Scales } from "@phosphor-icons/react";
import { useState } from "react";
import { api } from "../../api";
import { Badge, Button } from "../ui";
import { AgentSection } from "./AgentField";
import { applyPresetToProfile } from "./agentModes";
import type { ResponseProfile, ResponseProfilePreset } from "./types";

type CompareResult = {
  profile_id: string;
  profile: ResponseProfile | null;
  answer: string;
  error: string;
  chars: number;
  sections: string[];
  formatting: Record<string, boolean>;
  evidence: Record<string, boolean>;
  response_contract: Record<string, unknown> | null;
  validation: {
    contract_present: boolean;
    style_degraded: boolean;
    style_degradation_reason?: string;
  };
};

type CompareResponse = {
  results: CompareResult[];
  simulated_evidence: boolean;
  tools_executed: boolean;
  same_evidence: boolean;
};

export function AgentStyleComparator({
  presets,
  profile,
  agentId,
  token,
  organizationId,
  question,
  onUseProfile,
}: {
  presets: ResponseProfilePreset[];
  profile: ResponseProfile;
  agentId?: string;
  token?: string;
  organizationId?: string;
  question: string;
  onUseProfile: (next: ResponseProfile) => void;
}) {
  const [selected, setSelected] = useState<string[]>(["precise", "concise"]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [data, setData] = useState<CompareResponse | null>(null);

  function toggle(profileId: string) {
    setSelected((prev) => {
      if (prev.includes(profileId)) {
        return prev.filter((item) => item !== profileId);
      }
      if (prev.length >= 4) return prev;
      return [...prev, profileId];
    });
  }

  async function compare() {
    if (!agentId) {
      setError("Guardá el agente primero para comparar estilos reales.");
      return;
    }
    if (selected.length < 2) {
      setError("Elegí al menos dos estilos.");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    setData(null);
    try {
      const result = await api<CompareResponse>(
        `/api/v1/agents/${agentId}/config/compare`,
        {
          method: "POST",
          token,
          organizationId,
          body: JSON.stringify({
            question: question.trim() || "¿Qué decisión conviene y por qué?",
            profile_ids: selected,
          }),
        },
      );
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo comparar estilos");
    } finally {
      setBusy(false);
    }
  }

  function applyStyle(result: CompareResult) {
    const preset = presets.find((item) => item.id === result.profile_id);
    if (!preset) return;
    onUseProfile(applyPresetToProfile(preset));
    setNotice(
      `Estilo ${preset.label} aplicado al borrador. No se guardó: revisá y guardá el agente.`,
    );
  }

  return (
    <AgentSection
      title="Comparar estilos"
      hint="Misma pregunta, mismo modelo y misma evidencia simulada. No ejecuta herramientas ni guarda el perfil."
      actions={
        <Button
          variant="secondary"
          size="sm"
          leadingIcon={Scales}
          loading={busy}
          onClick={() => void compare()}
        >
          Comparar
        </Button>
      }
    >
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Estilos a comparar">
        {presets.map((preset) => {
          const active = selected.includes(preset.id);
          return (
            <button
              key={preset.id}
              type="button"
              aria-pressed={active}
              className={`rounded-full border px-2.5 py-1 text-[11.5px] transition-colors ${
                active
                  ? "border-accent bg-accent/10 text-accent"
                  : "border-border bg-surface text-muted hover:text-text"
              }`}
              onClick={() => toggle(preset.id)}
              title={preset.hint}
            >
              {preset.label}
            </button>
          );
        })}
      </div>
      <p className="text-[11.5px] text-faint">
        Perfil actual: {profile.profile_id}. Se comparan entre {selected.length} y 4 estilos.
      </p>
      {error ? (
        <p className="text-xs text-danger" role="alert">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="text-xs text-ok" role="status">
          {notice}
        </p>
      ) : null}
      {data ? (
        <div className="grid gap-2 md:grid-cols-2">
          <p className="text-[11px] text-faint md:col-span-2">
            Evidencia simulada, misma para todas las variantes. Herramientas ejecutadas: no.
          </p>
          {data.results.map((result) => {
            const preset = presets.find((item) => item.id === result.profile_id);
            return (
              <article
                key={result.profile_id}
                className="rounded-md border border-border bg-surface/60 p-3"
              >
                <div className="mb-2 flex flex-wrap items-center gap-1.5">
                  <Badge tone="accent">{preset?.label ?? result.profile_id}</Badge>
                  <Badge tone="neutral">
                    {String(result.response_contract?.communication_strategy ?? "sin estrategia")}
                  </Badge>
                  <Badge tone="neutral">{result.chars} chars</Badge>
                  <Badge tone={result.validation.style_degraded ? "danger" : "ok"}>
                    {result.validation.style_degraded ? "Parcial" : "Validado"}
                  </Badge>
                </div>
                {result.error ? (
                  <p className="text-xs text-danger">{result.error}</p>
                ) : (
                  <p className="whitespace-pre-wrap text-[12.5px] text-text">{result.answer}</p>
                )}
                <div className="mt-2 flex flex-wrap gap-1.5 text-[10.5px] text-faint">
                  <span>detalle: {String(result.response_contract?.detail ?? "?")}</span>
                  <span>secciones: {result.sections.length}</span>
                  <span>{result.evidence.citations_required ? "citas obligatorias" : "sin citas"}</span>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="mt-2"
                  onClick={() => applyStyle(result)}
                >
                  Usar este estilo
                </Button>
              </article>
            );
          })}
        </div>
      ) : null}
    </AgentSection>
  );
}

export default AgentStyleComparator;
