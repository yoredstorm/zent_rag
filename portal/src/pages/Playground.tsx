import { Play } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorInline, PageHeader } from "../components/ui";

type ApiKey = { id: string; name: string; prefix: string; is_active: boolean };
type Deployment = { id: string; slug: string; status: string };

const ENDPOINTS = [
  {
    key: "deployment_query",
    label: "Deployment query",
    method: "POST",
    path: (slug: string) => `/api/v1/deployments/${slug}/query`,
    body: '{"input": "¿Cuánto stock queda del producto ABC?", "user": {"id": "erp-001"}}',
    needsSlug: true,
  },
  {
    key: "rag_query",
    label: "RAG query",
    method: "POST",
    path: () => "/api/v1/rag/query",
    body: '{"question": "¿Cuánto stock queda del producto ABC?"}',
    needsSlug: false,
  },
  {
    key: "federated",
    label: "Federated search",
    method: "POST",
    path: () => "/api/v1/rag/federated",
    body: '{"query": "stock del producto ABC", "top_k": 5}',
    needsSlug: false,
  },
  {
    key: "agents",
    label: "Listar agentes",
    method: "GET",
    path: () => "/api/v1/agents",
    body: null,
    needsSlug: false,
  },
  {
    key: "knowledge_bases",
    label: "Listar KBs",
    method: "GET",
    path: () => "/api/v1/knowledge-bases",
    body: null,
    needsSlug: false,
  },
];

export default function PlaygroundPage() {
  const { session } = useAuth();
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [endpoint, setEndpoint] = useState(ENDPOINTS[0]);
  const [keyId, setKeyId] = useState("");
  const [slug, setSlug] = useState("");
  const [body, setBody] = useState(ENDPOINTS[0].body ?? "{}");
  const [response, setResponse] = useState("");
  const [status, setStatus] = useState("");
  const [latency, setLatency] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    void Promise.all([
      api<{ keys: ApiKey[] }>("/api/v1/organizations/api-keys", { token: session.token, organizationId: session.organizationId }),
      api<{ deployments: Deployment[] }>("/api/v1/deployments", { token: session.token, organizationId: session.organizationId }),
    ])
      .then(([k, d]) => {
        setKeys(k.keys.filter((x) => x.is_active));
        setDeployments(d.deployments || []);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Error"));
  }, [session]);

  async function execute() {
    if (!session) return;
    setBusy(true);
    setError("");
    setResponse("");
    setStatus("");
    setLatency(null);
    const key = keys.find((k) => k.id === keyId);
    if (!key) {
      setError("Selecciona una API key activa.");
      setBusy(false);
      return;
    }
    // La clave completa no se re-expone; usamos un token de demo si es la demo dev.
    setError("Uso el token de la sesión del portal como Bearer (la API key completa solo se muestra al crearla).");
    const started = performance.now();
    try {
      const resp = await fetch(endpoint.path(slug), {
        method: endpoint.method,
        headers: {
          Authorization: `Bearer ${session.token}`,
          "X-Organization-Id": session.organizationId,
          "Content-Type": "application/json",
          "Idempotency-Key": `pg-${crypto.randomUUID()}`,
        },
        body: endpoint.body ? body : undefined,
      });
      setStatus(`${resp.status}`);
      setLatency(Math.round(performance.now() - started));
      const text = await resp.text();
      try {
        setResponse(JSON.stringify(JSON.parse(text), null, 2));
      } catch {
        setResponse(text);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  function selectEndpoint(e: (typeof ENDPOINTS)[number]) {
    setEndpoint(e);
    setBody(e.body ?? "{}");
    setStatus("");
    setResponse("");
  }

  return (
    <div>
      <PageHeader title="API Console" subtitle="Ejecuta las APIs en vivo con tu sesión y tus deployments." />
      <ErrorInline message={error} />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="space-y-3">
          <div className="panel grid grid-cols-1 gap-2 p-4">
            <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={endpoint.key} onChange={(e) => selectEndpoint(ENDPOINTS.find((x) => x.key === e.target.value) ?? ENDPOINTS[0])}>
              {ENDPOINTS.map((e) => (
                <option key={e.key} value={e.key}>{e.method} · {e.label}</option>
              ))}
            </select>
            <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={keyId} onChange={(e) => setKeyId(e.target.value)}>
              <option value="">API key (demo de sesión)…</option>
              {keys.map((k) => (
                <option key={k.id} value={k.id}>{k.name} · {k.prefix}</option>
              ))}
            </select>
            {endpoint.needsSlug && (
              <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={slug} onChange={(e) => setSlug(e.target.value)}>
                <option value="">Deployment…</option>
                {deployments.filter((d) => d.status === "healthy").map((d) => (
                  <option key={d.id} value={d.slug}>{d.slug}</option>
                ))}
              </select>
            )}
            <textarea
              className="min-h-32 rounded-md border border-border bg-soft px-3 py-2 font-mono text-xs text-text"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              disabled={!endpoint.body}
            />
            <button type="button" className="btn btn-primary min-h-9 text-xs" disabled={busy} onClick={() => void execute()}>
              <Play size={13} aria-hidden /> Ejecutar
            </button>
          </div>
        </div>
        <div className="panel p-4">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-text">Respuesta</h3>
            {status && (
              <span className={`badge ${Number(status) < 400 ? "badge-ok" : "badge-danger"}`}>
                {status} {latency != null ? `· ${latency}ms` : ""}
              </span>
            )}
          </div>
          <pre className="max-h-[480px] min-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-soft p-3 text-xs leading-relaxed text-text">
            {response || "// ejecuta una llamada para ver la respuesta"}
          </pre>
        </div>
      </div>
    </div>
  );
}