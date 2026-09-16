import { ListBullets, Play, Terminal } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Button,
  CodeBlock,
  DataTable,
  EmptyState,
  ErrorInline,
  Field,
  KeyValue,
  PageHeader,
  Panel,
  PasswordInput,
  Select,
  SkeletonBlock,
  StatusBadge,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
  type Column,
} from "../components/ui";
import { fmtNum } from "../lib/format";

type ApiLog = {
  id: string;
  deployment_id: string | null;
  agent_id: string | null;
  request_id: string;
  endpoint: string;
  method: string;
  status: number;
  latency_ms: number | null;
  tokens: number;
  cost: number | null;
  api_key_id: string | null;
  error: string | null;
  created_at: string;
};

type Deployment = {
  id: string;
  slug: string;
  status: string;
  endpoint: string | null;
};

type SnippetEntry = { label: string; language: string; code: (slug: string) => string };

const SNIPPETS: Record<string, SnippetEntry> = {
  curl: {
    label: "cURL",
    language: "bash",
    code: (slug: string) => `curl -X POST https://api.zent.example/api/v1/deployments/${slug}/query \\
  -H "Authorization: Bearer zent_sk_live_..." \\
  -H "Content-Type: application/json" \\
  -d '{"input": "¿Cuánto stock queda del producto ABC?"}'`,
  },
  python: {
    label: "Python",
    language: "python",
    code: (slug: string) => `import requests

resp = requests.post(
    f"https://api.zent.example/api/v1/deployments/${slug}/query",
    headers={"Authorization": "Bearer zent_sk_live_..."},
    json={"input": "¿Cuánto stock queda del producto ABC?"},
)
print(resp.json()["answer"])`,
  },
  javascript: {
    label: "JavaScript",
    language: "javascript",
    code: (slug: string) => `const resp = await fetch(
  "https://api.zent.example/api/v1/deployments/${slug}/query",
  {
    method: "POST",
    headers: {
      Authorization: "Bearer zent_sk_live_...",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ input: "¿Cuánto stock queda del producto ABC?" }),
  }
);
console.log(await resp.json());`,
  },
  csharp: {
    label: "C#",
    language: "csharp",
    code: (slug: string) => `using var client = new HttpClient();
client.DefaultRequestHeaders.Authorization =
    new AuthenticationHeaderValue("Bearer", "zent_sk_live_...");
var payload = new { input = "¿Cuánto stock queda del producto ABC?" };
var resp = await client.PostAsJsonAsync(
    "https://api.zent.example/api/v1/deployments/${slug}/query", payload);
Console.WriteLine(await resp.Content.ReadAsStringAsync());`,
  },
  java: {
    label: "Java",
    language: "java",
    code: (slug: string) => `HttpRequest req = HttpRequest.newBuilder()
    .uri(URI.create("https://api.zent.example/api/v1/deployments/${slug}/query"))
    .header("Authorization", "Bearer zent_sk_live_...")
    .header("Content-Type", "application/json")
    .POST(BodyPublishers.ofString(
        "{\\"input\\":\\"¿Cuánto stock queda del producto ABC?\\"}"))
    .build();
var resp = HttpClient.newHttpClient().send(req, BodyHandlers.ofString());
System.out.println(resp.body());`,
  },
  php: {
    label: "PHP",
    language: "php",
    code: (slug: string) => `<?php
$resp = file_get_contents(
    "https://api.zent.example/api/v1/deployments/${slug}/query",
    false,
    stream_context_create(["http" => [
        "method" => "POST",
        "header" => "Authorization: Bearer zent_sk_live_...\\r\\nContent-Type: application/json",
        "content" => json_encode(["input" => "¿Cuánto stock queda del producto ABC?"]),
    ]])
);
echo $resp;`,
  },
};

