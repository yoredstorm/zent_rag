import {
  ArrowLeft,
  ChartLineUp,
  ChatCircleDots,
  FloppyDisk,
  PaperPlaneRight,
  Play,
  Robot,
} from "@phosphor-icons/react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  Spinner,
  StatCard,
  SuccessInline,
} from "../components/ui";

const TABS = [
  "instructions",
  "knowledge",
  "tools",
  "model",
  "security",
  "limits",
  "analytics",
  "playground",
  "embed",
] as const;

type Tab = (typeof TABS)[number];

const TAB_LABELS: Record<Tab, string> = {
  instructions: "Instructions",
  knowledge: "Knowledge",
  tools: "Tools",
  model: "Model",
  security: "Security",
  limits: "Limits",
  analytics: "Analytics",
  playground: "Playground",
  embed: "Embed",
};

type AgentConfig = {
  purpose: string | null;
  temperature: number;
  tone: "professional" | "friendly" | "concise";
  knowledge_base_ids: string[];
  limits: {
    max_steps: number | null;
    max_tokens: number | null;
    max_cost_usd: number | null;
  } | null;
  security: { sql_enabled: boolean; api_calls_enabled: boolean } | null;
};

type Agent = {
  id: string;
  name: string;
  description: string | null;
  system_prompt: string | null;
  tools: string[];
  model: string | null;
  is_active: boolean;
  created_at: string;
  config: AgentConfig;
};

type KB = { id: string; name: string; status: string };

type UsageRow = {
  agent_id: string;
  requests: number;
  tokens: number;
  estimated_cost: number;
  avg_latency_ms: number;
};

function defaultConfig(): AgentConfig {
  return {
    purpose: "",
    temperature: 0.2,
    tone: "professional",
    knowledge_base_ids: [],
    limits: { max_steps: 8, max_tokens: 4000, max_cost_usd: 0.5 },
    security: { sql_enabled: false, api_calls_enabled: false },
  };
}

function toolsFromCapabilities(semantic: boolean, sql: boolean, apiCalls: boolean): string[] {
  const tools: string[] = [];
  if (semantic) tools.push("search_knowledge");
  if (sql) tools.push("query_database");
  if (apiCalls) tools.push("call_api");
  return tools;
}

