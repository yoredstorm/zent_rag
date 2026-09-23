// =============================================================================
// AgentResponseProfileSection — "Cómo debe responder" (§27-§36)
// =============================================================================
// Separa PROPÓSITO ("qué debe lograr", vive en Identidad) de PERFIL DE RESPUESTA
// ("cómo debe explicarlo"). El perfil es estructura: idioma, tono, nivel,
// detalle, formato, citas y qué hacer con la incertidumbre.
//
// El generador con IA propone ESTILO. Nunca hechos ni capacidades que el agente
// no tenga: eso vive en el conocimiento, no en el prompt.
import { Sparkle } from "@phosphor-icons/react";
import { useState } from "react";
import { api } from "../../api";
import { Badge, Button, Select, Textarea } from "../ui";
import { AgentField, AgentOptionCard, AgentSection, AgentToggleGrid } from "./AgentField";
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
  sourceTitles = [],
}: {
  profile: ResponseProfile;
  onChange: (next: ResponseProfile) => void;
  /** Sin agente guardado no hay generación con IA: se avisa, no se simula. */
  agentId?: string;
  token?: string;
  organizationId?: string;
  sourceTitles?: string[];
}) {
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [preview, setPreview] = useState("");
  const [previewQuestion, setPreviewQuestion] = useState(
    "¿Qué significa el campo X cuando su valor es 2?",
  );
  const [previewContract, setPreviewContract] = useState<Record<string, unknown> | null>(null);

  const activePreset = profile.preset ?? "";

  function set<K extends keyof ResponseProfile>(key: K, value: ResponseProfile[K]) {
    onChange({ ...profile, [key]: value });
  }

  async function generateProfile() {
    if (!agentId) {
      setNotice("");
      setError("Guardá el agente primero: el generador sólo usa datos reales del agente.");
      return;
    }
    setBusy("profile");
    setError("");
    setNotice("");
    try {
      const data = await api<{ draft: Record<string, unknown> }>(
        `/api/v1/agents/${agentId}/config/response-profile`,
        { method: "POST", token, organizationId, body: JSON.stringify({}) },
      );
      const draft = data.draft as Partial<ResponseProfile>;
      onChange({
        ...profile,
        ...draft,
        preset: typeof draft.preset === "string" ? draft.preset : profile.preset,
      });
      setNotice("Perfil propuesto. Ajustá lo que quieras antes de guardar.");
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
    <section className="grid gap-6" data-testid="agent-response-profile">
      <AgentSection
        title="Cómo debe responder"
        hint="Cómo explicar la respuesta. No cambia qué puede concluir el agente: eso lo deciden la evidencia y el análisis."
        actions={
          <Button
            variant="secondary"
            size="sm"
            leadingIcon={Sparkle}
            loading={busy === "profile"}
            onClick={() => void generateProfile()}
          >
            Generar con IA
          </Button>
        }
      >
        <div>
          <p className="mb-2 flex items-center gap-2 text-xs text-muted">
            Estilo base
            {activePreset && !RESPONSE_PROFILE_PRESETS.some((p) => p.id === activePreset) ? (
              <Badge tone="neutral">Personalizado</Badge>
            ) : null}
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            {RESPONSE_PROFILE_PRESETS.map((preset) => (
              <AgentOptionCard
                key={preset.id}
                id={`response-preset-${preset.id}`}
                label={preset.label}
                hint={preset.hint}
                selected={activePreset === preset.id}
                onSelect={() => onChange({ ...profile, ...preset.profile, preset: preset.id })}
              />
            ))}
          </div>
        </div>
      </AgentSection>

      <div className="grid gap-3 sm:grid-cols-2">
        <AgentField id="response-detail" label="Nivel de detalle" hint="Cuánto explicar.">
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

      <AgentSection
        title="Formato y evidencia"
        hint="Qué puede usar la respuesta y qué debe declarar."
      >
        <AgentToggleGrid
          options={RESPONSE_PROFILE_TOGGLES.map((toggle) => ({
            key: String(toggle.key),
            label: toggle.label,
            checked: Boolean(profile[toggle.key]),
            onChange: (checked: boolean) => onChange({ ...profile, [toggle.key]: checked }),
          }))}
        />
      </AgentSection>

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

      <AgentSection
        title="Preview de respuesta"
        hint="Usa conocimiento simulado: muestra forma y estilo, no hechos reales."
      >
        <div className="flex flex-col gap-2">
          <Textarea
            aria-label="Pregunta de prueba"
            className="min-h-16"
            value={previewQuestion}
            onChange={(e) => setPreviewQuestion(e.target.value)}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              loading={busy === "preview"}
              onClick={() => void runPreview()}
            >
              Ver cómo respondería
            </Button>
            {sourceTitles.length ? (
              <span className="text-[11.5px] text-faint">
                Fuentes configuradas: {sourceTitles.slice(0, 3).join(", ")}
              </span>
            ) : null}
          </div>
        </div>
        {preview ? (
          <div className="rounded-md border border-border bg-surface/60 p-3">
            {previewContract ? (
              <div className="mb-2 flex flex-wrap items-center gap-1.5">
                <Badge tone="accent">{String(previewContract.blueprint)}</Badge>
                <Badge tone="neutral">{String(previewContract.detail)}</Badge>
                <Badge tone="neutral">{String(previewContract.decided_by)}</Badge>
              </div>
            ) : null}
            <p className="whitespace-pre-wrap text-[12.5px] text-text">{preview}</p>
          </div>
        ) : null}
      </AgentSection>
    </section>
  );
}

export default AgentResponseProfileSection;
