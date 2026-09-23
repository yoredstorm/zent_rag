// =============================================================================
// AgentResponseProfileSection — "Cómo debe responder" (§27-§36)
// =============================================================================
// Separa PROPÓSITO ("qué debe lograr") de PERFIL DE RESPUESTA ("cómo debe
// explicarlo"). El perfil es estructura: idioma, tono, nivel, detalle, formato,
// citas y qué hacer con la incertidumbre.
//
// El generador con IA propone ESTILO. Nunca hechos ni capacidades que el agente
// no tenga: eso vive en el conocimiento, no en el prompt.
import { useState } from "react";
import { api } from "../../api";
import { Badge, Button, Select, Textarea } from "../ui";
import { AgentField } from "./AgentField";
import {
  RESPONSE_PROFILE_PRESETS,
  RESPONSE_PROFILE_TOGGLES,
  type ResponseProfile,
} from "./types";

export function AgentResponseProfileSection({
  profile,
  onChange,
  agentId,
  token,
  organizationId,
  purpose,
  sourceTitles = [],
  onPurpose,
}: {
  profile: ResponseProfile;
  onChange: (next: ResponseProfile) => void;
  /** Sin agente guardado no hay generación con IA: se avisa, no se simula. */
  agentId?: string;
  token?: string;
  organizationId?: string;
  purpose?: string;
  sourceTitles?: string[];
  onPurpose?: (value: string) => void;
}) {
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [preview, setPreview] = useState("");
  const [previewQuestion, setPreviewQuestion] = useState("¿Qué significa el campo X cuando su valor es 2?");
  const [previewContract, setPreviewContract] = useState<Record<string, unknown> | null>(null);

  const activePreset = profile.preset ?? "";

  function applyPreset(preset: (typeof RESPONSE_PROFILE_PRESETS)[number]) {
    onChange({ ...profile, ...preset.profile, preset: preset.id });
  }

  function set<K extends keyof ResponseProfile>(key: K, value: ResponseProfile[K]) {
    onChange({ ...profile, [key]: value });
  }

  async function generate(what: "purpose" | "profile") {
    if (!agentId) {
      setNotice("");
      setError("Guardá el agente primero: el generador sólo usa datos reales del agente.");
      return;
    }
    setBusy(what);
    setError("");
    setNotice("");
    try {
      if (what === "purpose") {
        const data = await api<{ draft: string; warnings: string[]; saved: boolean }>(
          `/api/v1/agents/${agentId}/config/purpose`,
          {
            method: "POST",
            token,
            organizationId,
            body: JSON.stringify({}),
          },
        );
        onPurpose?.(data.draft);
        setNotice("Borrador de propósito generado. Revisalo y guardá cuando estés conforme.");
      } else {
        const data = await api<{ draft: Record<string, unknown>; saved: boolean }>(
          `/api/v1/agents/${agentId}/config/response-profile`,
          {
            method: "POST",
            token,
            organizationId,
            body: JSON.stringify({}),
          },
        );
        const draft = data.draft as Partial<ResponseProfile>;
        onChange({
          ...profile,
          ...draft,
          preset: typeof draft.preset === "string" ? draft.preset : profile.preset,
        });
        setNotice("Perfil propuesto. Ajustá lo que quieras antes de guardar.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo generar el borrador");
    } finally {
      setBusy("");
    }
  }

  async function runPreview() {
    if (!agentId) {
      setError("Guardá el agente primero para ver el preview real.");
      return;
    }
    setBusy("preview");
    setError("");
    setPreview("");
    setPreviewContract(null);
    try {
      const data = await api<{
        preview: string;
        response_contract: Record<string, unknown> | null;
        simulated_evidence: boolean;
      }>(`/api/v1/agents/${agentId}/config/preview`, {
        method: "POST",
        token,
        organizationId,
        body: JSON.stringify({ question: previewQuestion }),
      });
      setPreview(data.preview);
      setPreviewContract(data.response_contract);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo generar el preview");
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="grid gap-4" data-testid="agent-response-profile">
      <div>
        <p className="text-[13px] text-text">Cómo debe responder</p>
        <p className="text-[11.5px] text-faint">
          Cómo explicar la respuesta. No cambia qué puede concluir el agente: eso lo
          deciden la evidencia y el análisis.
        </p>
      </div>

      <div className="flex flex-wrap gap-2" role="group" aria-label="Presets de respuesta">
        {RESPONSE_PROFILE_PRESETS.map((preset) => (
          <button
            key={preset.id}
            type="button"
            onClick={() => applyPreset(preset)}
            aria-pressed={activePreset === preset.id}
            title={preset.hint}
            className={`rounded-sm border px-2.5 py-1 text-[12px] ${
              activePreset === preset.id
                ? "border-accent bg-surface-strong text-text"
                : "border-border text-muted hover:text-text"
            }`}
          >
            {preset.label}
          </button>
        ))}
        {activePreset && !RESPONSE_PROFILE_PRESETS.some((p) => p.id === activePreset) ? (
          <Badge tone="neutral">Personalizado</Badge>
        ) : null}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <AgentField id="response-detail" label="Nivel de detalle" hint="Cuánto explicar, no cuánto escribir.">
          <Select
            id="response-detail"
            value={profile.default_detail}
            onChange={(e) => set("default_detail", e.target.value as ResponseProfile["default_detail"])}
          >
            <option value="brief">Breve</option>
            <option value="normal">Normal</option>
            <option value="detailed">Detallado</option>
            <option value="deep">Profundo</option>
          </Select>
        </AgentField>
        <AgentField id="response-tone" label="Tono">
          <Select
            id="response-tone"
            value={profile.tone}
            onChange={(e) => set("tone", e.target.value as ResponseProfile["tone"])}
          >
            <option value="professional">Profesional</option>
            <option value="didactic">Didáctico</option>
            <option value="executive">Ejecutivo</option>
            <option value="neutral">Neutro</option>
          </Select>
        </AgentField>
        <AgentField id="response-level" label="Nivel técnico">
          <Select
            id="response-level"
            value={profile.technical_level}
            onChange={(e) =>
              set("technical_level", e.target.value as ResponseProfile["technical_level"])
            }
          >
            <option value="basic">Sin jerga</option>
            <option value="intermediate">Habitual</option>
            <option value="advanced">Técnico</option>
            <option value="expert">Experto</option>
          </Select>
        </AgentField>
        <AgentField id="response-audience" label="Audiencia" hint="Ajusta cuánto contexto explicar.">
          <Select
            id="response-audience"
            value={profile.audience}
            onChange={(e) => set("audience", e.target.value as ResponseProfile["audience"])}
          >
            <option value="beginner">Principiante</option>
            <option value="business">Negocio</option>
            <option value="technical">Técnica</option>
            <option value="expert">Experta</option>
          </Select>
        </AgentField>
      </div>

      <fieldset className="grid gap-2">
        <legend className="text-[12px] text-muted">Formato y evidencia</legend>
        <div className="flex flex-wrap gap-x-4 gap-y-2">
          {RESPONSE_PROFILE_TOGGLES.map((toggle) => (
            <label key={String(toggle.key)} className="flex items-center gap-2 text-[12px] text-text">
              <input
                type="checkbox"
                checked={Boolean(profile[toggle.key])}
                onChange={(e) => onChange({ ...profile, [toggle.key]: e.target.checked })}
                aria-label={toggle.label}
              />
              <span title={toggle.hint}>{toggle.label}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <AgentField
        id="response-instructions"
        label="Instrucciones de estilo"
        hint="Estilo, no conocimiento: los hechos viven en las fuentes."
      >
        <Textarea
          id="response-instructions"
          className="min-h-20"
          value={profile.custom_instructions ?? ""}
          onChange={(e) => set("custom_instructions", e.target.value)}
          placeholder="Responde primero la conclusión; conserva los términos técnicos; declara qué falta antes de especular."
        />
      </AgentField>

      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="secondary" onClick={() => void generate("profile")} disabled={busy !== ""}>
          {busy === "profile" ? "Generando…" : "Generar con IA"}
        </Button>
        {onPurpose ? (
          <Button type="button" variant="ghost" onClick={() => void generate("purpose")} disabled={busy !== ""}>
            {busy === "purpose" ? "Generando…" : "Generar propósito"}
          </Button>
        ) : null}
        {!agentId ? (
          <span className="text-[11.5px] text-faint">
            Guardá el agente para generar con IA y ver el preview.
          </span>
        ) : null}
      </div>

      {onPurpose ? (
        <AgentField
          id="agent-studio-purpose"
          label="Propósito"
          hint="¿Qué debe lograr? Usá «Generar propósito» como borrador."
        >
          <Textarea
            id="agent-studio-purpose"
            className="min-h-20"
            value={purpose ?? ""}
            onChange={(e) => onPurpose(e.target.value)}
            placeholder="Explicar reglas tarifarias con la documentación autorizada."
          />
        </AgentField>
      ) : null}

      {notice ? <p className="text-[11.5px] text-ok">{notice}</p> : null}
      {error ? <p className="text-[11.5px] text-danger">{error}</p> : null}

      <div className="rounded-md border border-border-soft p-3">
        <p className="text-[12px] text-text">Preview de respuesta</p>
        <p className="text-[11.5px] text-faint">
          Usa conocimiento simulado: muestra forma y estilo, no hechos reales.
          {sourceTitles.length ? ` Fuentes configuradas: ${sourceTitles.slice(0, 3).join(", ")}.` : ""}
        </p>
        <div className="mt-2 flex flex-col gap-2">
          <Textarea
            aria-label="Pregunta de prueba"
            className="min-h-16"
            value={previewQuestion}
            onChange={(e) => setPreviewQuestion(e.target.value)}
          />
          <div>
            <Button type="button" variant="secondary" onClick={() => void runPreview()} disabled={busy !== ""}>
              {busy === "preview" ? "Generando…" : "Ver cómo respondería"}
            </Button>
          </div>
        </div>
        {preview ? (
          <div className="mt-3 rounded border border-border bg-surface/60 p-2">
            {previewContract ? (
              <p className="mb-1 text-[11.5px] text-faint">
                Forma elegida: {String(previewContract.blueprint)} · nivel{" "}
                {String(previewContract.detail)} · {String(previewContract.decided_by)}
              </p>
            ) : null}
            <p className="whitespace-pre-wrap text-[12.5px] text-text">{preview}</p>
          </div>
        ) : null}
      </div>
    </section>
  );
}

export default AgentResponseProfileSection;