const LOG_COLUMNS: Column<ApiLog>[] = [
  {
    key: "request",
    header: "Request",
    render: (l) => <span className="mono text-xs text-text">{l.request_id.slice(0, 8)}</span>,
  },
  {
    key: "endpoint",
    header: "Endpoint",
    render: (l) => (
      <span className="mono text-xs text-muted">
        <span className="text-faint">{l.method}</span> {l.endpoint}
      </span>
    ),
  },
  {
    key: "status",
    header: "Status",
    width: "1%",
    render: (l) => (
      <StatusBadge status={l.status < 400 ? "healthy" : "failed"} label={String(l.status)} />
    ),
  },
  {
    key: "latency",
    header: "Latencia",
    align: "right",
    hideBelow: "md",
    render: (l) => (
      <span className="mono text-xs text-muted">{l.latency_ms != null ? `${l.latency_ms.toFixed(0)} ms` : "—"}</span>
    ),
  },
  {
    key: "tokens",
    header: "Tokens",
    align: "right",
    hideBelow: "md",
    render: (l) => <span className="mono text-xs text-muted">{fmtNum(l.tokens)}</span>,
  },
  {
    key: "cost",
    header: "Costo",
    align: "right",
    hideBelow: "lg",
    render: (l) => <span className="mono text-xs text-muted">{l.cost != null ? `$${l.cost.toFixed(5)}` : "—"}</span>,
  },
  {
    key: "key",
    header: "Key",
    hideBelow: "lg",
    render: (l) => <span className="mono text-xs text-faint">{l.api_key_id ? l.api_key_id.slice(0, 8) : "—"}</span>,
  },
  {
    key: "error",
    header: "Error",
    hideBelow: "xl",
    render: (l) => (
      <span className="block max-w-[16rem] truncate text-xs text-danger" title={l.error ?? undefined}>
        {l.error || "—"}
      </span>
    ),
  },
  {
    key: "created",
    header: "Fecha",
    hideBelow: "md",
    render: (l) => <span className="text-xs text-faint">{new Date(l.created_at).toLocaleString("es-PE")}</span>,
  },
];

function isJson(value: string): boolean {
  const firstNewline = value.indexOf("\n");
  const body = firstNewline === -1 ? "" : value.slice(firstNewline + 1);
  if (!body.trim()) return false;
  try {
    JSON.parse(body);
    return true;
  } catch {
    return false;
  }
}

