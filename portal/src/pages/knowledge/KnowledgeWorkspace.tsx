import { ChatCircleText, FileText, MagnifyingGlass, Notebook } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import PdfViewer from "../../components/PdfViewer";
import { ErrorInline, Spinner, StatusBadge } from "../../components/ui";

type Corpus = {
  id: string;
  name: string;
  slug: string;
  description: string;
  status: string;
  created_at: string;
};

type Source = {
  id: string;
  name: string;
  type: string;
  status: string;
  workspace_id: string | null;
  object_key: string | null;
};

type Citation = {
  document_name: string;
  document_id: string | null;
  page: number | null;
  section_path: string[];
  locator: string;
  relevance: number;
  excerpt: string;
};

type GroundedResponse = {
  answer: string;
  confidence: number;
  claims: { text: string; status: string; confidence: number }[];
  citations: Citation[];
  missing_information: string[];
  conflicts: string[];
  sources_used: string[];
};

type ViewerState =
  | {
      mode: "pdf";
      source: Source;
      fileUrl: string;
      highlight: { page: number; bbox: { x0: number; y0: number; x1: number; y1: number } | null; excerpt: string };
    }
  | {
      mode: "list";
      source: Source;
      documents: { id: string; title: string; page_count: number }[];
    };

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
};

/** Marcas [N] → nodos clickeables que abren el Viewer y resaltan la cita. */
function renderAnswer(content: string, citations: Citation[], onCite: (c: Citation) => void) {
  const parts = content.split(/(\[\d+\])/g);
  return parts.map((part, index) => {
    const match = /\[(\d+)\]/.exec(part);
    if (!match) return <span key={index}>{part}</span>;
    const citation = citations[Number(match[1]) - 1];
    if (!citation) return <span key={index}>{part}</span>;
    return (
      <button
        key={index}
        title={citation.locator}
        onClick={() => onCite(citation)}
        className="mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded bg-indigo-100 px-1 text-[10px] font-semibold text-indigo-700 hover:bg-indigo-200"
      >
        {match[1]}
      </button>
    );
  });
}

