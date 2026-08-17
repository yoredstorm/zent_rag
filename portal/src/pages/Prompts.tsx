import { Flask, FloppyDisk, User, Users } from "@phosphor-icons/react";
import { FormEvent, useEffect, useRef, useState } from "react";
import { marked } from "marked";
import { api } from "../api";
import { useAuth } from "../auth";
import { useToast } from "../Toast";
import { ErrorInline, PageHeader, SkeletonBlock, Spinner } from "../components/ui";

type RolePrompt = {
  system_prompt: string;
  custom_instructions: string;
  is_customized: boolean;
};

type PromptStatus = {
  roles: Record<string, RolePrompt>;
};

marked.setOptions({ gfm: true, breaks: true });

function renderMarkdown(text: string) {
  const html = marked.parse(text, { async: false }) as string;
  return { __html: html };
}

export default function PromptsPage() {
  const { session } = useAuth();
  const { pushToast } = useToast();
  const [role, setRole] = useState<"admin" | "customer">("admin");
  const [roles, setRoles] = useState<PromptStatus["roles"]>({});
  const [prompt, setPrompt] = useState("");
  const [instructions, setInstructions] = useState("");
  const [loadedPrompt, setLoadedPrompt] = useState("");
  const [loadedInstructions, setLoadedInstructions] = useState("");
  const [testQuery, setTestQuery] = useState("¿Cuáles son los productos disponibles?");
  const [testAnswer, setTestAnswer] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState("");

  const dirty = prompt !== loadedPrompt || instructions !== loadedInstructions;

  function applyRole(data: PromptStatus["roles"], nextRole: "admin" | "customer") {
    const r = data[nextRole];
    if (r) {
      setPrompt(r.system_prompt);
      setInstructions(r.custom_instructions || "");
      setLoadedPrompt(r.system_prompt);
      setLoadedInstructions(r.custom_instructions || "");
    }
  }

  useEffect(() => {
    if (!session) return;
    setLoading(true);
    setError("");
    setTestAnswer("");
    api<PromptStatus>("/api/v1/admin/prompt", {
      token: session.token,
      tenantId: session.tenantId,
    })
      .then((data) => {
        setRoles(data.roles || {});
        applyRole(data.roles || {}, role);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, role]);

  function switchRole(next: "admin" | "customer") {
    if (dirty && !window.confirm("Hay cambios sin guardar. ¿Descartar y cambiar de vista?")) {
      return;
    }
    setRole(next);
    if (roles[next]) {
      applyRole(roles, next);
    }
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!session) return;
    setError("");
    setSaving(true);
    try {
      await api("/api/v1/admin/prompt", {
        method: "PUT",
        token: session.token,
        tenantId: session.tenantId,
        body: JSON.stringify({
          system_prompt: prompt,
          custom_instructions: instructions,
          role,
        }),
      });
      setLoadedPrompt(prompt);
      setLoadedInstructions(instructions);
      setRoles((prev) => ({
        ...prev,
        [role]: {
          system_prompt: prompt,
          custom_instructions: instructions,
          is_customized: true,
        },
      }));
      pushToast("success", "Prompt guardado", `Vista ${role === "admin" ? "equipo" : "cliente"} actualizada.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al guardar");
    } finally {
      setSaving(false);
    }
  }

  async function testPrompt() {
    if (!session) return;
    setError("");
    setTestAnswer("");
    setTesting(true);
    try {
      const data = await api<{ answer: string }>("/api/v1/admin/prompt/test", {
        method: "POST",
        token: session.token,
        tenantId: session.tenantId,
        body: JSON.stringify({
          query: testQuery,
          system_prompt: prompt,
          custom_instructions: instructions,
          role,
        }),
      });
      setTestAnswer(data.answer);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Test falló");
    } finally {
      setTesting(false);
    }
  }

  const testInputRef = useRef<HTMLInputElement>(null);

  return (
    <div>
      <PageHeader
        title="Prompts"
        subtitle="Instrucciones del asistente según la vista. El test usa el pipeline RAG real con tus datos, sin guardar cambios."
      />
      <ErrorInline message={error} />

      <div className="mb-4 flex gap-1 rounded-md border border-border bg-surface p-1">
        {(
          [
            { value: "admin", label: "Vista equipo", icon: Users },
            { value: "customer", label: "Vista cliente", icon: User },
          ] as const
        ).map(({ value, label, icon: IconEl }) => (
          <button
            key={value}
            type="button"
            className={`flex flex-1 cursor-pointer items-center justify-center gap-2 rounded-xs px-3 py-2 text-[13px] transition-colors duration-150 sm:flex-none sm:px-6 ${
              role === value
                ? "bg-accent-soft font-medium text-accent"
                : "text-muted hover:bg-soft hover:text-text"
            }`}
            onClick={() => switchRole(value)}
          >
            <IconEl size={15} aria-hidden />
            {label}
            {roles[value]?.is_customized && (
              <span className="badge badge-ok px-1.5 py-0 text-[10px]">Personalizado</span>
            )}
          </button>
        ))}
        {dirty && (
          <span className="ml-auto flex items-center gap-1.5 px-2 text-[11px] text-warn">
            <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-warn" aria-hidden />
            Sin guardar
          </span>
        )}
      </div>

      {loading ? (
        <div className="panel p-5">
          <SkeletonBlock rows={8} />
        </div>
      ) : (
        <div className="grid items-start gap-4 xl:grid-cols-2">
          <form className="panel space-y-4 p-5" onSubmit={save}>
            <div className="field">
              <label htmlFor="prompt">System prompt</label>
              <textarea
                id="prompt"
                rows={10}
                className="font-mono text-[13px] leading-relaxed"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="instr">Custom instructions</label>
              <textarea
                id="instr"
                rows={5}
                className="font-mono text-[13px] leading-relaxed"
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
              />
            </div>
            <div className="flex items-center gap-2">
              <button className="btn btn-primary" type="submit" disabled={saving || !dirty}>
                {saving ? (
                  <>
                    <Spinner size={14} /> Guardando…
                  </>
                ) : (
                  <>
                    <FloppyDisk size={15} aria-hidden /> Guardar
                  </>
                )}
              </button>
              {dirty && (
                <button
                  type="button"
                  className="btn btn-ghost text-[13px]"
                  onClick={() => {
                    setPrompt(loadedPrompt);
                    setInstructions(loadedInstructions);
                  }}
                >
                  Descartar cambios
                </button>
              )}
            </div>
          </form>

          <div className="panel flex flex-col p-5">
            <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-text">
              <Flask size={16} className="text-accent" aria-hidden />
              Probar sin guardar
            </h2>
            <div className="field">
              <label htmlFor="tq">Pregunta</label>
              <input
                id="tq"
                ref={testInputRef}
                value={testQuery}
                onChange={(e) => setTestQuery(e.target.value)}
              />
            </div>
            <button
              className="btn btn-secondary mt-3 self-start"
              type="button"
              disabled={testing}
              onClick={() => void testPrompt()}
            >
              {testing ? (
                <>
                  <Spinner size={14} /> Ejecutando pipeline RAG…
                </>
              ) : (
                "Probar"
              )}
            </button>
            {testing && (
              <div className="mt-4">
                <SkeletonBlock rows={4} />
              </div>
            )}
            {testAnswer && !testing && (
              <div className="mt-4 rounded-md border border-border bg-bg/50 p-4">
                <p className="mb-2 text-[11px] font-semibold tracking-[0.08em] text-faint uppercase">
                  Respuesta con datos reales
                </p>
                <div
                  className="chat-markdown text-sm leading-relaxed text-text"
                  dangerouslySetInnerHTML={renderMarkdown(testAnswer)}
                />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
