import { Play, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Badge,
  Button,
  CodeBlock,
  EmptyState,
  ErrorInline,
  Field,
  InfoInline,
  PageHeader,
  Panel,
  PanelHeader,
  Select,
  Textarea,
} from "../components/ui";

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

function isJson(value: string): boolean {
  if (!value) return false;
  try {
    JSON.parse(value);
    return true;
  } catch {
    return false;
  }
}

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
  const [showCurl, setShowCurl] = useState(false);

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

  const path = endpoint.path(slug);
  const healthyDeployments = deployments.filter((d) => d.status === "healthy");
  const curl = `curl -X ${endpoint.method} ${path} \\
  -H "Authorization: Bearer $ZENT_TOKEN" \\
  -H "X-Organization-Id: $ZENT_ORG" \\
  -H "Content-Type: application/json"${
    endpoint.body
      ? ` \\
  -d '${body}'`
      : ""
  }`;
  const statusOk = status !== "" && Number(status) < 400;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="API Console" subtitle="Ejecuta las APIs en vivo con tu sesión y tus deployments." />
      <ErrorInline message={error} />
      <InfoInline>
        Las llamadas se autentican con el token de tu sesión del portal. La API key completa solo se
        muestra al crearla, así que no se reenvía desde acá.
      </InfoInline>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 lg:items-start">
        <Panel>
          <PanelHeader
            title="Solicitud"
            description="Elige el endpoint, la identidad y el cuerpo que enviaremos."
            actions={
              <>
                <Badge tone={endpoint.method === "GET" ? "info" : "accent"}>{endpoint.method}</Badge>
                <span className="mono text-xs text-muted">{path}</span>
              </>
            }
          />
          <div className="panel-body flex flex-col gap-3">
            <Field label="Endpoint" hint="Cada endpoint usa el mismo Bearer que tu sesión.">
              <Select
                value={endpoint.key}
                onChange={(e) => selectEndpoint(ENDPOINTS.find((x) => x.key === e.target.value) ?? ENDPOINTS[0])}
              >
                {ENDPOINTS.map((e) => (
                  <option key={e.key} value={e.key}>
                    {e.method} · {e.label}
                  </option>
                ))}
              </Select>
            </Field>

            <Field
              label="API key"
              hint="La clave completa no se vuelve a mostrar: el portal firma con tu sesión."
            >
              <Select value={keyId} onChange={(e) => setKeyId(e.target.value)} placeholder="Elegí una API key…">
                {keys.map((k) => (
                  <option key={k.id} value={k.id}>
                    {k.name} · {k.prefix}
                  </option>
                ))}
              </Select>
            </Field>

            {endpoint.needsSlug && (
              <Field label="Deployment">
                <Select value={slug} onChange={(e) => setSlug(e.target.value)} placeholder="Elegí un deployment…">
                  {healthyDeployments.map((d) => (
                    <option key={d.id} value={d.slug}>
                      {d.slug}
                    </option>
                  ))}
                </Select>
              </Field>
            )}

            {endpoint.needsSlug && healthyDeployments.length === 0 && (
              <p className="flex items-start gap-2 text-xs leading-relaxed text-warn">
                <WarningCircle size={14} className="mt-px shrink-0" aria-hidden />
                No hay deployments healthy. Despliega un agente o usa un endpoint que no dependa de uno.
              </p>
            )}

            <Field
              label="Cuerpo (JSON)"
              hint={endpoint.body ? "Editable para esta llamada." : "Este endpoint no lleva cuerpo."}
            >
              <Textarea
                className="min-h-32 font-mono text-xs"
                value={body}
                onChange={(e) => setBody(e.target.value)}
                disabled={!endpoint.body}
                spellCheck={false}
              />
            </Field>

            <div className="flex flex-wrap items-center gap-2">
              <Button variant="primary" loading={busy} leadingIcon={Play} onClick={() => void execute()}>
                Ejecutar
              </Button>
              <Button
                variant="ghost"
                size="sm"
                aria-expanded={showCurl}
                onClick={() => setShowCurl((v) => !v)}
              >
                {showCurl ? "Ocultar cURL" : "Ver como cURL"}
              </Button>
            </div>

            {showCurl && <CodeBlock code={curl} language="bash" filename="request.sh" maxHeight={220} />}
          </div>
        </Panel>

        <Panel>
          <PanelHeader
            title="Respuesta"
            actions={
              status !== "" ? (
                <>
                  <Badge tone={statusOk ? "ok" : "danger"} dot>
                    HTTP {status}
                  </Badge>
                  {latency != null && <span className="mono text-xs text-muted">{latency} ms</span>}
                </>
              ) : undefined
            }
          />
          <div className="panel-body">
            {response ? (
              <CodeBlock
                code={response}
                language={isJson(response) ? "json" : "text"}
                filename="response"
                maxHeight={520}
              />
            ) : (
              <EmptyState
                compact
                icon={Play}
                title="Sin respuesta todavía"
                body="Ejecuta una llamada para ver el cuerpo y su latencia."
              />
            )}
          </div>
        </Panel>
      </div>
    </div>
  );
}