export default function KnowledgeWorkspacePage() {
  const { corpusId = "" } = useParams();
  const { session } = useAuth();
  const [corpus, setCorpus] = useState<Corpus | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [asking, setAsking] = useState(false);
  const [viewer, setViewer] = useState<ViewerState | null>(null);
  const [highlighted, setHighlighted] = useState<Citation | null>(null);
  const [suggestions, setSuggestions] = useState<{ text: string; intent: string; basis: string }[]>([]);

  const load = useCallback(() => {
    if (!session) return;
    setLoading(true);
    api<{ corpus: Corpus; sources: Source[] }>(`/api/v1/knowledge/workspaces/${corpusId}`, {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => {
        setCorpus(data.corpus);
        setSources(data.sources ?? []);
        setSelected(new Set((data.sources ?? []).map((s) => s.id)));
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoading(false));
  }, [session, corpusId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!session || !corpusId) return;
    api<{ suggestions: { text: string; intent: string; basis: string }[] }>(
      `/api/v1/knowledge/workspaces/${corpusId}/suggestions`,
      { token: session.token, organizationId: session.organizationId },
    )
      .then((data) => setSuggestions(data.suggestions ?? []))
      .catch(() => setSuggestions([]));
  }, [session, corpusId]);

  const filtered = useMemo(() => {
    return sources.filter((s) => {
      const q = search.trim().toLowerCase();
      const matchesQuery = !q || s.name.toLowerCase().includes(q);
      const matchesType = typeFilter === "all" || s.type === typeFilter;
      return matchesQuery && matchesType;
    });
  }, [sources, search, typeFilter]);

  const ask = () => {
    const question = input.trim();
    if (!question || !session) return;
    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setInput("");
    setAsking(true);
    api<{ grounded: GroundedResponse }>(`/api/v1/knowledge/workspaces/${corpusId}/chat`, {
      token: session.token,
      organizationId: session.organizationId,
      method: "POST",
      body: JSON.stringify({ query: question, source_ids: Array.from(selected) }),
    })
      .then((data) => {
        const rounded = { ...data.grounded };
        rounded.confidence = Math.round(rounded.confidence * 100);
        setMessages((prev) => [...prev, {
          role: "assistant",
          content: data.grounded.answer,
          citations: data.grounded.citations,
        }]);
      })
      .catch((err) =>
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content:
              err instanceof Error && /503/.test(err.message)
                ? "Knowledge V2 no está activo en este entorno. Activa RAG_KNOWLEDGE_V2_ENABLED + RAG_KNOWLEDGE_V2_PROMOTE para usar el chat grounded."
                : (err instanceof Error ? err.message : "Error al consultar"),
          },
        ]),
      )
      .finally(() => setAsking(false));
  };

  const openSource = (
    source: Source,
    citation?: Citation | null,
  ) => {
    if (!session) return;
    const isPdf =
      (source.object_key ?? source.name).toLowerCase().endsWith(".pdf");
    if (isPdf) {
      const page = citation?.page ?? 1;
      const base = {
        mode: "pdf" as const,
        source,
        fileUrl: `/api/v1/knowledge/workspaces/${corpusId}/sources/${source.id}/file`,
        highlight: {
          page,
          bbox: null as {
            x0: number;
            y0: number;
            x1: number;
            y1: number;
          } | null,
          excerpt: citation?.excerpt ?? "",
        },
      };
      setViewer(base);
      // Resolver bbox (anchor → página) con locate (heurístico + LLM si flag on)
      api<{
        page: number | null;
        bbox: { x0: number; y0: number; x1: number; y1: number } | null;
        excerpt: string;
        method: string;
      }>(`/api/v1/knowledge/workspaces/${corpusId}/sources/${source.id}/locate`, {
        token: session.token,
        organizationId: session.organizationId,
        method: "POST",
        body: JSON.stringify({
          query: citation?.excerpt || citation?.locator || source.name,
          page_hint: citation?.page ?? null,
        }),
      })
        .then((located) => {
          if (located.page == null) return;
          setViewer((prev) =>
            prev && prev.mode === "pdf"
              ? {
                  ...prev,
                  highlight: {
                    page: located.page ?? page,
                    bbox: located.bbox ?? null,
                    excerpt: located.excerpt || prev.highlight.excerpt,
                  },
                }
              : prev,
          );
        })
        .catch(() => undefined);
      return;
    }

    api<{ documents: { id: string; title: string; page_count: number }[] }>(
      `/api/v1/knowledge/workspaces/${corpusId}/sources/${source.id}/documents`,
      { token: session.token, organizationId: session.organizationId },
    )
      .then((data) =>
        setViewer({ mode: "list", source, documents: data.documents ?? [] }),
      )
      .catch(() => setViewer({ mode: "list", source, documents: [] }));
  };

  const cite = (citation: Citation) => {
    setHighlighted(citation);
    const match =
      sources.find((s) => s.id === citation.document_id) ?? sources[0];
    if (match) {
      openSource(match, citation);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 px-6 py-10 text-zinc-500">
        <Spinner size={16} /> Cargando workspace…
      </div>
    );
  }
  if (error || !corpus) {
    return (
      <div className="px-6 py-10">
        <ErrorInline message={error || "Workspace no encontrado"} />
        <Link className="mt-3 inline-block text-sm text-indigo-600" to="/knowledge/workspaces">
          ← Volver
        </Link>
      </div>
    );
  }

  const types = Array.from(new Set(sources.map((s) => s.type)));

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-zinc-200 bg-white px-6 py-4">
        <div className="flex items-center justify-between gap-4">
          <div>
            <Link
              to="/knowledge/workspaces"
              className="text-xs font-medium text-zinc-400 hover:text-indigo-600"
            >
              ← Workspaces
            </Link>
            <div className="mt-0.5 flex items-center gap-2">
              <h1 className="text-lg font-semibold text-zinc-900">{corpus.name}</h1>
              <StatusBadge status={corpus.status} />
            </div>
            <p className="text-xs text-zinc-500">
              {sources.length === 0
                ? "Añade fuentes y vuelve aquí: tu pregunta se responde con evidencia."
                : `${sources.length} sources · pregunta lo que necesites con citas verificables.`}
            </p>
          </div>
          <div className="flex items-center gap-3 text-xs text-zinc-500">
            <button
              onClick={() => setViewer(null)}
              className="rounded-lg border border-zinc-200 px-2.5 py-1 hover:bg-zinc-50"
            >
              Chat
            </button>
            <button
              onClick={() => setViewer(null)}
              className="rounded-lg border border-zinc-200 px-2.5 py-1 hover:bg-zinc-50"
            >
              Fuentes
            </button>
            <button className="rounded-lg border border-zinc-200 px-2.5 py-1 hover:bg-zinc-50">
              Studio
            </button>
          </div>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[260px_1fr_280px]">
        {/* LEFT — Sources */}
        <aside className="flex min-h-0 flex-col border-r border-zinc-200 bg-zinc-50">
          <div className="border-b border-zinc-200 p-3">
            <div className="relative">
              <MagnifyingGlass size={14} className="absolute left-2.5 top-2.5 text-zinc-400" />
              <input
                className="w-full rounded-lg border border-zinc-200 bg-white py-1.5 pl-8 pr-2 text-sm focus:border-indigo-400 focus:outline-none"
                placeholder="Buscar fuente"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              <TypeChip active={typeFilter === "all"} label="Todos" onClick={() => setTypeFilter("all")} />
              {types.map((type) => (
                <TypeChip
                  key={type}
                  active={typeFilter === type}
                  label={type}
                  onClick={() => setTypeFilter(type)}
                />
              ))}
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {filtered.length === 0 && (
              <div className="p-3">
                {sources.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-zinc-300 p-3 text-[11px] leading-relaxed text-zinc-500">
                    <p className="font-medium text-zinc-600">Este workspace no tiene fuentes.</p>
                    <ol className="mt-1.5 list-decimal space-y-1 pl-4">
                      <li>Sube un PDF, DOCX o texto en <span className="font-medium text-indigo-600">Knowledge → Fuentes</span>.</li>
                      <li>Reprocesa la fuente (re-sync) para indexar su estructura.</li>
                      <li>Vuelve aquí: aparecerá y podrás preguntarle.</li>
                    </ol>
                  </div>
                ) : (
                  <p className="text-xs text-zinc-400">
                    Ninguna fuente coincide con la búsqueda o el filtro.
                  </p>
                )}
              </div>
            )}
            {filtered.map((source) => (
              <div
                key={source.id}
                className="mb-1 flex items-start gap-2 rounded-lg px-2 py-2 hover:bg-white"
              >
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={selected.has(source.id)}
                  onChange={() => {
                    setSelected((prev) => {
                      const next = new Set(prev);
                      if (next.has(source.id)) next.delete(source.id);
                      else next.add(source.id);
                      return next;
                    });
                  }}
                />
                <div className="min-w-0 flex-1">
                  <button
                    onClick={() => openSource(source)}
                    className="block w-full truncate text-left text-sm font-medium text-zinc-800 hover:text-indigo-700"
                  >
                    {source.name}
                  </button>
                  <div className="flex items-center gap-2 text-[11px] text-zinc-500">
                    <span className="capitalize">{source.type}</span>
                    <StatusBadge status={source.status} />
                  </div>
                </div>
              </div>
            ))}
          </div>
          <div className="border-t border-zinc-200 p-3 text-[11px] text-zinc-500">
            {selected.size} de {sources.length} fuentes en scope
          </div>
        </aside>

        {/* CENTER — Chat (o Viewer) */}
        <main className="flex min-h-0 flex-col bg-white">
          {viewer === null ? (
            <ChatPane
              messages={messages}
              asking={asking}
              input={input}
              setInput={setInput}
              ask={ask}
              onCite={cite}
              suggestions={suggestions}
              canAsk={sources.length > 0 && selected.size > 0}
            />
          ) : viewer.mode === "pdf" ? (
            <PdfViewer
              fileUrl={viewer.fileUrl}
              token={session?.token}
              highlight={viewer.highlight}
            />
          ) : (
            <ViewerPane
              source={viewer.source}
              documents={viewer.documents}
              highlighted={highlighted}
              onBack={() => setViewer(null)}
            />
          )}
        </main>

        {/* RIGHT — Studio */}
        <aside className="flex min-h-0 flex-col border-l border-zinc-200 bg-zinc-50">
          <StudioPane corpusId={corpusId} />
        </aside>
      </div>
    </div>
  );
}

