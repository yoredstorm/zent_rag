import {
  ArrowClockwise,
  ChatCircleDots,
  DownloadSimple,
  Lightbulb,
  Robot,
  Sparkle,
  Tag,
  Trash,
  WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Badge,
  Button,
  EmptyState,
  ErrorInline,
  LoadingDots,
  PageHeader,
  Panel,
  PanelHeader,
  Select,
  Skeleton,
  SuccessInline,
  Textarea,
  cn,
} from "../components/ui";
import { fmtNum, timeAgo } from "../lib/format";

type MarketAgent = { id: string; name: string; slug: string; description: string; category: string; tags: string[]; rating: number; installs: number; featured: boolean };
type Install = { id: string; agent_id: string | null; agent_name: string; slug: string; category: string; usage_count: number; installed_at: string };
type Msg = { id: string; role: string; content: string; intent: string | null; created_at: string };
type Sugg = { intent: string; repeats: number; last_seen: string; suggested_name: string; sample_questions: string[]; suggestion: string };

/** Preguntas de arranque: llenan el composer, no envían solas. */
const STARTERS = [
  "consulta mi base de conocimiento",
  "crea un agente",
  "cuánto cuesta el plan",
  "despliega el agente",
];

export default function CopilotPage() {
  const { session } = useAuth();
  const [market, setMarket] = useState<MarketAgent[]>([]);
  const [installs, setInstalls] = useState<Install[]>([]);
  const [sugg, setSugg] = useState<Sugg[]>([]);
  const [sessions, setSessions] = useState<{ id: string; title: string; last_activity_at: string; messages: number }[]>([]);
  const [activeSession, setActiveSession] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  async function load() {
    if (!session) return;
    setLoadError("");
    try {
      const [m, i, s, ss] = await Promise.all([
        api<{ agents: MarketAgent[] }>("/api/v1/copilot/marketplace", { token: session.token, organizationId: session.organizationId }),
        api<{ installs: Install[] }>("/api/v1/copilot/marketplace/installs", { token: session.token, organizationId: session.organizationId }),
        api<{ suggestions: Sugg[] }>("/api/v1/copilot/automations/suggest", { token: session.token, organizationId: session.organizationId }),
        api<{ sessions: { id: string; title: string; last_activity_at: string; messages: number }[] }>("/api/v1/copilot/sessions", { token: session.token, organizationId: session.organizationId }),
      ]);
      setMarket(m.agents || []);
      setInstalls(i.installs || []);
      setSugg(s.suggestions || []);
      setSessions(ss.sessions || []);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs]);

  async function install(slug: string) {
    if (!session) return;
    setBusy(`i-${slug}`);
    setError("");
    setMsg("");
    try {
      const out = await api<{ installed: boolean; agent_id: string }>("/api/v1/copilot/marketplace/install", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ slug }),
      });
      setMsg(out.installed ? `Agente instalado (${out.agent_id.slice(0, 8)}…).` : "El agente ya estaba instalado.");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function remove(installId: string) {
    if (!session) return;
    setBusy(`rm-${installId}`);
    setError("");
    setMsg("");
    try {
      await api(`/api/v1/copilot/marketplace/${installId}/remove`, { method: "POST", token: session.token, organizationId: session.organizationId });
      setMsg("Agente desinstalado.");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function send() {
    if (!session || !input.trim() || busy) return;
    const text = input.trim();
    setInput("");
    setBusy("chat");
    setError("");
    try {
      const out = await api<{ session_id: string; intent: string | null; reply: string }>("/api/v1/copilot/chat", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ message: text, session_id: activeSession, title: text.slice(0, 60) }),
      });
      setActiveSession(out.session_id);
      await loadMsgs(out.session_id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function loadMsgs(sid: string) {
    if (!session) return;
    const m = await api<{ messages: Msg[] }>(`/api/v1/copilot/sessions/${sid}`, { token: session.token, organizationId: session.organizationId });
    setMsgs(m.messages || []);
  }

  async function openSession(sid: string) {
    setActiveSession(sid);
    await loadMsgs(sid);
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Copilot & Asistentes" subtitle="Marketplace de agentes pre-entrenados, chat contextual con router por intención y automatizaciones sugeridas." />
      <ErrorInline message={error} />
      <ErrorInline
        message={
          loadError && (market.length > 0 || installs.length > 0 || sessions.length > 0 || sugg.length > 0)
            ? loadError
            : ""
        }
      />
      <SuccessInline message={msg} />
      {loading ? (
        <div className="grid gap-4 lg:grid-cols-3" aria-hidden>
          <div className="flex flex-col gap-4 lg:col-span-2">
            <Panel className="h-[480px]">
              <div className="flex flex-col gap-4 p-4">
                <Skeleton className="h-5 w-32" />
                <Skeleton className="mt-4 h-16 w-2/3 rounded-lg" />
                <Skeleton className="mt-3 h-10 w-1/2 self-end rounded-lg" />
              </div>
            </Panel>
            <Skeleton className="h-40 rounded-lg" />
          </div>
          <Skeleton className="h-72 rounded-lg" />
        </div>
      ) : loadError && market.length === 0 && installs.length === 0 && sessions.length === 0 && sugg.length === 0 ? (
        <Panel>
          <EmptyState
            icon={WarningCircle}
            title="No pudimos cargar el copilot"
            body={loadError}
            hint="Revisá la conexión y volvé a intentar."
            action={
              <Button variant="secondary" leadingIcon={ArrowClockwise} onClick={() => void load()}>
                Reintentar
              </Button>
            }
          />
        </Panel>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <section className="flex flex-col gap-4 lg:col-span-2">
            {/* Foco: la conversación */}
            <Panel className="flex h-[480px] flex-col">
              <div className="panel-header shrink-0">
                <h2 className="flex items-center gap-2 text-h3">
                  <ChatCircleDots size={16} className="text-accent" aria-hidden />
                  Copilot
                </h2>
                <Select
                  aria-label="Conversación"
                  className="max-w-[240px] text-xs"
                  value={activeSession ?? ""}
                  onChange={(e) => {
                    if (e.target.value) void openSession(e.target.value);
                  }}
                >
                  <option value="">nueva conversación…</option>
                  {sessions.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.title.slice(0, 40)} ({s.messages})
                    </option>
                  ))}
                </Select>
              </div>

              <div
                role="log"
                aria-label="Conversación con el copilot"
                aria-live="polite"
                className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto px-4 py-4"
              >
                {msgs.length === 0 && (
                  <EmptyState
                    compact
                    icon={ChatCircleDots}
                    title="Empezá una conversación"
                    body="Preguntá por tu conocimiento, creá agentes o consultá el plan."
                    action={
                      <div className="flex max-w-md flex-wrap justify-center gap-1.5">
                        {STARTERS.map((prompt) => (
                          <button
                            key={prompt}
                            type="button"
                            className="source-chip transition-colors duration-150 hover:border-border-strong hover:text-text"
                            onClick={() => setInput(prompt)}
                          >
                            {prompt}
                          </button>
                        ))}
                      </div>
                    }
                  />
                )}
                {msgs.map((m) => (
                  <div
                    key={m.id}
                    className={cn("bubble", m.role === "user" ? "bubble-user ml-auto" : "bubble-assistant")}
                  >
                    <p className="whitespace-pre-wrap">{m.content}</p>
                    {m.intent && (
                      <p className="mt-1.5 flex items-center gap-1.5 text-[11px] text-faint">
                        <Tag size={11} aria-hidden />
                        intención: {m.intent}
                      </p>
                    )}
                  </div>
                ))}
                {busy === "chat" && (
                  <div className="state-rail py-1" data-state="running" aria-live="polite">
                    <span className="flex items-center gap-2 text-xs text-muted">
                      <LoadingDots label="El copilot está respondiendo" />
                      El copilot está respondiendo…
                    </span>
                  </div>
                )}
                <div ref={endRef} />
              </div>

              <div className="shrink-0 border-t border-border px-4 py-3">
                <div className="flex items-end gap-2">
                  <Textarea
                    rows={1}
                    aria-label="Mensaje para el copilot"
                    className="max-h-32 min-h-9 flex-1 resize-none py-2"
                    placeholder="Escribe tu consulta…"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey && !busy) {
                        e.preventDefault();
                        void send();
                      }
                    }}
                  />
                  <Button
                    variant="primary"
                    leadingIcon={Sparkle}
                    loading={busy === "chat"}
                    disabled={!input.trim()}
                    onClick={() => void send()}
                  >
                    Enviar
                  </Button>
                </div>
                <p className="mt-1.5 text-[11px] text-faint">
                  Enter envía · Shift+Enter agrega un salto de línea
                </p>
              </div>
            </Panel>

            {/* Sugerencias: patrones reales detectados por el router */}
            <Panel>
              <PanelHeader
                title={`Automatizaciones sugeridas (${sugg.length})`}
                description="Consultas repetidas que pueden convertirse en una automatización."
              />
              {sugg.length === 0 ? (
                <EmptyState
                  compact
                  icon={Lightbulb}
                  title="Sin sugerencias todavía"
                  body="Usa el copilot unas veces y Zent te va a proponer automatizaciones."
                />
              ) : (
                <ul className="divide-y divide-border-soft">
                  {sugg.map((s) => (
                    <li key={s.intent} className="px-4 py-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-[13px] font-medium text-text">{s.suggested_name}</p>
                        <Badge tone="accent">{s.repeats} consultas esta semana</Badge>
                      </div>
                      <p className="mt-1 text-xs leading-relaxed text-muted">{s.suggestion}</p>
                      {(s.sample_questions ?? []).length > 0 && (
                        <ul className="mt-2 flex flex-wrap gap-1.5">
                          {(s.sample_questions ?? []).map((q, i) => (
                            <li key={i} className="chip">
                              {q.slice(0, 60)}
                            </li>
                          ))}
                        </ul>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </section>

          <section className="flex flex-col gap-4">
            {/* Marketplace de agentes */}
            <Panel>
              <PanelHeader
                title="Marketplace"
                description="Agentes pre-entrenados listos para tu workspace."
              />
              {market.length === 0 ? (
                <EmptyState
                  compact
                  icon={Robot}
                  title="Sin agentes disponibles"
                  body="Cuando el catálogo tenga agentes publicados van a aparecer acá."
                />
              ) : (
                <ul className="divide-y divide-border-soft">
                  {market.map((m) => {
                    const installed = installs.some((i) => i.slug === m.slug);
                    return (
                      <li key={m.id} className="px-4 py-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-[13px] font-medium text-text">{m.name}</p>
                          {m.featured && <Badge tone="warn">destacado</Badge>}
                          <Badge>{m.category}</Badge>
                        </div>
                        <p className="mt-1 text-xs leading-relaxed text-muted">{m.description}</p>
                        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                          <span className="text-xs text-faint tabular-nums">
                            ★ {m.rating} · {fmtNum(m.installs)} instalaciones
                          </span>
                          {installed ? (
                            <Badge tone="ok">Instalado</Badge>
                          ) : (
                            <Button
                              size="sm"
                              variant="secondary"
                              leadingIcon={DownloadSimple}
                              loading={busy === `i-${m.slug}`}
                              onClick={() => void install(m.slug)}
                            >
                              Instalar
                            </Button>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </Panel>

            {/* Instalados: uso real y baja */}
            <Panel>
              <PanelHeader
                title={`Tus agentes (${installs.length})`}
                description="Instalados en este workspace y cuántas veces se usaron."
              />
              {installs.length === 0 ? (
                <EmptyState
                  compact
                  icon={Robot}
                  title="Sin agentes instalados"
                  body="Instala un agente del marketplace para empezar a usarlo."
                />
              ) : (
                <ul className="divide-y divide-border-soft">
                  {installs.map((i) => (
                    <li key={i.id} className="flex items-center justify-between gap-3 px-4 py-3">
                      <div className="min-w-0">
                        <p className="truncate text-[13px] font-medium text-text">{i.agent_name}</p>
                        <p className="mt-0.5 text-xs text-faint">
                          {i.category} · {fmtNum(i.usage_count)} usos · {timeAgo(i.installed_at)}
                        </p>
                      </div>
                      <Button
                        size="sm"
                        variant="ghost"
                        leadingIcon={Trash}
                        loading={busy === `rm-${i.id}`}
                        onClick={() => void remove(i.id)}
                      >
                        Desinstalar
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </section>
        </div>
      )}
    </div>
  );
}