export default function AgentBuilderPage() {
  const { id } = useParams<{ id: string }>();
  const isNew = !id || id === "new";
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { session } = useAuth();
  const tab = (TABS.includes(searchParams.get("tab") as Tab)
    ? (searchParams.get("tab") as Tab)
    : isNew
      ? "instructions"
      : "instructions") as Tab;

  const [agent, setAgent] = useState<Agent | null>(null);
  const [kbs, setKbs] = useState<KB[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [model, setModel] = useState("");
  const [routes, setRoutes] = useState<{ name: string; description: string }[]>([]);
  const [canCustomModel, setCanCustomModel] = useState(false);
  const [config, setConfig] = useState<AgentConfig>(defaultConfig());
  const [semantic, setSemantic] = useState(true);
  const [sql, setSql] = useState(false);
  const [apiCalls, setApiCalls] = useState(false);
  const [isActive, setIsActive] = useState(true);
  const [loading, setLoading] = useState(!isNew);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [usage, setUsage] = useState<UsageRow | null>(null);
  const [playInput, setPlayInput] = useState("");
  const [playAnswer, setPlayAnswer] = useState("");
  const [playStatus, setPlayStatus] = useState("");
  const [playing, setPlaying] = useState(false);
  const [embedOrigins, setEmbedOrigins] = useState("https://");
  const [embedScript, setEmbedScript] = useState("");
  const [embedToken, setEmbedToken] = useState("");
  const [embedBusy, setEmbedBusy] = useState(false);

  function setTab(next: Tab) {
    setSearchParams({ tab: next }, { replace: true });
  }

  useEffect(() => {
    if (!session) return;
    api<{ knowledge_bases: KB[] }>("/api/v1/knowledge-bases", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => setKbs(data.knowledge_bases || []))
      .catch(() => setKbs([]));
  }, [session]);

  useEffect(() => {
    if (!session || isNew) return;
    setLoading(true);
    api<Agent>(`/api/v1/agents/${id}`, {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => {
        setAgent(data);
        setName(data.name);
        setDescription(data.description || "");
        setSystemPrompt(data.system_prompt || "");
        setModel(data.model || "");
        setConfig({ ...defaultConfig(), ...data.config });
        setSemantic(data.tools.includes("search_knowledge"));
        setSql(data.tools.includes("query_database"));
        setApiCalls(data.tools.includes("call_api"));
        setIsActive(data.is_active);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoading(false));
  }, [session, id, isNew]);

  useEffect(() => {
    if (!session) return;
    api<{ routes: { name: string; description: string }[] }>("/api/v1/gateway/routes", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((out) => setRoutes(out.routes || []))
      .catch(() => setRoutes([]));
    api<{ entitlements: Record<string, boolean | number | null> }>(
      "/api/v1/billing/entitlements",
      { token: session.token, organizationId: session.organizationId }
    )
      .then((out) => setCanCustomModel(out.entitlements?.custom_models === true))
      .catch(() => setCanCustomModel(false));
  }, [session]);

  useEffect(() => {
    if (!session || isNew || tab !== "analytics") return;
    api<{ agents: UsageRow[] }>("/api/v1/billing/usage/agents", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => {
        const row = (data.agents || []).find((a) => a.agent_id === id) || null;
        setUsage(row);
      })
      .catch(() => setUsage(null));
  }, [session, id, isNew, tab]);

  const payload = useMemo(
    () => ({
      name: name.trim(),
      description: description.trim() || null,
      system_prompt: systemPrompt.trim() || null,
      model: model.trim() || null,
      tools: toolsFromCapabilities(semantic, sql, apiCalls),
      is_active: isActive,
      config: {
        purpose: config.purpose?.trim() || null,
        temperature: config.temperature,
        tone: config.tone,
        knowledge_base_ids: config.knowledge_base_ids,
        limits: config.limits,
        security: {
          sql_enabled: sql,
          api_calls_enabled: apiCalls,
        },
      },
    }),
    [name, description, systemPrompt, model, semantic, sql, apiCalls, isActive, config]
  );

  async function save() {
    if (!session || !name.trim()) return;
    setSaving(true);
    setError("");
    setMsg("");
    try {
      if (isNew) {
        const created = await api<Agent>("/api/v1/agents", {
          method: "POST",
          token: session.token,
          organizationId: session.organizationId,
          body: JSON.stringify(payload),
        });
        setMsg("Agente creado.");
        navigate(`/agents/${created.id}?tab=playground`);
      } else {
        const updated = await api<Agent>(`/api/v1/agents/${id}`, {
          method: "PUT",
          token: session.token,
          organizationId: session.organizationId,
          body: JSON.stringify(payload),
        });
        setAgent(updated);
        setMsg("Cambios guardados.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al guardar");
    } finally {
      setSaving(false);
    }
  }

  async function runPlayground(event: FormEvent) {
    event.preventDefault();
    if (!session || !id || !playInput.trim()) return;
    setPlaying(true);
    setPlayAnswer("");
    setPlayStatus("Ejecutando agente…");
    setError("");
    try {
      const res = await fetch(`/api/v1/agents/${id}/run/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session.token}`,
          "X-Organization-Id": session.organizationId,
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify({ message: playInput.trim() }),
      });
      if (!res.ok || !res.body) {
        let message = `HTTP ${res.status}`;
        try {
          const data = await res.json();
          message = data.detail || data.message || message;
        } catch {
          // keep HTTP status
        }
        throw new Error(typeof message === "string" ? message : "Error al ejecutar");
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx: number;
        while ((idx = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          let eventName = "message";
          let data = "";
          for (const line of frame.split("\n")) {
            if (line.startsWith("event: ")) eventName = line.slice(7).trim();
            else if (line.startsWith("data: ")) data += line.slice(6);
          }
          if (!data) continue;
          const payloadJson = JSON.parse(data) as {
            phase?: string;
            answer?: string;
            status?: string;
            message?: string;
          };
          if (eventName === "status") {
            setPlayStatus(payloadJson.phase === "running" ? "Ejecutando agente…" : "En curso…");
          } else if (eventName === "done") {
            setPlayAnswer(payloadJson.answer || "");
            setPlayStatus(payloadJson.status === "completed" ? "Listo" : payloadJson.status || "Listo");
          } else if (eventName === "error") {
            throw new Error(payloadJson.message || "Error en el stream");
          }
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error en playground");
      setPlayStatus("");
    } finally {
      setPlaying(false);
    }
  }

  if (loading) {
    return (
      <div className="panel p-5">
        <SkeletonBlock rows={6} />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title={isNew ? "Crear agente" : name || "Agente"}
        subtitle={
          isNew
            ? "Define instrucciones, conocimiento, tools, modelo y límites. Prueba en el playground."
            : config.purpose || "Configura y prueba tu agente."
        }
        actions={
          <Link to="/agents" className="btn btn-secondary min-h-11">
            <ArrowLeft size={16} aria-hidden />
            Volver
          </Link>
        }
      />
      <ErrorInline message={error} />
      <SuccessInline message={msg} />

      <div className="mb-4 flex flex-wrap gap-1 overflow-x-auto" role="tablist" aria-label="Secciones del agente">
        {TABS.map((item) => (
          <button
            key={item}
            type="button"
            role="tab"
            aria-selected={tab === item}
            className={`min-h-11 whitespace-nowrap rounded-md px-3 py-2 text-sm ${
              tab === item
                ? "bg-accent-soft font-medium text-accent"
                : "text-muted hover:bg-soft hover:text-text"
            }`}
            onClick={() => setTab(item)}
          >
            {TAB_LABELS[item]}
          </button>
        ))}
      </div>

      {(tab === "instructions" || isNew) && tab === "instructions" && (
        <section className="panel p-5">
          <div className="grid gap-4">
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-text">Nombre</span>
              <input
                className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus-visible:ring-2 focus-visible:ring-accent"
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoComplete="off"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-text">Propósito</span>
              <input
                className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus-visible:ring-2 focus-visible:ring-accent"
                value={config.purpose || ""}
                onChange={(e) => setConfig({ ...config, purpose: e.target.value })}
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-text">Instrucciones (system prompt)</span>
              <textarea
                className="min-h-36 w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus-visible:ring-2 focus-visible:ring-accent"
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-text">Descripción</span>
              <input
                className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus-visible:ring-2 focus-visible:ring-accent"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>
          </div>
        </section>
      )}

      {tab === "knowledge" && (
        <section className="panel p-5">
          {kbs.length === 0 ? (
            <EmptyState
              icon={Robot}
              title="Sin colecciones"
              body="Crea una knowledge base en Conocimiento para asignarla a este agente."
            />
          ) : (
            <fieldset>
              <legend className="mb-3 text-sm font-medium text-text">Knowledge bases del tenant</legend>
              <div className="grid gap-2">
                {kbs.map((kb) => {
                  const checked = config.knowledge_base_ids.includes(kb.id);
                  return (
                    <label key={kb.id} className="flex min-h-11 items-center gap-3 rounded-md border border-border px-3 py-2">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => {
                          const next = checked
                            ? config.knowledge_base_ids.filter((x) => x !== kb.id)
                            : [...config.knowledge_base_ids, kb.id];
                          setConfig({ ...config, knowledge_base_ids: next });
                        }}
                      />
                      <span className="text-sm text-text">{kb.name}</span>
                      <span className="text-xs text-faint">{kb.status}</span>
                    </label>
                  );
                })}
              </div>
            </fieldset>
          )}
        </section>
      )}

      {tab === "tools" && (
        <section className="panel p-5">
          <fieldset className="grid gap-3">
            <legend className="mb-1 text-sm font-medium text-text">Capabilities</legend>
            <label className="flex min-h-11 items-center gap-3">
              <input type="checkbox" checked={semantic} onChange={(e) => setSemantic(e.target.checked)} />
              <span className="text-sm text-text">Búsqueda semántica (search_knowledge)</span>
            </label>
            <label className="flex min-h-11 items-center gap-3">
              <input type="checkbox" checked={sql} onChange={(e) => setSql(e.target.checked)} />
              <span className="text-sm text-text">SQL Expert (query_database)</span>
            </label>
            <label className="flex min-h-11 items-center gap-3">
              <input type="checkbox" checked={apiCalls} onChange={(e) => setApiCalls(e.target.checked)} />
              <span className="text-sm text-text">API Calls (call_api)</span>
            </label>
          </fieldset>
        </section>
      )}

      {tab === "model" && (
        <section className="panel grid gap-4 p-5">
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-text">Ruta del gateway</span>
            <select
              className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus-visible:ring-2 focus-visible:ring-accent"
              value={routes.some((r) => r.name === model) ? model : model && canCustomModel ? "__custom__" : "zent-default"}
              onChange={(e) => {
                const next = e.target.value;
                if (next === "__custom__") {
                  setModel("");
                  return;
                }
                setModel(next);
              }}
            >
              <option value="zent-default">zent-default</option>
              {routes
                .filter((r) => r.name !== "zent-default")
                .map((r) => (
                  <option key={r.name} value={r.name}>
                    {r.name}
                  </option>
                ))}
              {canCustomModel && <option value="__custom__">Modelo custom…</option>}
            </select>
            <p className="mt-1 text-xs text-muted">
              Alias virtual. Zent resuelve el modelo real y un fallback. Usage registra el modelo real, no el alias.
            </p>
          </label>
          {canCustomModel && (!routes.some((r) => r.name === model) || model === "") && (
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-text">Modelo custom</span>
              <input
                className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus-visible:ring-2 focus-visible:ring-accent"
                placeholder="openai/gpt-4o-mini"
                value={routes.some((r) => r.name === model) ? "" : model}
                onChange={(e) => setModel(e.target.value)}
              />
            </label>
          )}
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-text">
              Temperature ({config.temperature.toFixed(2)})
            </span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={config.temperature}
              onChange={(e) => setConfig({ ...config, temperature: Number(e.target.value) })}
              className="w-full"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-text">Tono</span>
            <select
              className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus-visible:ring-2 focus-visible:ring-accent"
              value={config.tone}
              onChange={(e) =>
                setConfig({
                  ...config,
                  tone: e.target.value as AgentConfig["tone"],
                })
              }
            >
              <option value="professional">Professional</option>
              <option value="friendly">Friendly</option>
              <option value="concise">Concise</option>
            </select>
          </label>
        </section>
      )}

      {tab === "security" && (
        <section className="panel p-5">
          <p className="mb-3 text-sm text-muted">
            Estas opciones se guardan en config.security y filtran tools en el runtime.
          </p>
          <fieldset className="grid gap-3">
            <label className="flex min-h-11 items-center gap-3">
              <input type="checkbox" checked={sql} onChange={(e) => setSql(e.target.checked)} />
              <span className="text-sm text-text">Permitir SQL Expert</span>
            </label>
            <label className="flex min-h-11 items-center gap-3">
              <input type="checkbox" checked={apiCalls} onChange={(e) => setApiCalls(e.target.checked)} />
              <span className="text-sm text-text">Permitir API Calls</span>
            </label>
          </fieldset>
        </section>
      )}

      {tab === "limits" && (
        <section className="panel grid gap-4 p-5 sm:grid-cols-3">
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-text">Max steps</span>
            <input
              type="number"
              min={1}
              max={100}
              inputMode="numeric"
              className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm"
              value={config.limits?.max_steps ?? 8}
              onChange={(e) =>
                setConfig({
                  ...config,
                  limits: { ...(config.limits || defaultConfig().limits!), max_steps: Number(e.target.value) },
                })
              }
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-text">Max tokens</span>
            <input
              type="number"
              min={1}
              inputMode="numeric"
              className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm"
              value={config.limits?.max_tokens ?? 4000}
              onChange={(e) =>
                setConfig({
                  ...config,
                  limits: { ...(config.limits || defaultConfig().limits!), max_tokens: Number(e.target.value) },
                })
              }
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-text">Max cost USD</span>
            <input
              type="number"
              min={0}
              step={0.01}
              inputMode="decimal"
              className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm"
              value={config.limits?.max_cost_usd ?? 0.5}
              onChange={(e) =>
                setConfig({
                  ...config,
                  limits: {
                    ...(config.limits || defaultConfig().limits!),
                    max_cost_usd: Number(e.target.value),
                  },
                })
              }
            />
          </label>
        </section>
      )}

      {tab === "analytics" && (
        <section>
          {!usage ? (
            <div className="panel">
              <EmptyState
                icon={ChartLineUp}
                title="Sin uso aún"
                body="Ejecuta el agente en el playground para ver requests, tokens y costo."
              />
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard label="Requests" value={usage.requests} />
              <StatCard label="Tokens" value={usage.tokens} />
              <StatCard label="Costo estimado" value={`$${usage.estimated_cost.toFixed(4)}`} />
              <StatCard label="Latencia media" value={`${usage.avg_latency_ms.toFixed(0)} ms`} />
            </div>
          )}
        </section>
      )}

      {tab === "embed" && (
        <section className="panel grid gap-4 p-5">
          {isNew ? (
            <EmptyState
              icon={Robot}
              title="Guarda el agente primero"
              body="El widget requiere un token de embed. Tu plan debe incluir embed_widget."
            />
          ) : (
            <>
              <p className="text-sm text-muted">
                Publica el agente en tu web. El cliente debe permitir el script/iframe de
                Zent en su CSP (script-src / frame-src). El widget no usa cookies de tracking.
              </p>
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-text">Orígenes permitidos</span>
                <input
                  className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm"
                  value={embedOrigins}
                  onChange={(e) => setEmbedOrigins(e.target.value)}
                  placeholder="https://farmacia.cl, https://www.farmacia.cl"
                />
              </label>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className="btn btn-primary min-h-11"
                  disabled={embedBusy}
                  onClick={() => {
                    if (!session || !id) return;
                    setEmbedBusy(true);
                    setError("");
                    api<{ token: string; public_id: string }>(`/api/v1/agents/${id}/embed/token`, {
                      method: "POST",
                      token: session.token,
                      organizationId: session.organizationId,
                      body: JSON.stringify({
                        allowed_origins: embedOrigins
                          .split(",")
                          .map((s) => s.trim())
                          .filter(Boolean),
                      }),
                    })
                      .then((data) => {
                        setEmbedToken(data.token);
                        setEmbedScript(
                          `<script src="${window.location.origin}/embed.js" data-embed="${data.public_id}"></script>`
                        );
                        setMsg("Token creado. Cópialo ahora; no se vuelve a mostrar.");
                      })
                      .catch((err) => setError(err instanceof Error ? err.message : "Error embed"))
                      .finally(() => setEmbedBusy(false));
                  }}
                >
                  {embedBusy ? <Spinner size={14} /> : "Crear token"}
                </button>
                <button
                  type="button"
                  className="btn btn-secondary min-h-11"
                  disabled={embedBusy}
                  onClick={() => {
                    if (!session || !id) return;
                    setEmbedBusy(true);
                    api(`/api/v1/agents/${id}/embed/revoke`, {
                      method: "POST",
                      token: session.token,
                      organizationId: session.organizationId,
                    })
                      .then(() => {
                        setEmbedToken("");
                        setEmbedScript("");
                        setMsg("Token revocado.");
                      })
                      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
                      .finally(() => setEmbedBusy(false));
                  }}
                >
                  Revocar
                </button>
              </div>
              {embedToken && (
                <p className="break-all rounded-md border border-border bg-soft p-3 font-mono text-xs">
                  {embedToken}
                </p>
              )}
              {embedScript && (
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-text">Snippet</span>
                  <textarea
                    readOnly
                    className="min-h-20 w-full rounded-md border border-border bg-soft p-3 font-mono text-xs"
                    value={embedScript}
                  />
                </label>
              )}
            </>
          )}
        </section>
      )}

      {tab === "playground" && (
        <section className="panel p-5">
          {isNew ? (
            <EmptyState
              icon={Play}
              title="Guarda el agente primero"
              body="Crea el agente para probarlo con POST /agents/{id}/run/stream."
            />
          ) : (
            <>
              <form className="flex flex-col gap-3 sm:flex-row" onSubmit={(e) => void runPlayground(e)}>
                <label className="block flex-1">
                  <span className="sr-only">Mensaje</span>
                  <input
                    className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus-visible:ring-2 focus-visible:ring-accent"
                    placeholder="Pregunta al agente…"
                    value={playInput}
                    onChange={(e) => setPlayInput(e.target.value)}
                    disabled={playing}
                  />
                </label>
                <button className="btn btn-primary min-h-11" type="submit" disabled={playing || !playInput.trim()}>
                  {playing ? <Spinner size={14} /> : <PaperPlaneRight size={15} aria-hidden />}
                  Probar
                </button>
              </form>
              {playStatus && <p className="mt-3 text-sm text-muted">{playStatus}</p>}
              {playAnswer && (
                <div className="mt-4 rounded-md border border-border bg-soft p-4 text-sm leading-relaxed text-text whitespace-pre-wrap">
                  {playAnswer}
                </div>
              )}
              <p className="mt-3 text-xs text-faint">
                Este playground usa el Agent Runtime, no el chat genérico de /chat.
              </p>
            </>
          )}
        </section>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          className="btn btn-primary min-h-11"
          disabled={saving || !name.trim()}
          onClick={() => void save()}
        >
          {saving ? <Spinner size={14} /> : <FloppyDisk size={15} aria-hidden />}
          {isNew ? "Crear agente" : "Guardar"}
        </button>
        {!isNew && (
          <label className="flex min-h-11 items-center gap-2 text-sm text-muted">
            <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
            Activo
          </label>
        )}
        {!isNew && (
          <span className="inline-flex items-center gap-1 text-xs text-faint">
            <ChatCircleDots size={14} aria-hidden />
            {agent?.tools.join(", ") || "sin tools"}
          </span>
        )}
      </div>
    </div>
  );
}