function TypeChip({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full px-2 py-0.5 text-[11px] font-medium capitalize ${
        active ? "bg-indigo-600 text-white" : "bg-white text-zinc-600 hover:bg-zinc-100"
      }`}
    >
      {label}
    </button>
  );
}

function ChatPane({
  messages,
  asking,
  input,
  setInput,
  ask,
  onCite,
  suggestions,
  canAsk,
}: {
  messages: ChatMessage[];
  asking: boolean;
  input: string;
  setInput: (v: string) => void;
  ask: () => void;
  onCite: (c: Citation) => void;
  suggestions: { text: string; intent: string; basis: string }[];
  canAsk: boolean;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages, asking]);

  return (
    <div className="flex min-h-0 flex-col">
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
        {messages.length === 0 && (
          <div className="pt-10 text-center">
            <Notebook size={28} className="mx-auto text-zinc-300" />
            <p className="mt-2 text-sm font-medium text-zinc-600">
              Pregunta a este workspace
            </p>
            <p className="text-xs text-zinc-400">
              Respuestas con citas verificables sobre tus fuentes.
            </p>
            {suggestions.length > 0 ? (
              <div className="mx-auto mt-5 flex max-w-md flex-col gap-2">
                {suggestions.map((suggestion) => (
                  <button
                    key={suggestion.text}
                    onClick={() => setInput(suggestion.text)}
                    className="rounded-lg border border-zinc-200 px-3 py-2 text-left text-xs text-zinc-600 hover:border-indigo-300 hover:text-indigo-700"
                  >
                    {suggestion.text}
                  </button>
                ))}
              </div>
            ) : (
              <p className="mx-auto mt-5 max-w-sm text-[11px] text-zinc-400">
                Sin fuentes o conocimiento estructurado aún en este corpus — las
                sugerencias aparecen cuando haya datos indexados.
              </p>
            )}
          </div>
        )}
        {messages.map((message, index) => (
          <div
            key={index}
            className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[85%] rounded-xl px-4 py-2.5 text-sm leading-relaxed ${
                message.role === "user"
                  ? "bg-indigo-600 text-white"
                  : "border border-zinc-200 bg-zinc-50 text-zinc-800"
              }`}
            >
              {message.role === "assistant"
                ? renderAnswer(message.content, message.citations ?? [], onCite)
                : message.content}
              {message.role === "assistant" && message.citations && message.citations.length > 0 && (
                <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-zinc-500">
                  <span>Sources used: {message.citations.length}</span>
                  <HoverCitation caption={message.citations[0].locator} excerpt={message.citations[0].excerpt} />
                </div>
              )}
            </div>
          </div>
        ))}
        {asking && (
          <div className="flex items-center gap-2 text-xs text-zinc-400">
            <Spinner size={12} /> Buscando evidencia y verificando…
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="border-t border-zinc-200 p-3">
        <div className="flex items-end gap-2">
          <textarea
            rows={1}
            className="min-h-[40px] flex-1 resize-none rounded-lg border border-zinc-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
            placeholder="Haz una pregunta sobre el corpus…"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                ask();
              }
            }}
          />
          <button
            disabled={!input.trim() || asking || !canAsk}
            onClick={ask}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            Enviar
          </button>
        </div>
      </div>
    </div>
  );
}