export default function DeveloperCenter() {
  const { session } = useAuth();
  const [tab, setTab] = useState("Endpoints");
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [logs, setLogs] = useState<ApiLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedSlug, setSelectedSlug] = useState("");
  const [lang, setLang] = useState("curl");

  // Sandbox
  const [sandboxKey, setSandboxKey] = useState("");
  const [sandboxInput, setSandboxInput] = useState("¿Cuánto stock queda?");
  const [sandboxResult, setSandboxResult] = useState("");
  const [sandboxBusy, setSandboxBusy] = useState(false);

  async function loadDeployments() {
    if (!session) return;
    try {
      const d = await api<{ deployments: Deployment[] }>("/api/v1/deployments", {
        token: session.token,
        organizationId: session.organizationId,
      });
      const healthy = (d.deployments || []).filter((x) => x.status === "healthy");
      setDeployments(healthy);
      if (healthy.length && !selectedSlug) setSelectedSlug(healthy[0].slug);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  async function loadLogs() {
    if (!session) return;
    try {
      const d = await api<{ logs: ApiLog[] }>("/api/v1/deployments/logs", {
        token: session.token,
        organizationId: session.organizationId,
      });
      setLogs(d.logs || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  useEffect(() => {
    void loadDeployments();
    void loadLogs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  useEffect(() => {
    if (tab === "Logs") void loadLogs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, session]);

  async function runSandbox() {
    if (!session || !selectedSlug) return;
    setSandboxBusy(true);
    setSandboxResult("");
    try {
      const res = await fetch(`/api/v1/deployments/${selectedSlug}/query`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${sandboxKey || session.token}`,
          "Content-Type": "application/json",
          "X-Organization-Id": session.organizationId,
        },
        body: JSON.stringify({ input: sandboxInput }),
      });
      const text = await res.text();
      setSandboxResult(`${res.status}\n${text}`);
    } catch (e) {
      setSandboxResult(e instanceof Error ? e.message : "Error");
    } finally {
      setSandboxBusy(false);
    }
  }

  const sandboxStatus = sandboxResult.includes("\n") ? sandboxResult.slice(0, sandboxResult.indexOf("\n")) : "";
  const sandboxBody = sandboxResult.includes("\n")
    ? sandboxResult.slice(sandboxResult.indexOf("\n") + 1)
    : sandboxResult;

  return (
    <div>
      <PageHeader title="Developer Center" subtitle="Consume tus agentes desde ERP/CRM/WMS: API pública, logs y sandbox." />
      <ErrorInline message={error} />

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          {["Endpoints", "Logs", "Sandbox"].map((t) => (
            <TabsTrigger key={t} value={t}>
              {t}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="Endpoints">
          {loading ? (
            <Panel className="p-4">
              <SkeletonBlock rows={4} />
            </Panel>
          ) : deployments.length === 0 ? (
            <Panel>
              <EmptyState
                icon={Terminal}
                title="Sin deployments healthy"
                body="Despliega un agente a production para obtener su endpoint público."
              />
            </Panel>
          ) : (
            <div className="flex flex-col gap-4">
              <Panel>
                <div className="panel-body grid gap-4 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
                  <Field label="Deployment" hint="Solo se listan los que están healthy.">
                    <Select value={selectedSlug} onChange={(e) => setSelectedSlug(e.target.value)}>
                      {deployments.map((d) => (
                        <option key={d.id} value={d.slug}>
                          {d.slug}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <KeyValue
                    columns={2}
                    items={[
                      { key: "Método", value: "POST", mono: true },
                      { key: "Ruta", value: `/api/v1/deployments/${selectedSlug || "…"}/query`, mono: true },
                      { key: "Auth", value: "Bearer token", mono: true },
                      { key: "Formato", value: "JSON", mono: true },
                    ]}
                  />
                </div>
              </Panel>

              <Panel>
                <Tabs value={lang} onValueChange={setLang} variant="pill" className="p-4">
                  <TabsList className="mb-3">
                    {Object.entries(SNIPPETS).map(([key, info]) => (
                      <TabsTrigger key={key} value={key}>
                        {info.label}
                      </TabsTrigger>
                    ))}
                  </TabsList>
                  {Object.entries(SNIPPETS).map(([key, info]) => (
                    <TabsContent key={key} value={key} className="mt-0">
                      <CodeBlock
                        code={info.code(selectedSlug)}
                        language={info.language}
                        filename={`query.${key}`}
                      />
                    </TabsContent>
                  ))}
                </Tabs>
              </Panel>
            </div>
          )}
        </TabsContent>

        <TabsContent value="Logs">
          <DataTable
            columns={LOG_COLUMNS}
            rows={logs}
            rowKey={(l) => l.id}
            loading={loading}
            stickyHeader
            empty={
              <EmptyState
                icon={ListBullets}
                title="Sin llamadas"
                body="Aún no hay llamadas a la API pública."
              />
            }
          />
        </TabsContent>

        <TabsContent value="Sandbox">
          <Panel className="p-4">
            <div className="flex flex-col gap-4">
              <div className="grid gap-4 lg:grid-cols-2">
                <Field label="Deployment" hint="La prueba se ejecuta contra el deployment elegido.">
                  <Select value={selectedSlug} onChange={(e) => setSelectedSlug(e.target.value)}>
                    {deployments.map((d) => (
                      <option key={d.id} value={d.slug}>
                        {d.slug}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="API key" hint="Vacío = se usa el token de tu sesión del portal.">
                  <PasswordInput
                    value={sandboxKey}
                    onChange={(e) => setSandboxKey(e.target.value)}
                    placeholder="zent_sk_live_..."
                    autoComplete="off"
                  />
                </Field>
              </div>
              <Field label="Input">
                <Textarea
                  className="min-h-20"
                  value={sandboxInput}
                  onChange={(e) => setSandboxInput(e.target.value)}
                />
              </Field>
              <div>
                <Button
                  variant="primary"
                  loading={sandboxBusy}
                  leadingIcon={Play}
                  disabled={!selectedSlug}
                  onClick={() => void runSandbox()}
                >
                  Probar
                </Button>
              </div>
              {sandboxResult && (
                <CodeBlock
                  code={sandboxBody || "// sin cuerpo en la respuesta"}
                  language={isJson(sandboxResult) ? "json" : "text"}
                  filename={sandboxStatus ? `HTTP ${sandboxStatus}` : "respuesta"}
                  actions={
                    sandboxStatus ? (
                      <StatusBadge
                        status={Number(sandboxStatus) < 400 ? "healthy" : "failed"}
                        label={`HTTP ${sandboxStatus}`}
                      />
                    ) : undefined
                  }
                />
              )}
            </div>
          </Panel>
        </TabsContent>
      </Tabs>
    </div>
  );
}