function HoverCitation({ caption, excerpt }: { caption: string; excerpt: string }) {
  const [hover, setHover] = useState(false);
  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <span className="cursor-help text-indigo-600 underline decoration-dotted">{caption}</span>
      {hover && (
        <span className="absolute bottom-full left-0 z-10 mb-1 w-64 rounded-md border border-zinc-200 bg-white p-2 text-[11px] text-zinc-600 shadow-lg">
          {excerpt.slice(0, 200)}…
        </span>
      )}
    </span>
  );
}

function ViewerPane({
  source,
  documents,
  highlighted,
  onBack,
}: {
  source: Source;
  documents: { id: string; title: string; page_count: number }[];
  highlighted: Citation | null;
  onBack: () => void;
}) {
  return (
    <div className="flex min-h-0 flex-col">
      <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <button
            onClick={onBack}
            className="text-xs font-medium text-indigo-600 hover:text-indigo-500"
          >
            ← Chat
          </button>
          <FileText size={15} className="text-zinc-400" />
          <h2 className="text-sm font-semibold text-zinc-800">{source.name}</h2>
        </div>
        <span className="text-[11px] text-zinc-400">Source Viewer</span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        {highlighted && (
          <div className="mb-4 rounded-lg border border-indigo-200 bg-indigo-50 p-3 text-sm text-indigo-800">
            <p className="text-xs font-semibold uppercase tracking-wide text-indigo-500">
              Evidencia resaltada — {highlighted.locator}
            </p>
            <p className="mt-1">{highlighted.excerpt}</p>
          </div>
        )}
        {documents.length === 0 ? (
          <p className="text-sm text-zinc-400">
            Sin documentos estructurados indexados para esta fuente todavía.
          </p>
        ) : (
          <ul className="space-y-2">
            {documents.map((doc) => (
              <li
                key={doc.id}
                className="rounded-lg border border-zinc-200 p-3 text-sm text-zinc-700"
              >
                <span className="font-medium">{doc.title}</span>
                <span className="ml-2 text-xs text-zinc-400">
                  {doc.page_count} páginas
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

type StudioItem = {
  text?: string;
  question?: string;
  date?: string;
  title?: string;
  document_id?: string;
  page?: number | null;
  kind?: string;
  source?: string;
};

type StudioArtifactPayload = {
  artifact: string;
  items: StudioItem[];
  provenance: string;
};

type StudioPayload = { artifacts: StudioArtifactPayload[] };

function StudioPane({ corpusId }: { corpusId: string }) {
  const { session } = useAuth();
  const [loading, setLoading] = useState<string | null>(null);
  const [result, setResult] = useState<StudioPayload | null>(null);
  const [error, setError] = useState("");

  const run = (artifact: string) => {
    if (!session) return;
    setLoading(artifact);
    setError("");
    api<StudioPayload>(`/api/v1/knowledge/workspaces/${corpusId}/studio`, {
      token: session.token,
      organizationId: session.organizationId,
      method: "POST",
      body: JSON.stringify({ artifact }),
    })
      .then((data) => setResult(data))
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoading(null));
  };

  const artifacts = [
    { id: "executive_summary", label: "Executive Summary" },
    { id: "key_facts", label: "Key Facts" },
    { id: "faq", label: "FAQ" },
    { id: "timeline", label: "Timeline" },
    { id: "risks", label: "Risk Summary" },
  ];
  const comingSoon = ["Comparison", "Knowledge Map", "Briefing"];

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-4">
      <div className="flex items-center gap-2">
        <ChatCircleText size={16} className="text-indigo-600" />
        <h3 className="text-sm font-semibold text-zinc-800">Knowledge Studio</h3>
      </div>
      <p className="mt-1 text-[11px] leading-relaxed text-zinc-500">
        Artefactos generados a partir de datos reales del corpus. Los candidatos
        son INFERRED hasta revisión humana.
      </p>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {artifacts.map((artifact) => (
          <button
            key={artifact.id}
            onClick={() => run(artifact.id)}
            disabled={loading !== null}
            className={`rounded-full border px-2.5 py-1 text-[11px] font-medium transition ${
              loading === artifact.id
                ? "border-indigo-300 bg-indigo-50 text-indigo-700"
                : "border-zinc-300 bg-white text-zinc-700 hover:border-indigo-300 hover:text-indigo-700"
            }`}
          >
            {loading === artifact.id ? "Generando…" : artifact.label}
          </button>
        ))}
      </div>

      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}

      {result && (
        <div className="mt-4 space-y-4">
          {result.artifacts.map((artifact) => (
            <div key={artifact.artifact}>
              <p className="text-[10px] font-semibold uppercase tracking-wide text-zinc-400">
                {artifact.artifact.replace(/_/g, " ")} · {artifact.provenance}
              </p>
              {/* Timeline: agrupado por fecha */}
              {artifact.artifact === "timeline" && artifact.items.length > 0 ? (
                <ol className="mt-1.5 space-y-1">
                  {artifact.items.map((item, index) => (
                    <li key={index} className="flex gap-2 text-xs text-zinc-600">
                      <span className="shrink-0 font-medium text-indigo-600">{item.date}</span>
                      <span className="truncate">{item.text}</span>
                    </li>
                  ))}
                </ol>
              ) : artifact.items.length > 0 ? (
                <ul className="mt-1.5 space-y-1.5">
                  {artifact.items.slice(0, 12).map((item, index) => (
                    <li key={index} className="rounded-md border border-zinc-200 bg-white p-2 text-[11px] text-zinc-600">
                      {item.question ?? item.text ?? item.title}
                      {(item.page != null || item.kind) && (
                        <span className="mt-0.5 block text-[10px] text-zinc-400">
                          {item.kind}
                          {item.page != null ? ` · pág. ${item.page}` : ""} · {item.source}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-1 text-[11px] text-zinc-400">
                  Sin datos para este artefacto en el corpus todavía.
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="mt-4 border-t border-zinc-200 pt-3">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-zinc-400">
          Próximamente
        </p>
        <ul className="mt-1.5 space-y-1">
          {comingSoon.map((artifact) => (
            <li key={artifact} className="text-[11px] text-zinc-400">
              {artifact}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}